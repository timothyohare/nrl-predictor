import aws_cdk as cdk
from aws_cdk import (
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
)
from constructs import Construct

# Repo root is one level above infra/
REPO_ROOT = ".."
LAMBDA_RUNTIME = _lambda.Runtime.PYTHON_3_12

# Directories that must never end up in the Lambda zip
_ASSET_EXCLUDE = [
    "cdk.out",       # CDK output — recursive death if included
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
]


class NrlPredictorStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 ──────────────────────────────────────────────────────────────
        raw_bucket = s3.Bucket(
            self,
            "RawScrapes",
            bucket_name="nrl-predictor-raw-scrapes",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    prefix="raw-scrapes/",
                    expiration=cdk.Duration.days(90),
                )
            ],
        )

        # ── DynamoDB tables ──────────────────────────────────────────────────
        predictions_table = dynamodb.Table(
            self, "Predictions",
            table_name="predictions",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="generatedAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        teams_table = dynamodb.Table(
            self, "Teams",
            table_name="teams",
            partition_key=dynamodb.Attribute(name="teamId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="round", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        results_table = dynamodb.Table(
            self, "Results",
            table_name="results",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="scoredAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        metrics_table = dynamodb.Table(
            self, "Metrics",
            table_name="metrics",
            partition_key=dynamodb.Attribute(name="period", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="metricName", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        rate_limits_table = dynamodb.Table(
            self, "RateLimitsV2",
            table_name="nrl-rate-limits",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        claude_usage_table = dynamodb.Table(
            self, "ClaudeUsage",
            table_name="claude_usage",
            partition_key=dynamodb.Attribute(name="yearMonth", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="invokedAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        injuries_table = dynamodb.Table(
            self, "Injuries",
            table_name="injuries",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        weather_table = dynamodb.Table(
            self, "Weather",
            table_name="weather",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        retrospectives_table = dynamodb.Table(
            self, "Retrospectives",
            table_name="retrospectives",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="generatedAt", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        match_stats_table = dynamodb.Table(
            self, "MatchStats",
            table_name="match_stats",
            partition_key=dynamodb.Attribute(name="matchId", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="scraped_at", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ── Secrets Manager ──────────────────────────────────────────────────
        anthropic_secret = secretsmanager.Secret(
            self, "AnthropicApiKey",
            secret_name="nrl-predictor/anthropic-api-key",
            description="Anthropic API key for Claude inference",
        )

        tavily_secret = secretsmanager.Secret(
            self, "TavilyApiKey",
            secret_name="nrl-predictor/tavily-api-key",
            description="Tavily API key for web search",
        )

        secretsmanager.Secret(
            self, "SupercoachToken",
            secret_name="nrl-predictor/supercoach-token",
            description="SuperCoach bearer token (V1.1)",
            secret_string_value=cdk.SecretValue.unsafe_plain_text("PENDING"),
        )

        # ── Alerting SNS ─────────────────────────────────────────────────────
        alert_topic = sns.Topic(self, "AlertTopic", topic_name="nrl-predictor-alerts")
        alert_topic.add_subscription(sns_subs.EmailSubscription("timohare@gmail.com"))

        # ── Shared Lambda environment ─────────────────────────────────────────
        _common_env = {
            "TEAMS_TABLE": teams_table.table_name,
            "RESULTS_TABLE": results_table.table_name,
            "PREDICTIONS_TABLE": predictions_table.table_name,
            "METRICS_TABLE": metrics_table.table_name,
            "RATE_LIMITS_TABLE": rate_limits_table.table_name,
            "CLAUDE_USAGE_TABLE": claude_usage_table.table_name,
            "INJURIES_TABLE": injuries_table.table_name,
            "WEATHER_TABLE": weather_table.table_name,
            "RETROSPECTIVES_TABLE": retrospectives_table.table_name,
            "MATCH_STATS_TABLE": match_stats_table.table_name,
            "RAW_BUCKET": raw_bucket.bucket_name,
            "AWS_ACCOUNT": self.account,
        }

        _scraper_env = {**_common_env}

        # ── Lambda Layer: pip dependencies ───────────────────────────────────
        # Code.from_asset only zips source — it never runs pip. We use Docker
        # bundling so the layer contains Linux-compatible wheels.
        deps_layer = _lambda.LayerVersion(
            self, "DepsLayer",
            layer_version_name="nrl-predictor-deps",
            compatible_runtimes=[LAMBDA_RUNTIME],
            description="Third-party Python runtime dependencies",
            code=_lambda.Code.from_asset(
                REPO_ROOT,
                exclude=_ASSET_EXCLUDE,
                bundling=cdk.BundlingOptions(
                    image=LAMBDA_RUNTIME.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install requests beautifulsoup4 lxml anthropic langgraph tavily-python boto3"
                        " --target /asset-output/python --no-cache-dir --quiet",
                    ],
                ),
            ),
        )

        # ── Lambda: scrapers ─────────────────────────────────────────────────
        scraper_code = _lambda.Code.from_asset(REPO_ROOT, exclude=_ASSET_EXCLUDE)

        draw_fn = _lambda.Function(
            self, "DrawScraper",
            function_name="nrl-predictor-draw-scraper",
            runtime=LAMBDA_RUNTIME,
            handler="scrapers.nrl.draw.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(2),
            memory_size=512,
            environment=_scraper_env,
        )

        team_sheet_fn = _lambda.Function(
            self, "TeamSheetScraper",
            function_name="nrl-predictor-team-sheet-scraper",
            runtime=LAMBDA_RUNTIME,
            handler="scrapers.nrl.team_sheet.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(3),
            memory_size=512,
            environment=_scraper_env,
        )

        ladder_fn = _lambda.Function(
            self, "LadderScraper",
            function_name="nrl-predictor-ladder-scraper",
            runtime=LAMBDA_RUNTIME,
            handler="scrapers.nrl.ladder.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(2),
            memory_size=512,
            environment=_scraper_env,
        )

        results_fn = _lambda.Function(
            self, "ResultsScraper",
            function_name="nrl-predictor-results-scraper",
            runtime=LAMBDA_RUNTIME,
            handler="scrapers.nrl.results.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(2),
            memory_size=512,
            environment=_scraper_env,
        )

        weather_fn = _lambda.Function(
            self, "WeatherScraper",
            function_name="nrl-predictor-weather-scraper",
            runtime=LAMBDA_RUNTIME,
            handler="scrapers.weather.lambda_handler.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(2),
            memory_size=512,
            environment=_scraper_env,
        )

        articles_fn = _lambda.Function(
            self, "ArticlesScraper",
            function_name="nrl-predictor-articles-scraper",
            runtime=LAMBDA_RUNTIME,
            handler="scrapers.articles.lambda_handler.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(3),
            memory_size=512,
            environment={
                **_scraper_env,
                "ANTHROPIC_SECRET_ARN": anthropic_secret.secret_arn,
            },
        )

        # ── Lambda: agent ─────────────────────────────────────────────────────
        agent_fn = _lambda.Function(
            self, "AgentLambda",
            function_name="nrl-predictor-agent",
            runtime=LAMBDA_RUNTIME,
            handler="agent.lambda_handler.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(5),
            memory_size=1024,
            environment={
                **_common_env,
                "ANTHROPIC_SECRET_ARN": anthropic_secret.secret_arn,
                "TAVILY_SECRET_ARN": tavily_secret.secret_arn,
                "MONTHLY_BUDGET_USD": "18",
            },
        )

        # ── Lambda: orchestrator ─────────────────────────────────────────────
        # Fans out per-match work: scrapes draw + team sheets inline, then
        # invokes agent_fn async per match. EventBridge calls this on Friday/
        # Saturday/Thursday windows (per-match Lambdas can still be invoked
        # ad-hoc for backfill/debugging).
        orchestrator_fn = _lambda.Function(
            self, "OrchestratorLambda",
            function_name="nrl-predictor-orchestrator",
            runtime=LAMBDA_RUNTIME,
            handler="orchestrator.lambda_handler.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(10),
            memory_size=512,
            environment={
                **_scraper_env,
                "AGENT_FUNCTION_NAME": agent_fn.function_name,
            },
        )

        # ── Lambda: retrospective ────────────────────────────────────────────
        # Defined before scoring_fn so we can pass its ARN into scoring's env
        retrospective_fn = _lambda.Function(
            self, "RetrospectiveLambda",
            function_name="nrl-predictor-retrospective",
            runtime=LAMBDA_RUNTIME,
            handler="retrospective.lambda_handler.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(3),
            memory_size=512,
            environment={
                **_common_env,
                "ANTHROPIC_SECRET_ARN": anthropic_secret.secret_arn,
                "TAVILY_SECRET_ARN": tavily_secret.secret_arn,
            },
        )

        # ── Lambda: scoring ───────────────────────────────────────────────────
        scoring_fn = _lambda.Function(
            self, "ScoringLambda",
            function_name="nrl-predictor-scoring",
            runtime=LAMBDA_RUNTIME,
            handler="scoring.lambda_handler.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.minutes(2),
            memory_size=512,
            environment={
                **_common_env,
                "RETROSPECTIVE_FUNCTION_ARN": retrospective_fn.function_arn,
            },
        )

        # ── Lambda: API ───────────────────────────────────────────────────────
        api_fn = _lambda.Function(
            self, "ApiLambda",
            function_name="nrl-predictor-api",
            runtime=LAMBDA_RUNTIME,
            handler="api.router.lambda_handler",
            code=scraper_code,
            layers=[deps_layer],
            timeout=cdk.Duration.seconds(10),
            memory_size=256,
            environment={
                **_common_env,
                "RATE_LIMITS_TABLE": rate_limits_table.table_name,
            },
        )

        # ── IAM grants ───────────────────────────────────────────────────────
        for fn in (draw_fn, team_sheet_fn, ladder_fn, results_fn, weather_fn, articles_fn):
            teams_table.grant_read_write_data(fn)
            results_table.grant_read_write_data(fn)
            raw_bucket.grant_read_write(fn)

        # Orchestrator: reads/writes teams + s3 (same as the scraper lambdas
        # whose work it inlines) and invokes the agent
        teams_table.grant_read_write_data(orchestrator_fn)
        raw_bucket.grant_read_write(orchestrator_fn)
        agent_fn.grant_invoke(orchestrator_fn)

        for fn in (agent_fn,):
            for tbl in (predictions_table, teams_table, results_table, metrics_table,
                        claude_usage_table, injuries_table, weather_table):
                tbl.grant_read_write_data(fn)
            retrospectives_table.grant_read_data(fn)
            raw_bucket.grant_read(fn)
            anthropic_secret.grant_read(fn)
            tavily_secret.grant_read(fn)

        for tbl in (predictions_table, results_table, metrics_table):
            tbl.grant_read_write_data(scoring_fn)
        # scoring invokes retrospective asynchronously
        retrospective_fn.grant_invoke(scoring_fn)

        # retrospective reads predictions + results, writes retrospectives + match_stats
        for tbl in (predictions_table, results_table):
            tbl.grant_read_data(retrospective_fn)
        for tbl in (retrospectives_table, match_stats_table):
            tbl.grant_read_write_data(retrospective_fn)
        anthropic_secret.grant_read(retrospective_fn)
        tavily_secret.grant_read(retrospective_fn)

        for tbl in (predictions_table, metrics_table, rate_limits_table, retrospectives_table):
            tbl.grant_read_write_data(api_fn)
        # API joins results onto predictions to show actual scores
        results_table.grant_read_data(api_fn)

        anthropic_secret.grant_read(articles_fn)

        # ── API Gateway HTTP API ──────────────────────────────────────────────
        api = apigwv2.HttpApi(
            self, "HttpApi",
            api_name="nrl-predictor-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_methods=[apigwv2.CorsHttpMethod.GET],
                allow_origins=["*"],
            ),
        )

        api_integration = integrations.HttpLambdaIntegration("ApiIntegration", api_fn)

        api.add_routes(path="/predictions/{round}", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/accuracy", methods=[apigwv2.HttpMethod.GET], integration=api_integration)
        api.add_routes(path="/health", methods=[apigwv2.HttpMethod.GET], integration=api_integration)

        # ── EventBridge schedules (UTC cron) ──────────────────────────────────
        # Wednesday 08:00 UTC (18:00 AEST) — draw scraper
        events.Rule(
            self, "WedDrawRule",
            rule_name="nrl-scraper-wednesday",
            schedule=events.Schedule.cron(minute="0", hour="8", week_day="WED"),
            targets=[targets.LambdaFunction(draw_fn, event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}))],
        )

        # Thursday 07:00 UTC (17:00 AEST) — ladder refresh + orchestrator
        # so predictions are ready before any Thursday-night 6pm AEST game.
        thu_rule = events.Rule(
            self, "ThuRule",
            rule_name="nrl-scraper-thursday",
            schedule=events.Schedule.cron(minute="0", hour="7", week_day="THU"),
        )
        thu_rule.add_target(targets.LambdaFunction(ladder_fn, event=events.RuleTargetInput.from_object({"season": 2026})))
        thu_rule.add_target(targets.LambdaFunction(articles_fn))
        thu_rule.add_target(targets.LambdaFunction(weather_fn))
        thu_rule.add_target(targets.LambdaFunction(
            orchestrator_fn,
            event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
        ))

        # Friday 07:00 UTC (17:00 AEST) — orchestrator refresh so predictions
        # are ready before any Friday 6pm AEST game.
        fri_pm_rule = events.Rule(
            self, "FriPmRule",
            rule_name="nrl-scraper-friday-pm",
            schedule=events.Schedule.cron(minute="0", hour="7", week_day="FRI"),
        )
        fri_pm_rule.add_target(targets.LambdaFunction(articles_fn))
        fri_pm_rule.add_target(targets.LambdaFunction(weather_fn))
        fri_pm_rule.add_target(targets.LambdaFunction(
            orchestrator_fn,
            event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
        ))

        # Friday 12:00 UTC (22:00 AEST) — orchestrator fans out per-match work
        # (draw + team sheets + agent) then weather + articles for refresh.
        fri_night_rule = events.Rule(
            self, "FriNightRule",
            rule_name="nrl-scraper-friday-night",
            schedule=events.Schedule.cron(minute="0", hour="12", week_day="FRI"),
        )
        fri_night_rule.add_target(targets.LambdaFunction(
            orchestrator_fn,
            event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
        ))
        fri_night_rule.add_target(targets.LambdaFunction(weather_fn))
        fri_night_rule.add_target(targets.LambdaFunction(articles_fn))

        # Saturday 23:00 UTC Friday (09:00 AEST Sat) — orchestrator re-run
        sat_am_rule = events.Rule(
            self, "SatAmRule",
            rule_name="nrl-scraper-saturday-am",
            schedule=events.Schedule.cron(minute="0", hour="23", week_day="FRI"),
        )
        sat_am_rule.add_target(targets.LambdaFunction(
            orchestrator_fn,
            event=events.RuleTargetInput.from_object({"season": 2026, "round": "current"}),
        ))
        sat_am_rule.add_target(targets.LambdaFunction(weather_fn))
        sat_am_rule.add_target(targets.LambdaFunction(articles_fn))

        # ── CloudWatch Alarms ─────────────────────────────────────────────────
        for fn, name in [
            (draw_fn, "DrawScraper"), (team_sheet_fn, "TeamSheet"), (ladder_fn, "Ladder"),
            (results_fn, "Results"), (weather_fn, "Weather"), (articles_fn, "Articles"),
        ]:
            alarm = cloudwatch.Alarm(
                self, f"{name}ErrorAlarm",
                alarm_name=f"nrl-predictor-{name.lower()}-errors",
                metric=fn.metric_errors(period=cdk.Duration.minutes(30)),
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            alarm.add_alarm_action(cw_actions.SnsAction(alert_topic))

        agent_timeout_alarm = cloudwatch.Alarm(
            self, "AgentTimeoutAlarm",
            alarm_name="nrl-predictor-agent-duration",
            metric=agent_fn.metric_duration(period=cdk.Duration.minutes(5)),
            threshold=4 * 60 * 1000,  # 4 minutes in ms
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        agent_timeout_alarm.add_alarm_action(cw_actions.SnsAction(alert_topic))

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "ApiEndpoint", value=api.api_endpoint)
        cdk.CfnOutput(self, "RawBucketName", value=raw_bucket.bucket_name)
        cdk.CfnOutput(self, "AgentFunctionArn", value=agent_fn.function_arn)
