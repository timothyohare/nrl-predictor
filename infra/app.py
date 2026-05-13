#!/usr/bin/env python3
import aws_cdk as cdk
from stack import NrlPredictorStack

app = cdk.App()
NrlPredictorStack(
    app,
    "NrlPredictorStack",
    env=cdk.Environment(account="810429055117", region="ap-southeast-2"),
)
app.synth()
