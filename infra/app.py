#!/usr/bin/env python3
"""Single CDK app for the monorepo — synthesizes every stack.

v1 (NrlPredictorStack), v2 (NrlPredictorV2Stack) and the NFL pipeline
(NflPredictorStack) coexist and deploy independently:
  cdk deploy NrlPredictorStack  /  cdk deploy NrlPredictorV2Stack  /  cdk deploy NflPredictorStack
"""
import aws_cdk as cdk
from nfl_stack import NflPredictorStack
from v1_stack import NrlPredictorStack
from v2_stack import NrlPredictorV2Stack

app = cdk.App()
_env = cdk.Environment(account="810429055117", region="ap-southeast-2")

NrlPredictorStack(app, "NrlPredictorStack", env=_env)
NrlPredictorV2Stack(app, "NrlPredictorV2Stack", env=_env)
NflPredictorStack(app, "NflPredictorStack", env=_env)

app.synth()
