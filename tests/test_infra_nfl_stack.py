"""NflPredictorStack (infra/nfl_stack.py) — spec criterion 3.9, text-parsed like
test_infra_handler_paths.py so no CDK synth / Docker is needed in the unit suite."""
from __future__ import annotations

import importlib
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).parent.parent
_INFRA = _REPO / "infra"
_STACK = (_INFRA / "nfl_stack.py").read_text() if (_INFRA / "nfl_stack.py").exists() else ""


def _calls(text: str, opener: str) -> list[str]:
    """Every `opener(...)` call in `text`, parentheses balanced."""
    blocks = []
    for m in re.finditer(re.escape(opener) + r"\(", text):
        depth, i = 0, m.end() - 1
        while True:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
            if depth == 0:
                break
        blocks.append(text[m.start():i])
    return blocks


def _handlers() -> list[str]:
    return re.findall(r'handler="([\w.]+)"', _STACK)


def test_stack_declares_the_orchestrator_handler():
    assert _handlers() == ["nfl.orchestrator.lambda_handler.lambda_handler"]


@pytest.mark.parametrize("handler", _handlers() or ["<missing>"])
def test_handler_resolves_to_a_callable(handler):
    module_path, func_name = handler.rsplit(".", 1)
    module = importlib.import_module(module_path)
    assert callable(getattr(module, func_name, None))


def test_season_flag_ships_off_and_flags_the_licence_question():
    m = re.search(r"^NFL_SEASON_ACTIVE\s*=\s*(\w+)", _STACK, re.MULTILINE)
    assert m and m.group(1) == "False"
    preamble = _STACK[: m.start()]
    assert re.search(r"licen[cs]e", preamble, re.IGNORECASE)
    assert "nflverse" in preamble


def test_every_rule_is_gated_by_the_season_flag():
    rules = _calls(_STACK, "events.Rule")
    assert len(rules) == 1
    assert all("enabled=NFL_SEASON_ACTIVE" in r for r in rules)


def test_daily_rule_at_noon_utc_with_empty_payload():
    (rule,) = _calls(_STACK, "events.Rule")
    assert 'minute="0"' in rule and 'hour="12"' in rule
    assert "week_day" not in rule
    assert "RuleTargetInput.from_object({})" in rule


def test_no_hardcoded_season_payload():
    assert '"season":' not in _STACK


def test_both_tables_are_pay_per_request_with_the_spec_keys():
    tables = _calls(_STACK, "dynamodb.Table")
    assert len(tables) == 2
    assert all("billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST" in t for t in tables)
    games = next(t for t in tables if 'table_name="nfl_games"' in t)
    predictions = next(t for t in tables if 'table_name="nfl_predictions"' in t)
    assert 'name="matchId"' in games and "sort_key" not in games
    assert 'name="matchId"' in predictions and 'name="generatedAt"' in predictions


def test_lambda_sizing_and_table_env_vars():
    (fn,) = _calls(_STACK, "_lambda.Function")
    assert 'function_name="nfl-predictor-orchestrator"' in fn
    assert "memory_size=512" in fn
    assert "cdk.Duration.seconds(60)" in fn
    for var in ("NFL_GAMES_TABLE", "NFL_PREDICTIONS_TABLE", "NFL_GAMES_CSV_URL"):
        assert f'"{var}"' in _STACK


def test_orchestrator_reserved_concurrency_is_one():
    """Review N2: idempotency is check-then-put, so two overlapping invocations
    (schedule + manual) must never run at once."""
    fn = next(f for f in _calls(_STACK, "_lambda.Function")
              if 'function_name="nfl-predictor-orchestrator"' in f)
    assert "reserved_concurrent_executions=1," in fn


def test_layer_bundles_tzdata():
    """N1: the Lambda runtime image must not be relied on for the tz database."""
    (layer,) = _calls(_STACK, "_lambda.LayerVersion")
    assert "tzdata" in layer


def test_alerts_go_to_the_existing_topic_imported_not_recreated():
    assert "sns.Topic.from_topic_arn" in _STACK
    assert "arn:aws:sns:ap-southeast-2:810429055117:nrl-predictor-alerts" in _STACK
    assert "sns.Topic(" not in _STACK


def test_unpredicted_games_alarm_is_a_24h_ignore_pulse():
    alarms = _calls(_STACK, "cloudwatch.Alarm")
    assert len(alarms) == 2
    pulse = next(a for a in alarms if '"UnpredictedGames"' in a)
    assert 'namespace="NflPredictor"' in pulse
    assert "period=cdk.Duration.hours(24)" in pulse
    assert "TreatMissingData.IGNORE" in pulse
    assert "datapoints_to_alarm=1" in pulse
    errors = next(a for a in alarms if "metric_errors" in a)
    assert "TreatMissingData.IGNORE" in errors
    # The 2026-08-30 incident: never the 1h / NOT_BREACHING pattern for a daily pulse.
    assert "NOT_BREACHING" not in _STACK
    assert "Duration.hours(1)" not in _STACK
    assert _STACK.count("SnsAction(alert_topic)") == 2


def test_put_metric_data_is_scoped_to_the_nfl_namespace():
    assert '"cloudwatch:PutMetricData"' in _STACK
    assert '{"cloudwatch:namespace": "NflPredictor"}' in _STACK


def test_app_instantiates_the_nfl_stack():
    app = (_INFRA / "app.py").read_text()
    assert "from nfl_stack import NflPredictorStack" in app
    assert re.search(r'NflPredictorStack\(app, "NflPredictorStack"', app)


def test_nrl_stacks_are_unchanged_from_main():
    if subprocess.run(["git", "rev-parse", "--verify", "-q", "main"], cwd=_REPO,
                      capture_output=True).returncode != 0:
        pytest.skip("no local main branch to compare against")
    result = subprocess.run(
        ["git", "diff", "--quiet", "main", "--", "infra/v1_stack.py", "infra/v2_stack.py"],
        cwd=_REPO,
    )
    assert result.returncode == 0


def test_lambda_asset_never_ships_dotfiles():
    """The repo-root asset must exclude dotfiles: `.env` holds API keys, and
    `.mypy_cache` alone is ~38 MB."""
    m = re.search(r"^_ASSET_EXCLUDE = \[(.*?)^\]", _STACK, re.MULTILINE | re.DOTALL)
    assert m
    patterns = re.findall(r'"([^"]+)"', m.group(1))
    assert ".*" in patterns
    assert "*.egg-info" in patterns


def _synth_nfl_assets(tree: Path) -> list[Path]:
    """Synthesise the real NflPredictorStack with its REPO_ROOT pointed at `tree`,
    returning every Lambda code asset dir. Docker bundling (the tzdata layer) is
    skipped — only the code assets matter. REPO_ROOT is patched to an absolute path
    because the jsii runtime resolves relative paths against its own cwd."""
    cdk = pytest.importorskip("aws_cdk")
    import sys

    sys.path.insert(0, str(_INFRA))
    nfl_stack = importlib.import_module("nfl_stack")
    original_root = nfl_stack.REPO_ROOT
    try:
        nfl_stack.REPO_ROOT = str(tree)
        outdir = tree.parent / "cdk.out"
        app = cdk.App(outdir=str(outdir), context={
            "aws:cdk:bundling-stacks": [],
            "aws:cdk:enable-asset-metadata": True,
        })
        nfl_stack.NflPredictorStack(app, "NflPredictorStack")
        template = app.synth().get_stack_by_name("NflPredictorStack").template
    finally:
        nfl_stack.REPO_ROOT = original_root
        sys.path.remove(str(_INFRA))
    functions = [r for r in template["Resources"].values() if r["Type"] == "AWS::Lambda::Function"]
    assert functions
    return [outdir / f["Metadata"]["aws:asset:path"] for f in functions]


def test_synthesised_lambda_assets_contain_no_dotfiles(tmp_path):
    """Review N12: prove the exclude list on a real synth, not just that ".*" is in
    it — a root .env, a nested .env and a nested dot-directory must all be absent,
    while ordinary source next to them still ships."""
    planted = [".env", "common/.env", "nfl/sub/.env.local", "common/.cache/secret.py"]
    shipped = ["common/a.py", "nfl/sub/b.py"]
    tree = tmp_path / "repo"
    for rel in planted + shipped:
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")

    for asset in _synth_nfl_assets(tree):
        files = {p.relative_to(asset).as_posix() for p in asset.rglob("*") if p.is_file()}
        assert set(shipped) <= files
        assert not [f for f in files if any(part.startswith(".") for part in f.split("/"))]
