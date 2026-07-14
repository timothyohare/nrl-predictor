from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from scrapers.articles import lambda_handler as handler_module
from scrapers.shared.models import InjuryMention

TABLE = "injuries"
BUCKET = "raw-bucket"

_HTML = "<html><body><article>Cleary in doubt with a calf strain.</article></body></html>"


def _rss(n_items: int = 1, team: str = "Panthers") -> str:
    items = ""
    for i in range(n_items):
        pub = (datetime.now(UTC) - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items += f"""
        <item>
          <title>{team} injury update {i}</title>
          <link>https://example.com/article-{i}/</link>
          <pubDate>{pub}</pubDate>
        </item>"""
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def _mention(team: str = "Panthers") -> InjuryMention:
    return InjuryMention(player="Nathan Cleary", team=team, status="doubtful", detail="calf strain")


@pytest.fixture
def injuries_table(monkeypatch):
    monkeypatch.setenv("INJURIES_TABLE", TABLE)
    monkeypatch.setenv("RAW_BUCKET", BUCKET)
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3", region_name="ap-southeast-2").create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )
        secret = boto3.client("secretsmanager", region_name="ap-southeast-2").create_secret(
            Name="anthropic-key", SecretString="test-key",
        )
        monkeypatch.setenv("ANTHROPIC_SECRET_ARN", secret["ARN"])
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def _run(rss_xml, mentions=None, body_side_effect=None):
    with patch.object(handler_module, "fetch_rss", return_value=rss_xml), \
         patch.object(handler_module, "fetch_article_body") as body_mock, \
         patch.object(handler_module, "extract_injury_mentions") as extract_mock:
        body_mock.side_effect = body_side_effect or (lambda url: _HTML)
        extract_mock.return_value = mentions if mentions is not None else [_mention()]
        result = handler_module.lambda_handler({}, None)
    return result, body_mock


def test_writes_injury_mention_with_slugged_team(injuries_table):
    _run(_rss())
    items = injuries_table.scan()["Items"]
    assert len(items) == 1
    item = items[0]
    assert item["pk"].startswith("injury#panthers#")
    assert item["team"] == "panthers"
    assert item["player"] == "Nathan Cleary"
    assert item["status"] == "doubtful"
    assert "scraped_at" in item
    # sk must be an ISO timestamp so the 48h-cutoff scan in the injury tool works
    assert item["sk"] == item["scraped_at"]


def test_one_article_failure_does_not_abort_run(injuries_table):
    calls = {"n": 0}

    def flaky(url):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fetch failed")
        return _HTML

    result, _ = _run(_rss(n_items=2), body_side_effect=flaky)
    assert result["mentions_written"] == 1
    assert len(injuries_table.scan()["Items"]) == 1


def test_caps_articles_processed_per_run(injuries_table):
    _, body_mock = _run(_rss(n_items=20))
    assert body_mock.call_count == handler_module._MAX_ARTICLES


def test_returns_run_counts(injuries_table):
    result, _ = _run(_rss(n_items=2))
    assert result["articles_processed"] == 2
    assert result["mentions_written"] >= 1
