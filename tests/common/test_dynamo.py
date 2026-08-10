"""Tests for the shared DynamoDB scan pagination helper (common/dynamo.py)."""
import boto3
import pytest
from moto import mock_aws

from common.dynamo import scan_all

TABLE = "scan-all-test"


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        tbl = boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)
        for i in range(5):
            tbl.put_item(Item={"pk": f"item-{i}", "group": "a"})
        yield tbl


def test_returns_all_items_within_a_single_page(ddb_table):
    items = scan_all(ddb_table)
    assert {i["pk"] for i in items} == {f"item-{i}" for i in range(5)}


def test_follows_last_evaluated_key_across_pages(ddb_table):
    # Limit=2 forces DynamoDB to paginate a 5-item table into 3 pages —
    # a plain single table.scan(Limit=2) would only see the first 2 items.
    items = scan_all(ddb_table, Limit=2)
    assert len(items) == 5
    assert {i["pk"] for i in items} == {f"item-{i}" for i in range(5)}


def test_applies_filter_expression_across_all_pages(ddb_table):
    ddb_table.put_item(Item={"pk": "item-other-group", "group": "b"})
    items = scan_all(
        ddb_table,
        Limit=2,
        FilterExpression="#g = :g",
        ExpressionAttributeNames={"#g": "group"},
        ExpressionAttributeValues={":g": "a"},
    )
    assert len(items) == 5
    assert all(i["group"] == "a" for i in items)
