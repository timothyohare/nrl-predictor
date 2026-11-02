"""NflPredictorStack — the NFL live pipeline (spec Phase 3) and its read API
(Phase 4), deployed, paused and destroyed independently of the NRL stacks
(v1_stack.py / v2_stack.py are never touched by it).

One daily Lambda ingests the nflverse schedule/results CSV, upserts the current
season into `nfl_games` and predicts the next week into `nfl_predictions`
(Elo + Monte Carlo, `nfl-elo-v1`; no LLM, no market input). A separate HttpApi
(user decision Q3; the frontend reads it via NFL_API_BASE_URL) serves
/nfl/weeks/current, /nfl/predictions/{season}/{week} and /nfl/accuracy.
Cost-conscious: two PAY_PER_REQUEST tables, one 512 MB / 60 s Lambda run once a
day, one small API Lambda, two alarms on the existing NRL alerts topic
(imported, not recreated).
"""
import aws_cdk as cdk
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as integrations,
)
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
)
from aws_cdk import (
    aws_cloudwatch_actions as cw_actions,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_lambda as _lambda,
)
from aws_cdk import (
    aws_sns as sns,
)
from constructs import Construct

# Repo root is one level above infra/
REPO_ROOT = ".."
LAMBDA_RUNTIME = _lambda.Runtime.PYTHON_3_12

# Data licence: nflverse/nfldata declares no licence (GitHub API "license": null,
# checked 2026-10-26). Decided 2026-11-02 (owner): use it on the public site with
# attribution — every NFL page carries the nflverse credit line. Setting this to
# False disables the daily rule (stack stays deployed) for the off-season.
NFL_SEASON_ACTIVE = True

NFLVERSE_GAMES_CSV_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"

# The NRL v1 stack owns this topic (email subscription included); import, never recreate.
ALERT_TOPIC_ARN = "arn:aws:sns:ap-southeast-2:810429055117:nrl-predictor-alerts"

# The NRL v1 stack owns the API rate-limit table too; the NFL API shares it under
# an `nfl#<ip>` bucket (nfl/api/router.py). Import by ARN, grant UpdateItem only.
RATE_LIMITS_TABLE_ARN = "arn:aws:dynamodb:ap-southeast-2:810429055117:table/nrl-rate-limits"

# Only what the NFL Lambdas import (common/ + nfl/, and the shared NRL rate
# limiter v1/api/rate_limit.py for the API) needs to ship. ".*" keeps every
# dotfile out of the zip — notably .env (local API keys) and the tool caches
# (.mypy_cache alone is ~38 MB). Order matters for the v1 lines: later "!"
# patterns re-include what an earlier pattern excluded.
_ASSET_EXCLUDE = [
    ".*",
    "*.egg-info",
    "cdk.out",
    ".venv",
    "frontend",
    "infra",
    "fetcher-spikes",
    "docs",
    ".git",
    ".github",
    "node_modules",
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "tests",
    "TODO.md",
    "CLAUDE.md",
    "v1/*",
    "!v1/__init__.py",
    "!v1/api",
    "v1/api/*",
    "!v1/api/__init__.py",
    "!v1/api/rate_limit.py",
    "v2",
    "tasks",
    "SPEC.md",
    "mutants",
    "reports",
    "scripts",
    "manual_context",
    "plans",
    "security",
]


class NflPredictorStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── DynamoDB tables ──────────────────────────────────────────────────
        games_table = dynamodb.Table(
            self, "NflGames",
            table_name="nfl_games",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        predictions_table = dynamodb.Table(
            self, "NflPredictions",
            table_name="nfl_predictions",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="generatedAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ── Lambda Layer: tzdata ─────────────────────────────────────────────
        # nflverse kickoffs are US Eastern (zoneinfo); the Lambda runtime image
        # isn't guaranteed to carry the IANA database, so ship it. boto3 comes
        # with the runtime; the CSV fetch uses urllib (stdlib).
        deps_layer = _lambda.LayerVersion(
            self, "NflDepsLayer",
            layer_version_name="nfl-predictor-deps",
            compatible_runtimes=[LAMBDA_RUNTIME],
            description="tzdata for the NFL orchestrator",
            code=_lambda.Code.from_asset(
                REPO_ROOT,
                exclude=_ASSET_EXCLUDE,
                bundling=cdk.BundlingOptions(
                    image=LAMBDA_RUNTIME.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install 'tzdata>=2024.1'"
                        " --target /asset-output/python --no-cache-dir --quiet",
                    ],
                ),
            ),
        )

        code = _lambda.Code.from_asset(REPO_ROOT, exclude=_ASSET_EXCLUDE)

        # ── Lambda: orchestrator ─────────────────────────────────────────────
        orchestrator_fn = _lambda.Function(
            self, "NflOrchestrator",
            function_name="nfl-predictor-orchestrator",
            runtime=LAMBDA_RUNTIME,
            handler="nfl.orchestrator.lambda_handler.lambda_handler",
            code=code,
            layers=[deps_layer],
            timeout=cdk.Duration.seconds(60),
            memory_size=512,
            # Idempotency is check-then-put (the sort key is generatedAt, so a
            # conditional put can't dedupe): never let a manual invoke overlap
            # the scheduled run.
            reserved_concurrent_executions=1,
            environment={
                "NFL_GAMES_TABLE": games_table.table_name,
                "NFL_PREDICTIONS_TABLE": predictions_table.table_name,
                "NFL_GAMES_CSV_URL": NFLVERSE_GAMES_CSV_URL,
            },
        )
        games_table.grant_read_write_data(orchestrator_fn)
        predictions_table.grant_read_write_data(orchestrator_fn)
        orchestrator_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": "NflPredictor"}},
        ))

        # ── Lambda + HttpApi: the NFL read API (Phase 4) ─────────────────────
        api_fn = _lambda.Function(
            self, "NflApiLambda",
            function_name="nfl-predictor-api",
            runtime=LAMBDA_RUNTIME,
            handler="nfl.api.router.lambda_handler",
            code=code,
            layers=[deps_layer],
            timeout=cdk.Duration.seconds(10),
            memory_size=256,
            environment={
                "NFL_GAMES_TABLE": games_table.table_name,
                "NFL_PREDICTIONS_TABLE": predictions_table.table_name,
                "RATE_LIMITS_TABLE": "nrl-rate-limits",
            },
        )
        games_table.grant_read_data(api_fn)
        predictions_table.grant_read_data(api_fn)
        rate_limits_table = dynamodb.Table.from_table_arn(self, "RateLimits", RATE_LIMITS_TABLE_ARN)
        rate_limits_table.grant(api_fn, "dynamodb:UpdateItem")

        # Same CORS as the NRL API (v1_stack.py): GET from any origin.
        api = apigwv2.HttpApi(
            self, "NflHttpApi",
            api_name="nfl-predictor-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_methods=[apigwv2.CorsHttpMethod.GET],
                allow_origins=["*"],
            ),
        )
        api_integration = integrations.HttpLambdaIntegration("NflApiIntegration", api_fn)
        api.add_routes(path="/health", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/nfl/weeks/current", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/nfl/weeks", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/nfl/predictions/{season}/{week}", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/nfl/accuracy", methods=[apigwv2.HttpMethod.GET], integration=api_integration)

        # ── Schedule ─────────────────────────────────────────────────────────
        # Daily 12:00 UTC (22:00/23:00 Sydney; 07:00/08:00 US Eastern) — after
        # Monday night results land, before Thursday night kickoff. Empty payload:
        # season and week always come from the data.
        events.Rule(
            self, "NflOrchestratorDailyRule",
            rule_name="nfl-orchestrator-daily",
            schedule=events.Schedule.cron(minute="0", hour="12"),
            enabled=NFL_SEASON_ACTIVE,
            targets=[targets.LambdaFunction(
                orchestrator_fn,
                event=events.RuleTargetInput.from_object({}),
            )],
        )

        # ── CloudWatch Alarms ─────────────────────────────────────────────────
        alert_topic = sns.Topic.from_topic_arn(self, "AlertTopic", ALERT_TOPIC_ARN)

        # The Lambda runs once a day, so even its built-in Errors metric is a
        # sparse pulse here: 24h period + IGNORE holds ALARM until a later run
        # succeeds (Lambda then reports Errors = 0), instead of flapping back to OK.
        errors_alarm = cloudwatch.Alarm(
            self, "NflOrchestratorErrorAlarm",
            alarm_name="nfl-predictor-orchestrator-errors",
            metric=orchestrator_fn.metric_errors(period=cdk.Duration.hours(24)),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.IGNORE,
        )
        errors_alarm.add_alarm_action(cw_actions.SnsAction(alert_topic))

        # UnpredictedGames is a once-a-day pulse from the orchestrator. Same fix
        # as NRL's PredictionCoverageAlarm (2026-08-30, see v1_stack.py and
        # CLAUDE.md): a short period misses the daily datapoint and a
        # treat-missing-as-not-breaching default forces OK on the next empty period, so the alarm
        # never fires. 24h period so the pulse always lands in the evaluated
        # window; IGNORE so missing data holds the last state until a later run
        # emits 0.
        unpredicted_alarm = cloudwatch.Alarm(
            self, "NflUnpredictedGamesAlarm",
            alarm_name="nfl-predictor-unpredicted-games",
            metric=cloudwatch.Metric(
                namespace="NflPredictor",
                metric_name="UnpredictedGames",
                statistic="Maximum",
                period=cdk.Duration.hours(24),
            ),
            threshold=1,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.IGNORE,
        )
        unpredicted_alarm.add_alarm_action(cw_actions.SnsAction(alert_topic))

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "NflOrchestratorFunctionName", value=orchestrator_fn.function_name)
        cdk.CfnOutput(self, "NflApiEndpoint", value=api.api_endpoint)
