"""
Spike: Zero Tackle & The Roar
Tests article scraping from the two main NRL journalism sources.

What we want:
  - Injury/team news articles (text for LLM consumption)
  - Journalist tips for the round
  - Article publication timestamps (freshness matters)
  - Whether RSS feeds are available (much more reliable than HTML scraping)

Strategy:
  1. Try RSS/Atom feed first (structured, stable)
  2. Fall back to HTML scraping if RSS unavailable or incomplete
  3. Extract article body text for S3 storage
"""

import json
import time
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def get(url, label):
    print(f"\n[GET] {label}")
    print(f"      {url}")
    t0 = time.time()
    try:
        r = SESSION.get(url, timeout=10)
        elapsed = time.time() - t0
        print(f"      Status: {r.status_code}  |  {elapsed:.2f}s  |  {len(r.content):,} bytes")
        print(f"      Content-Type: {r.headers.get('Content-Type', '?')}")
        return r
    except Exception as e:
        print(f"      ERROR: {type(e).__name__}: {e}")
        return None

def section(title):
    print(f"\n{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}")

def extract_article_text(soup):
    """Extract clean article body text from a BeautifulSoup object."""
    # Remove noise elements
    for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                               "aside", ".advertisement", ".social-share"]):
        tag.decompose()

    # Try common article body selectors
    selectors = [
        "article",
        "[class*='article-body']",
        "[class*='post-content']",
        "[class*='entry-content']",
        ".content-body",
        "main",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            # Clean up excessive whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:3000]  # cap at 3000 chars for prompt budget
    return soup.get_text(separator="\n", strip=True)[:2000]

# ── Test 1: Zero Tackle ───────────────────────────────────────────────────────

def test_zero_tackle():
    section("1. Zero Tackle (zerotackle.com)")

    base = "https://www.zerotackle.com"

    # Try RSS first
    rss_candidates = [
        f"{base}/feed/",
        f"{base}/rss/",
        f"{base}/feed.xml",
        f"{base}/category/nrl/feed/",
    ]

    rss_found = False
    for rss_url in rss_candidates:
        r = get(rss_url, "RSS feed attempt")
        if r and r.status_code == 200 and (
            "xml" in r.headers.get("Content-Type", "") or
            r.text.strip().startswith("<?xml")
        ):
            rss_found = True
            print(f"\n  ✓ RSS feed found at {rss_url}")
            soup = BeautifulSoup(r.text, "xml")
            items = soup.find_all("item")
            print(f"  Items in feed: {len(items)}")
            for item in items[:5]:
                title = item.find("title")
                pub   = item.find("pubDate")
                link  = item.find("link")
                print(f"    [{pub.text[:16] if pub else '?'}] {title.text[:60] if title else '?'}")
                print(f"      {link.text[:80] if link else '?'}")

            # Fetch and extract text from the first relevant article
            injury_items = [i for i in items if any(
                kw in (i.find("title").text if i.find("title") else "").lower()
                for kw in ["team list", "injury", "team sheet", "late change", "tips"]
            )]
            if injury_items:
                test_item = injury_items[0]
            elif items:
                test_item = items[0]
            else:
                test_item = None

            if test_item:
                article_url = test_item.find("link").text if test_item.find("link") else None
                if article_url:
                    ar = get(article_url, "Article body fetch")
                    if ar and ar.status_code == 200:
                        soup2 = BeautifulSoup(ar.text, "lxml")
                        text = extract_article_text(soup2)
                        print(f"\n  Article text sample ({len(text)} chars):")
                        print(f"  {'-'*40}")
                        print(f"  {text[:500]}")
                        print(f"  {'-'*40}")
            break

    if not rss_found:
        print("\n  ✗ No RSS feed found — falling back to HTML scrape")

        # Try scraping the homepage for article links
        r = get(base, "Homepage scrape")
        if r and r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            # Look for article links
            articles = soup.select("article, .post, [class*='article']")
            print(f"\n  Article elements found: {len(articles)}")

            links = soup.find_all("a", href=True)
            nrl_links = [
                a["href"] for a in links
                if any(kw in a["href"].lower() for kw in
                       ["team-list", "injury", "tips", "preview", "nrl"])
            ][:10]
            print(f"  NRL-relevant links found: {len(nrl_links)}")
            for lnk in nrl_links[:6]:
                print(f"    {urljoin(base, lnk)}")

            if nrl_links:
                test_url = urljoin(base, nrl_links[0])
                ar = get(test_url, "First article body")
                if ar and ar.status_code == 200:
                    soup2 = BeautifulSoup(ar.text, "lxml")
                    text = extract_article_text(soup2)
                    print(f"\n  Article text sample ({len(text)} chars):")
                    print(f"  {'-'*40}")
                    print(f"  {text[:500]}")
                    print(f"  {'-'*40}")

# ── Test 2: The Roar ──────────────────────────────────────────────────────────

def test_the_roar():
    section("2. The Roar (theroar.com.au)")

    base = "https://www.theroar.com.au"

    # The Roar has an NRL section
    rss_candidates = [
        f"{base}/feed/",
        f"{base}/nrl/feed/",
        f"{base}/rugby-league/feed/",
    ]

    rss_found = False
    for rss_url in rss_candidates:
        r = get(rss_url, "RSS feed attempt")
        if r and r.status_code == 200 and (
            "xml" in r.headers.get("Content-Type", "") or
            r.text.strip().startswith("<?xml")
        ):
            rss_found = True
            print(f"\n  ✓ RSS feed found at {rss_url}")
            soup = BeautifulSoup(r.text, "xml")
            items = soup.find_all("item")
            print(f"  Items in feed: {len(items)}")
            for item in items[:5]:
                title = item.find("title")
                pub   = item.find("pubDate")
                link  = item.find("link")
                print(f"    [{pub.text[:16] if pub else '?'}] {title.text[:60] if title else '?'}")
            break

    if not rss_found:
        print("\n  ✗ No RSS found — scraping NRL section page")
        r = get(f"{base}/nrl/", "NRL section page")
        if r and r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            headlines = soup.select("h1, h2, h3, .article-title, [class*='headline']")
            print(f"\n  Headlines found: {len(headlines)}")
            for h in headlines[:8]:
                text = h.get_text(strip=True)
                if len(text) > 15:
                    print(f"    {text[:80]}")

            # Grab links to tip articles
            all_links = soup.find_all("a", href=True)
            tip_links = [
                a["href"] for a in all_links
                if any(kw in a.get_text().lower() for kw in
                       ["tips", "preview", "team list", "injury"])
            ][:5]
            print(f"\n  Tip/preview article links: {len(tip_links)}")
            for lnk in tip_links:
                print(f"    {urljoin(base, lnk)}")

# ── Test 3: NRL.com News ──────────────────────────────────────────────────────

def test_nrl_news():
    section("3. nrl.com News / Team List Articles")

    # NRL.com publishes team lists as structured news — often the most reliable source
    candidates = [
        ("NRL news feed", "https://www.nrl.com/news/"),
        ("NRL team lists tag", "https://www.nrl.com/news/?tagKey=team-lists"),
        ("NRL news JSON", "https://www.nrl.com/news/data?type=article&limit=20"),
    ]

    for label, url in candidates:
        r = get(url, label)
        if r and r.status_code == 200:
            ct = r.headers.get("Content-Type", "")
            if "json" in ct:
                try:
                    data = r.json()
                    print(f"  JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    articles = data.get("articles", data.get("data", []))
                    print(f"  Articles found: {len(articles)}")
                    for a in articles[:3]:
                        print(f"    [{a.get('publishedAt','?')[:10]}] {a.get('title','?')[:70]}")
                except Exception as e:
                    print(f"  JSON parse error: {e}")
            else:
                soup = BeautifulSoup(r.text, "lxml")
                # Check for embedded JSON (Next.js pattern)
                script = soup.find("script", id="__NEXT_DATA__")
                if script:
                    print(f"\n  ✓ Found __NEXT_DATA__ ({len(script.text):,} chars)")
                    try:
                        nd = json.loads(script.text)
                        # Try to find article list in page props
                        props = nd.get("props", {}).get("pageProps", {})
                        print(f"  pageProps keys: {list(props.keys())[:10]}")
                    except Exception as ex:
                        print(f"  __NEXT_DATA__ parse error: {ex}")
                else:
                    articles = soup.select("article, .news-feed__item, [class*='article']")
                    print(f"  Article elements: {len(articles)}")

# ── Summary ───────────────────────────────────────────────────────────────────

def summarise():
    section("Summary / Recommendations")
    print("""
  ARTICLE FETCHING STRATEGY:

  1. RSS feeds (if available)
       → Subscribe to Zero Tackle + The Roar NRL RSS
       → Poll every 2 hours Thu–Sat; store new articles to S3
       → Key: {source}/{slug}.txt  e.g.  zerotackle/2026-05-15-team-lists.txt
       → Only store articles containing NRL team/injury keywords

  2. nrl.com __NEXT_DATA__ pattern
       → NRL.com is Next.js — full page data lives in <script id="__NEXT_DATA__">
       → Parse this as JSON to get article lists and team sheet data without
         fragile CSS selector scraping
       → Most stable approach for nrl.com specifically

  3. HTML fallback
       → Use extract_article_text() helper defined in this file
       → Store raw text in S3; never store HTML (too large, too fragile)

  WHAT TO PASS TO THE AGENT:
    Don't send full articles — they're too long and costly.
    Instead, run a cheap Haiku pre-processing step:
      Prompt: "Extract all player injury/availability mentions from this article.
               Return JSON: [{player, team, status, detail}]"
    Store the extracted JSON alongside the raw text in S3.
    The main agent tool search_articles() returns the extracted JSON,
    not the raw text.

  FRESHNESS RULE:
    Tag every stored article with scraped_at timestamp.
    Agent tool: only return articles scraped within the last 48 hours.
    Older articles are kept for audit but excluded from agent context.
    """)

# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    test_zero_tackle()
    test_the_roar()
    test_nrl_news()
    summarise()

if __name__ == "__main__":
    run()
