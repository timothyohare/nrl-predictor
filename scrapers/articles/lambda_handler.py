"""Articles scraper Lambda — RSS → article body → Haiku injury extraction.

Writes injury/availability mentions keyed exactly as the agent's
get_injury_list tool reads them: pk = "injury#{team-slug}#{player-slug}",
sk = scraped_at ISO timestamp (the tool filters sk against a 48h cutoff).
"""
import json
import logging
import os
import re
from datetime import UTC, datetime

import anthropic
import boto3

from common.teams import to_slug
from scrapers.articles.body import extract_body_text, fetch_article_body
from scrapers.articles.haiku_extractor import extract_injury_mentions
from scrapers.articles.rss import fetch_rss, parse_rss
from scrapers.shared.s3_cache import save_raw

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Confirmed by fetcher-spikes/spike_zerotackle.py: both feeds serve RSS without
# auth. The Roar main feed is multi-sport; parse_rss team-filters titles.
_FEEDS = [
    ("Zero Tackle", "https://www.zerotackle.com/feed/"),
    ("The Roar", "https://www.theroar.com.au/feed/"),
]
# Bounds Haiku spend and keeps the run inside the 3-minute Lambda timeout
# (each article costs a delayed HTTP fetch + one Haiku call).
_MAX_ARTICLES = 8
_BODY_CHAR_CAP = 3000


def _get_anthropic_client() -> anthropic.Anthropic:
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["ANTHROPIC_SECRET_ARN"]
    )
    raw = secret["SecretString"]
    api_key = json.loads(raw)["api_key"] if raw.startswith("{") else raw
    return anthropic.Anthropic(api_key=api_key)


def _player_slug(player: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", player.lower()).strip("-")


def lambda_handler(event: dict, context) -> dict:
    table = boto3.resource("dynamodb").Table(os.environ["INJURIES_TABLE"])
    bucket = os.environ["RAW_BUCKET"]
    scraped_at = datetime.now(UTC).isoformat()
    client = _get_anthropic_client()

    articles = []
    seen_urls: set[str] = set()
    for source, url in _FEEDS:
        try:
            xml = fetch_rss(url)
        except Exception:
            logger.warning("RSS fetch failed for %s (%s)", source, url, exc_info=True)
            continue
        save_raw(bucket, f"raw-scrapes/articles/{source}/{scraped_at[:10]}.xml", xml)
        for article in parse_rss(xml, source):
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                articles.append(article)
    articles = articles[:_MAX_ARTICLES]

    processed = 0
    mentions_written = 0
    for article in articles:
        try:
            text = extract_body_text(fetch_article_body(article.url))[:_BODY_CHAR_CAP]
            mentions = extract_injury_mentions(text, client)
        except Exception:
            logger.warning("Article processing failed for %s", article.url, exc_info=True)
            continue
        processed += 1
        for mention in mentions:
            team = to_slug(mention.team)
            table.put_item(Item={
                "pk": f"injury#{team}#{_player_slug(mention.player)}",
                "sk": scraped_at,
                "player": mention.player,
                "team": team,
                "status": mention.status,
                "detail": mention.detail,
                "source": article.source,
                "article_url": article.url,
                "article_title": article.title,
                "published_at": article.published_at,
                "scraped_at": scraped_at,
            })
            mentions_written += 1

    logger.info("Processed %d articles, wrote %d injury mentions", processed, mentions_written)
    return {"articles_processed": processed, "mentions_written": mentions_written}
