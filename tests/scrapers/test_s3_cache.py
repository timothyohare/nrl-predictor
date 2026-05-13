import pytest
import boto3
from moto import mock_aws
from scrapers.shared.s3_cache import save_raw, load_raw

BUCKET = "test-bucket"
KEY = "raw-scrapes/test.json"
BODY = '{"foo": "bar"}'


@pytest.fixture
def s3_bucket():
    with mock_aws():
        boto3.client("s3", region_name="ap-southeast-2").create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-2"},
        )
        yield


def test_save_and_load_roundtrip(s3_bucket):
    save_raw(BUCKET, KEY, BODY)
    result = load_raw(BUCKET, KEY)
    assert result == BODY


def test_load_returns_none_for_missing_key(s3_bucket):
    result = load_raw(BUCKET, "raw-scrapes/nonexistent.json")
    assert result is None


def test_save_sets_json_content_type(s3_bucket):
    save_raw(BUCKET, "raw-scrapes/data.json", BODY, content_type="application/json")
    head = boto3.client("s3", region_name="ap-southeast-2").head_object(
        Bucket=BUCKET, Key="raw-scrapes/data.json"
    )
    assert head["ContentType"] == "application/json"


def test_save_sets_html_content_type(s3_bucket):
    save_raw(BUCKET, "raw-scrapes/page.html", "<html/>", content_type="text/html")
    head = boto3.client("s3", region_name="ap-southeast-2").head_object(
        Bucket=BUCKET, Key="raw-scrapes/page.html"
    )
    assert head["ContentType"] == "text/html"


def test_save_default_content_type_is_json(s3_bucket):
    save_raw(BUCKET, KEY, BODY)
    head = boto3.client("s3", region_name="ap-southeast-2").head_object(
        Bucket=BUCKET, Key=KEY
    )
    assert head["ContentType"] == "application/json"
