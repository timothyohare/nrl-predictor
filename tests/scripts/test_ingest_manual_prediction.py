"""Tests for scripts/ingest_manual_prediction.py — validates a pasted
Claude Pro prediction and writes it into the real predictions table in the
exact shape v1/agent/lambda_handler.py writes, so it flows through the
existing API/frontend unchanged."""
import json

import boto3
import pytest
from moto import mock_aws

from scripts.ingest_manual_prediction import (
    build_prediction_row,
    ingest_prediction,
    ingest_prediction_dict,
    load_prediction,
    next_generation,
)
from v1.agent.schema import ValidationError

REGION = "ap-southeast-2"


@pytest.fixture
def predictions_table():
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        resource.create_table(
            TableName="predictions",
            KeySchema=[{"AttributeName": "matchId", "KeyType": "HASH"},
                       {"AttributeName": "generatedAt", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "matchId", "AttributeType": "S"},
                                  {"AttributeName": "generatedAt", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield resource.Table("predictions")


def _valid_raw(**overrides):
    raw = {
        "predicted_winner": "Panthers",
        "predicted_margin": 8,
        "confidence": "MEDIUM",
        "key_factors": ["Home ground advantage", "Better recent form"],
        "reasoning": "The Panthers have won 4 of their last 5 and are at home.",
        "data_freshness": "2026-07-27T09:00:00+00:00",
    }
    raw.update(overrides)
    return raw


def test_load_prediction_reads_plain_json(tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text(json.dumps(_valid_raw()))
    assert load_prediction(path)["predicted_winner"] == "Panthers"


def test_load_prediction_unwraps_markdown_code_fence(tmp_path):
    """A copy-paste from a Claude Pro chat almost always wraps the JSON in a
    ```json fence — the automated agent has the exact same problem
    (see v1/agent/graph.py's _extract_prediction_json), so this must be at
    least as tolerant."""
    path = tmp_path / "prediction.json"
    path.write_text(f"```json\n{json.dumps(_valid_raw())}\n```")
    assert load_prediction(path)["predicted_winner"] == "Panthers"


def test_load_prediction_strips_surrounding_prose(tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text(
        "Here's my prediction:\n\n" + json.dumps(_valid_raw()) + "\n\nLet me know if you need anything else!"
    )
    assert load_prediction(path)["predicted_winner"] == "Panthers"


def test_load_prediction_raises_clear_error_on_no_json(tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text("I couldn't find enough information to make a prediction.")
    with pytest.raises(ValueError, match="Could not find"):
        load_prediction(path)


def test_next_generation_counts_only_ok_rows(predictions_table):
    predictions_table.put_item(Item={"matchId": "m1", "generatedAt": "t1", "status": "OK"})
    predictions_table.put_item(Item={"matchId": "m1", "generatedAt": "t2", "status": "OK"})
    predictions_table.put_item(Item={"matchId": "m1", "generatedAt": "t3", "status": "FAILED"})
    assert next_generation(predictions_table, "m1") == 3


def test_next_generation_is_one_when_no_existing_rows(predictions_table):
    assert next_generation(predictions_table, "no-such-match") == 1


def test_build_prediction_row_stamps_required_fields():
    row = build_prediction_row(
        _valid_raw(), match_id="round-11-panthers-v-broncos", round_number=11,
        generated_at="2026-07-27T10:00:00+00:00", generation=2,
    )
    assert row["matchId"] == "round-11-panthers-v-broncos"
    assert row["roundNumber"] == 11
    assert row["staleness_flag"] is False
    assert row["status"] == "OK"
    assert row["generation"] == 2
    assert "prompt_version" in row
    assert row["generatedAt"] == "2026-07-27T10:00:00+00:00"


def test_build_prediction_row_defaults_model_used():
    row = build_prediction_row(
        _valid_raw(), match_id="m", round_number=1,
        generated_at="2026-07-27T10:00:00+00:00", generation=1,
    )
    assert row["model_used"] == "manual-claude-pro"


def test_build_prediction_row_preserves_provided_model_used_and_generated_at():
    raw = _valid_raw(model_used="claude-opus-5", generated_at="2026-01-01T00:00:00+00:00")
    row = build_prediction_row(
        raw, match_id="m", round_number=1,
        generated_at="2026-07-27T10:00:00+00:00", generation=1,
    )
    assert row["model_used"] == "claude-opus-5"
    assert row["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert row["generatedAt"] == "2026-01-01T00:00:00+00:00"


def test_build_prediction_row_normalises_team_name():
    row = build_prediction_row(
        _valid_raw(predicted_winner="Sea Eagles"), match_id="m", round_number=1,
        generated_at="now", generation=1,
    )
    assert row["predicted_winner"] == "sea-eagles"


def test_build_prediction_row_rejects_invalid_confidence():
    with pytest.raises(ValidationError):
        build_prediction_row(
            _valid_raw(confidence="MAYBE"), match_id="m", round_number=1,
            generated_at="now", generation=1,
        )


def test_build_prediction_row_rejects_unknown_team():
    with pytest.raises(ValidationError):
        build_prediction_row(
            _valid_raw(predicted_winner="Not A Team"), match_id="m", round_number=1,
            generated_at="now", generation=1,
        )


def test_ingest_prediction_writes_to_table(predictions_table, tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text(json.dumps(_valid_raw()))

    row = ingest_prediction(
        predictions_table, path, match_id="round-11-panthers-v-broncos", round_number=11,
    )

    items = predictions_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["matchId"] == "round-11-panthers-v-broncos"
    assert items[0]["generation"] == 1
    assert row["matchId"] == "round-11-panthers-v-broncos"


def test_ingest_prediction_dry_run_skips_write(predictions_table, tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text(json.dumps(_valid_raw()))

    row = ingest_prediction(
        predictions_table, path, match_id="round-11-panthers-v-broncos", round_number=11,
        dry_run=True,
    )

    assert predictions_table.scan()["Items"] == []
    assert row["matchId"] == "round-11-panthers-v-broncos"


def test_ingest_prediction_increments_generation_across_calls(predictions_table, tmp_path):
    path = tmp_path / "prediction.json"
    path.write_text(json.dumps(_valid_raw()))

    first = ingest_prediction(predictions_table, path, match_id="m", round_number=11)
    second = ingest_prediction(predictions_table, path, match_id="m", round_number=11)

    assert first["generation"] == 1
    assert second["generation"] == 2


def test_ingest_prediction_dict_writes_without_any_file(predictions_table):
    """No file I/O at all — for a caller (or Claude, generating the
    prediction directly in a Claude Code session) that already has the
    prediction as an in-memory dict."""
    row = ingest_prediction_dict(
        predictions_table, _valid_raw(), match_id="round-11-panthers-v-broncos", round_number=11,
    )

    items = predictions_table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["matchId"] == "round-11-panthers-v-broncos"
    assert row["generation"] == 1


def test_ingest_prediction_dict_dry_run_skips_write(predictions_table):
    row = ingest_prediction_dict(
        predictions_table, _valid_raw(), match_id="m", round_number=11, dry_run=True,
    )
    assert predictions_table.scan()["Items"] == []
    assert row["matchId"] == "m"


def test_ingest_prediction_delegates_to_dict_version(predictions_table, tmp_path):
    """ingest_prediction(path=...) and ingest_prediction_dict(raw=...) must
    produce identical rows — the file-based path is just a thin loader."""
    path = tmp_path / "prediction.json"
    path.write_text(json.dumps(_valid_raw()))

    from_file = ingest_prediction(predictions_table, path, match_id="m", round_number=11, dry_run=True)
    from_dict = ingest_prediction_dict(predictions_table, _valid_raw(), match_id="m", round_number=11, dry_run=True)

    assert from_file["predicted_winner"] == from_dict["predicted_winner"]
    assert from_file["roundNumber"] == from_dict["roundNumber"]
