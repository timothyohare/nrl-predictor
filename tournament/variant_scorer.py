"""Scores prompt variant predictions against actual results."""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

_CONFIDENCE_PROB = {"HIGH": 0.85, "MEDIUM": 0.65, "LOW": 0.55}


def _write_metric(table, variant_id: str, period: str, correct: int, total: int,
                  avg_margin_error: float, brier_score: float, rounds_active: int = 1) -> None:
    table.put_item(Item={
        "variantId": variant_id,
        "period": period,
        "correct_picks": correct,
        "total_picks": total,
        "pick_rate": Decimal(str(round(correct / total, 6))) if total > 0 else Decimal("0"),
        "avg_margin_error": Decimal(str(round(avg_margin_error, 3))),
        "brier_score": Decimal(str(round(brier_score, 6))),
        "rounds_active": rounds_active,
    })


def score_round(
    round_number: int,
    season: int,
    sim_preds_table,
    results_table,
    variant_metrics_table,
) -> dict[str, dict]:
    """Score all variants for a round. Returns {variant_id: metrics_dict}."""
    # Scan simulation predictions for this round
    sim_resp = sim_preds_table.scan(
        FilterExpression="roundNumber = :r AND season = :s",
        ExpressionAttributeValues={":r": round_number, ":s": season},
    )
    sim_items = sim_resp.get("Items", [])

    # Scan results for this round (only scored items)
    results_resp = results_table.scan(
        FilterExpression="roundNumber = :r",
        ExpressionAttributeValues={":r": round_number},
    )
    result_by_match = {}
    for item in results_resp.get("Items", []):
        mid = item["matchId"]
        if mid not in result_by_match or item.get("scoredAt", "") > result_by_match[mid].get("scoredAt", ""):
            result_by_match[mid] = item

    # Group simulation predictions by variantId
    by_variant: dict[str, list[dict]] = {}
    for item in sim_items:
        vid = item["variantId"]
        by_variant.setdefault(vid, []).append(item)

    period = f"{season}-round-{round_number}"
    written = {}

    for variant_id, preds in by_variant.items():
        scored = []
        for pred in preds:
            result = result_by_match.get(pred["matchId"])
            if result is None:
                continue
            correct = pred["predicted_winner"] == result["winner"]
            margin_error = abs(int(pred.get("predicted_margin", 0)) - int(result["margin"]))
            conf = pred.get("confidence", "MEDIUM")
            p = _CONFIDENCE_PROB.get(conf, 0.65)
            brier = (p - (1 if correct else 0)) ** 2
            scored.append((correct, margin_error, brier))

        if not scored:
            continue

        total = len(scored)
        correct_count = sum(1 for c, _, _ in scored if c)
        avg_margin = sum(e for _, e, _ in scored) / total
        avg_brier = sum(b for _, _, b in scored) / total

        _write_metric(
            variant_metrics_table, variant_id, period,
            correct=correct_count, total=total,
            avg_margin_error=avg_margin, brier_score=avg_brier,
        )
        written[variant_id] = {"correct_picks": correct_count, "total_picks": total}
        logger.info("Variant %s round %d: %d/%d correct", variant_id, round_number, correct_count, total)

    return written


def aggregate_variant_season(
    season: int,
    sim_preds_table,
    results_table,
    variant_metrics_table,
) -> None:
    """Aggregate season-to-date metrics across all variants."""
    sim_resp = sim_preds_table.scan(
        FilterExpression="season = :s",
        ExpressionAttributeValues={":s": season},
    )
    sim_items = sim_resp.get("Items", [])

    results_resp = results_table.scan(
        FilterExpression="season = :s",
        ExpressionAttributeValues={":s": season},
    )
    result_by_match = {}
    for item in results_resp.get("Items", []):
        mid = item["matchId"]
        if mid not in result_by_match or item.get("scoredAt", "") > result_by_match[mid].get("scoredAt", ""):
            result_by_match[mid] = item

    # Also compute rounds_active per variant
    rounds_by_variant: dict[str, set] = {}
    by_variant: dict[str, list[dict]] = {}
    for item in sim_items:
        vid = item["variantId"]
        by_variant.setdefault(vid, []).append(item)
        rounds_by_variant.setdefault(vid, set()).add(item.get("roundNumber"))

    period = f"{season}-season"
    for variant_id, preds in by_variant.items():
        scored = []
        for pred in preds:
            result = result_by_match.get(pred["matchId"])
            if result is None:
                continue
            correct = pred["predicted_winner"] == result["winner"]
            margin_error = abs(int(pred.get("predicted_margin", 0)) - int(result["margin"]))
            conf = pred.get("confidence", "MEDIUM")
            p = _CONFIDENCE_PROB.get(conf, 0.65)
            brier = (p - (1 if correct else 0)) ** 2
            scored.append((correct, margin_error, brier))

        if not scored:
            continue

        total = len(scored)
        correct_count = sum(1 for c, _, _ in scored if c)
        avg_margin = sum(e for _, e, _ in scored) / total
        avg_brier = sum(b for _, _, b in scored) / total
        rounds_active = len(rounds_by_variant.get(variant_id, set()))

        _write_metric(
            variant_metrics_table, variant_id, period,
            correct=correct_count, total=total,
            avg_margin_error=avg_margin, brier_score=avg_brier,
            rounds_active=rounds_active,
        )


def get_leaderboard(season: int, variant_metrics_table) -> list[dict]:
    """Return variants ranked by season pick rate."""
    resp = variant_metrics_table.scan(
        FilterExpression="#p = :p",
        ExpressionAttributeNames={"#p": "period"},
        ExpressionAttributeValues={":p": f"{season}-season"},
    )
    items = resp.get("Items", [])
    ranked = sorted(items, key=lambda x: float(x.get("pick_rate", 0)), reverse=True)
    return [
        {
            "variantId": item["variantId"],
            "pick_rate": float(item.get("pick_rate", 0)),
            "correct_picks": int(item.get("correct_picks", 0)),
            "total_picks": int(item.get("total_picks", 0)),
            "avg_margin_error": float(item.get("avg_margin_error", 0)),
            "brier_score": float(item.get("brier_score", 0)),
            "rounds_active": int(item.get("rounds_active", 0)),
        }
        for item in ranked
    ]
