"""Bounded deterministic input fuzzing; AWS calls are replaced by local mocks."""
import json
import random
from unittest.mock import patch

import pytest

from v1.api import predictions, tournament


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("PREDICTIONS_TABLE", "security-test-predictions")
    monkeypatch.setenv("VARIANT_METRICS_TABLE", "security-test-metrics")
    for key in ("RETROSPECTIVES_TABLE", "RESULTS_TABLE", "ODDS_TABLE", "RATE_LIMITS_TABLE"):
        monkeypatch.delenv(key, raising=False)


def test_seeded_round_strings_are_rejected_before_database_access():
    rng = random.Random(20260927)
    values = ["' OR 1=1--", "../", "<script>", "\x00", "9" * 5000]
    values += ['x' + ''.join(rng.choices('abc<>/012345', k=rng.randrange(1, 128))) for _ in range(300)]
    with patch.object(predictions.boto3, 'resource') as resource:
        for value in values:
            response = predictions.lambda_handler({'pathParameters': {'round': value}}, None)
            assert response['statusCode'] == 400, repr(value)
            assert isinstance(json.loads(response['body'])['error'], str)
        resource.assert_not_called()


@pytest.mark.parametrize('value', ['x', "' OR 1=1--", '\x00', '', '9' * 5000], ids=['text', 'injection', 'nul', 'empty', 'oversize'])
def test_invalid_season_returns_400_not_unhandled_exception(value):
    with patch.object(tournament.boto3, 'resource') as resource:
        response = tournament.lambda_handler({'queryStringParameters': {'season': value}}, None)
        assert response['statusCode'] == 400
        resource.assert_not_called()


def test_out_of_dynamodb_range_round_is_rejected_before_scan():
    with patch.object(predictions.boto3, 'resource') as resource:
        resource.return_value.Table.return_value.scan.return_value = {'Items': []}
        response = predictions.lambda_handler({'pathParameters': {'round': '9' * 100}}, None)
        assert response['statusCode'] == 400
        resource.assert_not_called()
