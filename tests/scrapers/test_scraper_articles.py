from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from scrapers.articles.rss import parse_rss
from scrapers.articles.body import extract_body_text
from scrapers.shared.models import Article

RSS_FIXTURE = Path(__file__).parent.parent / "fixtures" / "zerotackle_rss.xml"
BODY_FIXTURE = Path(__file__).parent.parent / "fixtures" / "article_body.html"

NRL_TEAMS = ["Panthers", "Broncos", "Storm", "Roosters", "Sharks", "Raiders",
             "Warriors", "Cowboys", "Titans", "Eels", "Dragons", "Bulldogs",
             "Knights", "Sea Eagles", "Rabbitohs", "Wests Tigers", "Dolphins"]


def make_rss_with_dates(hours_ago_list: list[int]) -> str:
    items = ""
    for h in hours_ago_list:
        pub = (datetime.now(timezone.utc) - timedelta(hours=h)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items += f"""
        <item>
          <title>Panthers injury update</title>
          <link>https://example.com/article-{h}/</link>
          <pubDate>{pub}</pubDate>
          <description>Panthers latest.</description>
        </item>"""
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_parse_rss_returns_article_objects():
    xml = RSS_FIXTURE.read_text()
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=now)
    assert all(isinstance(a, Article) for a in articles)


def test_parse_rss_filters_older_than_48h():
    xml = make_rss_with_dates([10, 30, 50, 72])
    now = datetime.now(timezone.utc)
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=now)
    assert all(a for a in articles)
    assert len(articles) == 2  # only 10h and 30h articles


def test_parse_rss_filters_non_nrl_articles():
    xml = RSS_FIXTURE.read_text()
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=now)
    titles = [a.title for a in articles]
    assert not any("AFL" in t for t in titles)


def test_parse_rss_source_field():
    xml = make_rss_with_dates([5])
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=datetime.now(timezone.utc))
    assert articles[0].source == "Zero Tackle"


def test_extract_body_text_strips_html():
    html = BODY_FIXTURE.read_text()
    text = extract_body_text(html)
    assert "<" not in text
    assert ">" not in text


def test_extract_body_text_excludes_nav_and_footer():
    html = BODY_FIXTURE.read_text()
    text = extract_body_text(html)
    assert "Copyright" not in text


def test_extract_body_text_min_length():
    html = BODY_FIXTURE.read_text()
    text = extract_body_text(html)
    assert len(text) >= 100


def test_extract_body_text_contains_article_content():
    html = BODY_FIXTURE.read_text()
    text = extract_body_text(html)
    assert "Cleary" in text
