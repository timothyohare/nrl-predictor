from dataclasses import dataclass
from decimal import Decimal

import boto3


@dataclass
class RoundMetrics:
    round_number: int
    season: int
    correct_picks: int
    total: int
    pick_rate: float
    mean_margin_error: float
    brier_score: float


def aggregate_round(round_number: int, season: int, results_table, metrics_table) -> RoundMetrics:
    response = results_table.scan(
        FilterExpression="roundNumber = :r AND season = :s",
        ExpressionAttributeValues={":r": round_number, ":s": season},
    )
    items = response.get("Items", [])
    total = len(items)
    if total == 0:
        return RoundMetrics(round_number, season, 0, 0, 0.0, 0.0, 0.0)

    correct = sum(1 for i in items if i.get("correct_pick"))
    margin_errors = [int(i.get("predicted_margin_error", 0)) for i in items]
    brier_components = [float(i.get("brier_component", 0)) for i in items]

    pick_rate = correct / total
    mean_margin = sum(margin_errors) / total
    brier = sum(brier_components) / total

    period = f"{season}-round-{round_number}"
    for metric_name, value in [
        ("pick_rate", pick_rate),
        ("mean_margin_error", mean_margin),
        ("brier_score", brier),
    ]:
        metrics_table.put_item(Item={
            "period": period,
            "metricName": metric_name,
            "value": Decimal(str(round(value, 6))),
            "correct_picks": correct,
            "total": total,
        })

    return RoundMetrics(
        round_number=round_number,
        season=season,
        correct_picks=correct,
        total=total,
        pick_rate=pick_rate,
        mean_margin_error=mean_margin,
        brier_score=brier,
    )


def aggregate_season(season: int, results_table, metrics_table) -> None:
    response = results_table.scan(
        FilterExpression="season = :s",
        ExpressionAttributeValues={":s": season},
    )
    items = response.get("Items", [])
    total = len(items)
    if total == 0:
        return

    correct = sum(1 for i in items if i.get("correct_pick"))
    margin_errors = [int(i.get("predicted_margin_error", 0)) for i in items]
    brier_components = [float(i.get("brier_component", 0)) for i in items]

    pick_rate = correct / total
    mean_margin = sum(margin_errors) / total
    brier = sum(brier_components) / total

    period = f"{season}-season"
    for metric_name, value in [
        ("pick_rate", pick_rate),
        ("mean_margin_error", mean_margin),
        ("brier_score", brier),
    ]:
        metrics_table.put_item(Item={
            "period": period,
            "metricName": metric_name,
            "value": Decimal(str(round(value, 6))),
            "correct_picks": correct,
            "total": total,
        })
