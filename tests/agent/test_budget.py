import boto3
import pytest
from decimal import Decimal
from moto import mock_aws
from agent.budget import record_usage, get_month_to_date_spend, check_budget, BudgetExceeded

TABLE = "claude_usage"


@pytest.fixture
def ddb_table():
    with mock_aws():
        boto3.client("dynamodb", region_name="ap-southeast-2").create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "yearMonth", "KeyType": "HASH"},
                {"AttributeName": "invokedAt", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "yearMonth", "AttributeType": "S"},
                {"AttributeName": "invokedAt", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="ap-southeast-2").Table(TABLE)


def test_record_usage_writes_record(ddb_table):
    record_usage(input_tokens=1000, output_tokens=200, model="claude-haiku-4-5-20251001", table=ddb_table)
    response = ddb_table.scan()
    assert response["Count"] == 1
    item = response["Items"][0]
    assert "cost_usd" in item
    assert item["input_tokens"] == 1000


def test_get_month_to_date_spend_sums_costs(ddb_table):
    record_usage(1000, 200, "claude-haiku-4-5-20251001", table=ddb_table)
    record_usage(2000, 400, "claude-haiku-4-5-20251001", table=ddb_table)
    spend = get_month_to_date_spend(table=ddb_table)
    assert spend > 0


def test_check_budget_raises_when_exceeded(ddb_table):
    record_usage(10_000_000, 5_000_000, "claude-sonnet-4-6", table=ddb_table)
    with pytest.raises(BudgetExceeded):
        check_budget(threshold_usd=0.01, table=ddb_table)


def test_check_budget_passes_when_under(ddb_table):
    record_usage(100, 50, "claude-haiku-4-5-20251001", table=ddb_table)
    check_budget(threshold_usd=100.0, table=ddb_table)  # should not raise
