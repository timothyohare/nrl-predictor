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


def _function(name: str) -> str:
    return next(f for f in _calls(_STACK, "_lambda.Function") if f'function_name="{name}"' in f)


def test_stack_declares_the_orchestrator_and_api_handlers():
    assert _handlers() == [
        "nfl.orchestrator.lambda_handler.lambda_handler",
        "nfl.api.router.lambda_handler",
    ]


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
    assert len(_calls(_STACK, "_lambda.Function")) == 2
    fn = _function("nfl-predictor-orchestrator")
    assert "memory_size=512" in fn
    assert "cdk.Duration.seconds(60)" in fn
    for var in ("NFL_GAMES_TABLE", "NFL_PREDICTIONS_TABLE", "NFL_GAMES_CSV_URL"):
        assert f'"{var}"' in _STACK


def test_orchestrator_reserved_concurrency_is_one():
    """Review N2: idempotency is check-then-put, so two overlapping invocations
    (schedule + manual) must never run at once."""
    assert "reserved_concurrent_executions=1," in _function("nfl-predictor-orchestrator")


# --- Phase 4: the NFL API (separate HttpApi, user decision Q3) ----------------------

def test_api_lambda_handler_and_env():
    fn = _function("nfl-predictor-api")
    assert 'handler="nfl.api.router.lambda_handler"' in fn
    assert "cdk.Duration.seconds(10)" in fn
    for var in ("NFL_GAMES_TABLE", "NFL_PREDICTIONS_TABLE", "RATE_LIMITS_TABLE"):
        assert f'"{var}"' in fn


def test_api_reads_nfl_tables_and_only_updates_the_rate_limit_table():
    assert "games_table.grant_read_data(api_fn)" in _STACK
    assert "predictions_table.grant_read_data(api_fn)" in _STACK
    assert "grant_read_write_data(api_fn)" not in _STACK
    assert "dynamodb.Table.from_table_arn" in _STACK
    assert "arn:aws:dynamodb:ap-southeast-2:810429055117:table/nrl-rate-limits" in _STACK
    assert 'rate_limits_table.grant(api_fn, "dynamodb:UpdateItem")' in _STACK


def test_separate_http_api_with_nrl_cors():
    (api,) = _calls(_STACK, "apigwv2.HttpApi")
    assert 'api_name="nfl-predictor-api"' in api
    assert "allow_methods=[apigwv2.CorsHttpMethod.GET]" in api
    assert 'allow_origins=["*"]' in api


def test_api_routes():
    routes = re.findall(r'add_routes\(path="([^"]+)", methods=\[apigwv2\.HttpMethod\.GET\]', _STACK)
    assert sorted(routes) == sorted([
        "/health", "/nfl/weeks/current", "/nfl/weeks", "/nfl/predictions/{season}/{week}",
        "/nfl/accuracy",
    ])


def test_api_endpoint_is_an_output():
    assert re.search(r'CfnOutput\(self, "NflApiEndpoint", value=api\.api_endpoint', _STACK)


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


_PLANTED = [".env", "common/.env", "nfl/sub/.env.local", "common/.cache/secret.py"]
_SHIPPED = ["common/a.py", "nfl/sub/b.py"]


def _synth(repo_root: Path, outdir: Path) -> dict:
    """Synthesise the real NflPredictorStack with REPO_ROOT pointed at `repo_root`
    (absolute, because the jsii runtime resolves relative paths against its own
    cwd). Docker bundling (the tzdata layer) is skipped — only the code assets and
    the template matter here."""
    cdk = pytest.importorskip("aws_cdk")
    import sys

    sys.path.insert(0, str(_INFRA))
    nfl_stack = importlib.import_module("nfl_stack")
    original_root = nfl_stack.REPO_ROOT
    try:
        nfl_stack.REPO_ROOT = str(repo_root)
        app = cdk.App(outdir=str(outdir), context={
            "aws:cdk:bundling-stacks": [],
            "aws:cdk:enable-asset-metadata": True,
        })
        nfl_stack.NflPredictorStack(app, "NflPredictorStack")
        return app.synth().get_stack_by_name("NflPredictorStack").template
    finally:
        nfl_stack.REPO_ROOT = original_root
        sys.path.remove(str(_INFRA))


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    """The stack synthesised over a tiny planted tree (dotfiles + ordinary source)."""
    root = tmp_path_factory.mktemp("synth")
    tree = root / "repo"
    for rel in _PLANTED + _SHIPPED:
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    outdir = root / "cdk.out"
    return _synth(tree, outdir), outdir


@pytest.fixture(scope="module")
def repo_synth(tmp_path_factory):
    """The stack synthesised over this repo, exactly as `cdk synth` would ship it."""
    outdir = tmp_path_factory.mktemp("repo-synth") / "cdk.out"
    return _synth(_REPO, outdir), outdir


def _resources(template: dict, kind: str) -> list[dict]:
    return [r for r in template["Resources"].values() if r["Type"] == kind]


def test_synthesised_lambda_assets_contain_no_dotfiles(synth):
    """Review N12: prove the exclude list on a real synth, not just that ".*" is in
    it — a root .env, a nested .env and a nested dot-directory must all be absent,
    while ordinary source next to them still ships."""
    template, outdir = synth
    functions = _resources(template, "AWS::Lambda::Function")
    assert len(functions) == 2
    for fn in functions:
        asset = outdir / fn["Metadata"]["aws:asset:path"]
        files = {p.relative_to(asset).as_posix() for p in asset.rglob("*") if p.is_file()}
        assert set(_SHIPPED) <= files
        assert not [f for f in files if any(part.startswith(".") for part in f.split("/"))]


def test_synthesised_orchestrator_reserved_concurrency(synth):
    template, _ = synth
    fn = next(f for f in _resources(template, "AWS::Lambda::Function")
              if f["Properties"]["FunctionName"] == "nfl-predictor-orchestrator")
    assert fn["Properties"]["ReservedConcurrentExecutions"] == 1


def test_synthesised_http_api_routes_and_cors(synth):
    template, _ = synth
    (api,) = _resources(template, "AWS::ApiGatewayV2::Api")
    assert api["Properties"]["Name"] == "nfl-predictor-api"
    cors = api["Properties"]["CorsConfiguration"]
    assert cors["AllowOrigins"] == ["*"] and cors["AllowMethods"] == ["GET"]
    keys = {r["Properties"]["RouteKey"] for r in _resources(template, "AWS::ApiGatewayV2::Route")}
    assert keys == {"GET /health", "GET /nfl/weeks/current", "GET /nfl/weeks",
                    "GET /nfl/predictions/{season}/{week}", "GET /nfl/accuracy"}


def test_synthesised_api_policy_is_read_only_on_nfl_tables(synth):
    template, _ = synth
    import json as _json

    api_fn = next(k for k, r in template["Resources"].items()
                  if r["Type"] == "AWS::Lambda::Function"
                  and r["Properties"]["FunctionName"] == "nfl-predictor-api")
    role = template["Resources"][api_fn]["Properties"]["Role"]["Fn::GetAtt"][0]
    policies = [r for r in _resources(template, "AWS::IAM::Policy")
                if {"Ref": role} in r["Properties"]["Roles"]]
    statements = [st for p in policies for st in p["Properties"]["PolicyDocument"]["Statement"]]
    actions = {a for st in statements for a in (st["Action"] if isinstance(st["Action"], list)
                                               else [st["Action"]])}
    assert not {"dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"} & actions
    rate = [st for st in statements if "nrl-rate-limits" in _json.dumps(st["Resource"])]
    assert [st["Action"] for st in rate] == ["dynamodb:UpdateItem"]


def test_every_handler_imports_from_its_synthesised_asset(repo_synth, tmp_path):
    """Each Lambda's handler module must import from its own code asset alone (plus
    third-party packages) — the repo checkout and the editable install hide a
    first-party module the asset excludes. `-S` skips site processing, so the
    editable-install .pth finder never runs; site-packages is appended by hand.
    `-B` keeps bytecode out of the asset (other tests list its files)."""
    import os
    import sys
    import sysconfig

    template, outdir = repo_synth
    purelib = sysconfig.get_paths()["purelib"]
    probe = (
        "import importlib, sys; sys.path[:0] = [sys.argv[1]]; sys.path.append(sys.argv[2]); "
        "module, attr = sys.argv[3].rsplit('.', 1); m = importlib.import_module(module); "
        "assert m.__file__.startswith(sys.argv[1]), m.__file__; "
        "assert callable(getattr(m, attr))"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    functions = _resources(template, "AWS::Lambda::Function")
    assert len(functions) == 2
    for fn in functions:
        asset = outdir / fn["Metadata"]["aws:asset:path"]
        handler = fn["Properties"]["Handler"]
        result = subprocess.run(
            [sys.executable, "-S", "-B", "-c", probe, str(asset), purelib, handler],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{handler}: {result.stderr}"


def test_only_the_shared_rate_limiter_ships_from_v1(repo_synth):
    """The NFL API reuses v1/api/rate_limit.py; nothing else of the NRL tree ships."""
    template, outdir = repo_synth
    for fn in _resources(template, "AWS::Lambda::Function"):
        asset = outdir / fn["Metadata"]["aws:asset:path"]
        v1_files = sorted(p.relative_to(asset).as_posix() for p in (asset / "v1").rglob("*")
                          if p.is_file())
        assert v1_files == ["v1/__init__.py", "v1/api/__init__.py", "v1/api/rate_limit.py"]
        assert not (asset / "v2").exists() and not (asset / "tests").exists()
