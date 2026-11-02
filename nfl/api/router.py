"""NFL API Lambda entry point (spec Phase 4) — routes by path.

Rate limiting reuses the NRL limiter (v1/api/rate_limit.py) against the shared
`nrl-rate-limits` table under an `nfl#<ip>` bucket, so NFL and NRL traffic are
counted separately. Like NRL it fails open: an unreachable table never blocks a
request (CLAUDE.md constraint).
"""
from __future__ import annotations

import logging
import os
import re

import boto3

from nfl.api import accuracy, predictions, weeks
from nfl.api.http import error, respond
from v1.api.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)

_PREDICTIONS = re.compile(r"^/nfl/predictions/([^/]+)/([^/]+)$")


def _rate_limit_denial(ip: str) -> str | None:
    """The denial reason, or None to let the request through (incl. on any error)."""
    table_name = os.environ.get("RATE_LIMITS_TABLE")
    if not table_name:
        return None
    try:
        table = boto3.resource("dynamodb").Table(table_name)
        allowed, reason = check_rate_limit(f"nfl#{ip}", table=table)
    except Exception:
        logger.exception("NFL rate limit check failed — failing open")
        return None
    return None if allowed else reason


def lambda_handler(event: dict, context) -> dict:
    try:
        return _route(event, context)
    except Exception:
        # Never API Gateway's bare 500, and never internals in the body (review N1).
        logger.exception("Unhandled error in the NFL API")
        return error(500, "Internal error")


def _route(event: dict, context) -> dict:
    path = (event.get("rawPath") or event.get("path") or "").rstrip("/")
    ip = (event.get("requestContext") or {}).get("http", {}).get("sourceIp", "unknown")

    denial = _rate_limit_denial(ip)
    if denial:
        return error(429, denial, headers={"Retry-After": "3600"})

    if path == "/health":
        return respond(200, {"status": "ok"})
    if path == "/nfl/weeks/current":
        return weeks.lambda_handler(event, context)
    if path == "/nfl/weeks":
        return weeks.list_handler(event, context)
    if path == "/nfl/accuracy":
        return accuracy.lambda_handler(event, context)
    match = _PREDICTIONS.match(path)
    if match:
        params = event.get("pathParameters") or {"season": match.group(1), "week": match.group(2)}
        return predictions.lambda_handler({**event, "pathParameters": params}, context)
    return error(404, "Not found")
