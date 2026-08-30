from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from scrapers.articles.body import extract_body_text
from scrapers.articles.rss import fetch_rss, parse_rss
from scrapers.shared.http_client import ScraperError
from scrapers.shared.models import Article

RSS_FIXTURE = Path(__file__).parent.parent / "fixtures" / "zerotackle_rss.xml"
BODY_FIXTURE = Path(__file__).parent.parent / "fixtures" / "article_body.html"

NRL_TEAMS = ["Panthers", "Broncos", "Storm", "Roosters", "Sharks", "Raiders",
             "Warriors", "Cowboys", "Titans", "Eels", "Dragons", "Bulldogs",
             "Knights", "Sea Eagles", "Rabbitohs", "Wests Tigers", "Dolphins"]


def make_rss_with_dates(hours_ago_list: list[int]) -> str:
    items = ""
    for h in hours_ago_list:
        pub = (datetime.now(UTC) - timedelta(hours=h)).strftime("%a, %d %b %Y %H:%M:%S +0000")
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
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=now)
    assert all(isinstance(a, Article) for a in articles)


def test_parse_rss_filters_older_than_48h():
    xml = make_rss_with_dates([10, 30, 50, 72])
    now = datetime.now(UTC)
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=now)
    assert all(a for a in articles)
    assert len(articles) == 2  # only 10h and 30h articles


def test_parse_rss_filters_non_nrl_articles():
    xml = RSS_FIXTURE.read_text()
    now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=now)
    titles = [a.title for a in articles]
    assert not any("AFL" in t for t in titles)


def test_parse_rss_source_field():
    xml = make_rss_with_dates([5])
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=datetime.now(UTC))
    assert articles[0].source == "Zero Tackle"


def test_fetch_rss_returns_response_body():
    with patch(
        "scrapers.articles.rss.get_with_retry",
        return_value=(200, "<rss><channel/></rss>"),
    ) as mock_get:
        body = fetch_rss("https://www.zerotackle.com/feed/")

    assert body == "<rss><channel/></rss>"
    assert mock_get.call_args.args[0] == "https://www.zerotackle.com/feed/"


def test_fetch_rss_propagates_fetch_errors():
    with patch(
        "scrapers.articles.rss.get_with_retry",
        side_effect=ScraperError("Failed after 3 attempts; last status 503"),
    ):
        with pytest.raises(ScraperError):
            fetch_rss("https://www.zerotackle.com/feed/")


def test_parse_rss_skips_entry_missing_required_fields():
    recent = (datetime.now(UTC) - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    xml = f"""<?xml version="1.0"?><rss version="2.0"><channel>
      <item>
        <title>Panthers recall star for finals</title>
        <link>https://example.com/ok/</link>
        <pubDate>{recent}</pubDate>
        <description>Panthers news.</description>
      </item>
      <item>
        <title>Panthers injury latest</title>
        <link>https://example.com/no-date/</link>
        <description>Missing pubDate, must be dropped.</description>
      </item>
    </channel></rss>"""
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=datetime.now(UTC))
    assert [a.url for a in articles] == ["https://example.com/ok/"]


def test_parse_rss_skips_entry_with_unparseable_pubdate():
    recent = (datetime.now(UTC) - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    xml = f"""<?xml version="1.0"?><rss version="2.0"><channel>
      <item>
        <title>Panthers name unchanged side</title>
        <link>https://example.com/ok/</link>
        <pubDate>{recent}</pubDate>
        <description>Panthers news.</description>
      </item>
      <item>
        <title>Panthers halfback in doubt</title>
        <link>https://example.com/bad-date/</link>
        <pubDate>not actually a date</pubDate>
        <description>Panthers news.</description>
      </item>
    </channel></rss>"""
    articles = parse_rss(xml, "Zero Tackle", nrl_teams=NRL_TEAMS, now=datetime.now(UTC))
    assert [a.url for a in articles] == ["https://example.com/ok/"]


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
