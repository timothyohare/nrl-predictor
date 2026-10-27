"""Response and path-parameter helpers shared by the NFL API handlers."""
from __future__ import annotations

import json
import re
from decimal import Decimal

SEASONS = (1999, 2100)  # nflverse starts in 1999
WEEKS = (1, 25)  # regular season + playoffs top out at week 22
_DIGITS = re.compile(r"[0-9]{1,4}")


def _serialise(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def respond(status: int, payload, *, cache: str = "no-store", headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": cache, **(headers or {})},
        "body": json.dumps(payload, default=_serialise),
    }


def error(status: int, message: str, *, headers: dict | None = None) -> dict:
    return respond(status, {"error": message}, headers=headers)


def parse_int(value, bounds: tuple[int, int]) -> int | None:
    """`value` as an int within `bounds` (inclusive), or None. ASCII digits only."""
    if not isinstance(value, str) or not _DIGITS.fullmatch(value):
        return None
    number = int(value)
    return number if bounds[0] <= number <= bounds[1] else None
