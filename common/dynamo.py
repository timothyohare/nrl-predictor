"""Shared DynamoDB helpers."""
from typing import Any


def scan_all(table: Any, **kwargs: Any) -> list[dict]:
    """Run table.scan(**kwargs), following LastEvaluatedKey until exhausted.

    A single Scan response is capped at ~1MB pre-filter, so a bare
    table.scan() silently drops matching items once a table grows past that.
    Always use this instead of calling table.scan() directly.
    """
    items: list[dict] = []
    scan_kwargs = dict(kwargs)
    while True:
        resp = table.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            return items
        scan_kwargs["ExclusiveStartKey"] = last_key
