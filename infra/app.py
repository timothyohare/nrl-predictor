#!/usr/bin/env python3
"""Single CDK app for the monorepo — synthesizes BOTH stacks.

v1 (NrlPredictorStack) and v2 (NrlPredictorV2Stack) coexist and deploy
independently:  cdk deploy NrlPredictorStack  /  cdk deploy NrlPredictorV2Stack.
"""
import aws_cdk as cdk
from v1_stack import NrlPredictorStack
from v2_stack import NrlPredictorV2Stack

app = cdk.App()
_env = cdk.Environment(account="810429055117", region="ap-southeast-2")

NrlPredictorStack(app, "NrlPredictorStack", env=_env)
NrlPredictorV2Stack(app, "NrlPredictorV2Stack", env=_env)

app.synth()
