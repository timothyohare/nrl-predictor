"""NflPredictorStack — the NFL live pipeline (spec Phase 3), deployed, paused and
destroyed independently of the NRL stacks (v1_stack.py / v2_stack.py are never
touched by it).

One daily Lambda ingests the nflverse schedule/results CSV, upserts the current
season into `nfl_games` and predicts the next week into `nfl_predictions`
(Elo + Monte Carlo, `nfl-elo-v1`; no LLM, no market input). Cost-conscious:
two PAY_PER_REQUEST tables, one 512 MB / 60 s Lambda run once a day, two alarms
on the existing NRL alerts topic (imported, not recreated).
"""
import aws_cdk as cdk
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

# OPEN QUESTION (blocks deploy, not build): the nflverse data licence.
# nflverse/nfldata declares no licence (GitHub API "license": null, checked
# 2026-10-26), so whether a public site may be built on it with attribution only
# is unresolved — see .claude/sdlc/nfl-predictor/spec.md, open question 1. Until
# the user answers it, this ships False: a deploy creates the stack but the daily
# rule stays DISABLED, so no scheduled ingest runs. Flip to True only once the
# licence question is resolved and the user confirms go-live.
NFL_SEASON_ACTIVE = False

NFLVERSE_GAMES_CSV_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"

# The NRL v1 stack owns this topic (email subscription included); import, never recreate.
ALERT_TOPIC_ARN = "arn:aws:sns:ap-southeast-2:810429055117:nrl-predictor-alerts"

# Only what the NFL Lambda imports (common/ + nfl/) needs to ship. ".*" keeps
# every dotfile out of the zip — notably .env (local API keys) and the tool
# caches (.mypy_cache alone is ~38 MB).
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
    "v1",
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

        # ── Lambda: orchestrator ─────────────────────────────────────────────
        orchestrator_fn = _lambda.Function(
            self, "NflOrchestrator",
            function_name="nfl-predictor-orchestrator",
            runtime=LAMBDA_RUNTIME,
            handler="nfl.orchestrator.lambda_handler.lambda_handler",
            code=_lambda.Code.from_asset(REPO_ROOT, exclude=_ASSET_EXCLUDE),
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
