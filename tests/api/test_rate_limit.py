
import boto3
import pytest
from moto import mock_aws

from api.rate_limit import check_rate_limit

TABLE = "rate_limits"


@pytest.fixture
def table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def test_allows_under_hourly_limit(table):
    for _ in range(20):
        allowed, _ = check_rate_limit("1.2.3.4", table=table)
    assert allowed is True


def test_blocks_over_hourly_limit(table):
    for _ in range(20):
        check_rate_limit("1.2.3.4", table=table)
    allowed, reason = check_rate_limit("1.2.3.4", table=table)
    assert allowed is False
    assert "hour" in reason.lower()


def test_different_ips_are_independent(table):
    for _ in range(21):
        check_rate_limit("1.1.1.1", table=table)
    allowed, _ = check_rate_limit("2.2.2.2", table=table)
    assert allowed is True


def test_fails_open_on_exception():
    # Pass a broken table that raises on update_item
    class BrokenTable:
        def update_item(self, **kwargs):
            raise Exception("DynamoDB down")
    allowed, reason = check_rate_limit("1.2.3.4", table=BrokenTable())
    assert allowed is True
