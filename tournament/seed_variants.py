"""Seed initial prompt variants into the prompt_variants DynamoDB table.

Usage:
    AWS_DEFAULT_REGION=ap-southeast-2 python3 -m tournament.seed_variants [--dry-run]
"""
import argparse
import os
from datetime import UTC, datetime

import boto3

from agent.prompt import build_system_prompt

_BASE_PROMPT = build_system_prompt()

_VARIANTS = [
    {
        "variantId": "baseline",
        "hypothesis": "Control — identical to production prompt (no lessons injected)",
        "dimensions": ["control"],
        "prompt_template": _BASE_PROMPT,
    },
    {
        "variantId": "heavy-home-advantage",
        "hypothesis": "Home advantage is worth 6pts not the default ~4pts",
        "dimensions": ["home_advantage"],
        "prompt_template": _BASE_PROMPT.replace(
            "4. HOME/AWAY ADVANTAGE — Quantify home ground advantage for this venue. Note travel distance for the away side.",
            "4. HOME/AWAY ADVANTAGE — Home advantage is worth approximately 6 points in the NRL. "
            "Quantify the home ground advantage for this venue and factor in travel distance. "
            "Unless the form or team sheet gives a clear reason to discount it, adjust your margin prediction to reflect home advantage.",
        ),
    },
    {
        "variantId": "light-home-advantage",
        "hypothesis": "Home advantage is only worth 2pts — modern travel has reduced it",
        "dimensions": ["home_advantage"],
        "prompt_template": _BASE_PROMPT.replace(
            "4. HOME/AWAY ADVANTAGE — Quantify home ground advantage for this venue. Note travel distance for the away side.",
            "4. HOME/AWAY ADVANTAGE — Modern travel has reduced home advantage. It is worth approximately 2 points in the NRL. "
            "Do not over-index on venue unless it is a known fortress (Suncorp, BlueBet) or the away team has interstate travel.",
        ),
    },
    {
        "variantId": "form-over-h2h",
        "hypothesis": "Recent form is more predictive than H2H — squads change season to season",
        "dimensions": ["form_vs_h2h"],
        "prompt_template": _BASE_PROMPT.replace(
            "2. RECENT FORM — Assess each team's momentum using the weighted form data. Pay attention to momentum direction (rising/falling/stable) and the weighted win rate rather than raw win count. A team on a 3-game winning streak after earlier losses is more dangerous than their season record suggests.\n3. HEAD-TO-HEAD — Check the recent H2H record at this venue and overall. Also retrieve the coaching matchup to see how the current coaches have fared against each other during their tenures. Note any psychological edge.",
            "2. RECENT FORM — This is your primary input. Assess momentum direction, weighted win rate, and scoring trends. "
            "A team's current form is more predictive than historical H2H because squad composition changes every season.\n"
            "3. HEAD-TO-HEAD — Check H2H for psychological factors and venue-specific patterns only. "
            "Do not let a historical H2H advantage override a clear current-form mismatch.",
        ),
    },
    {
        "variantId": "h2h-over-form",
        "hypothesis": "H2H records reveal structural mismatches that outlast personnel changes",
        "dimensions": ["form_vs_h2h"],
        "prompt_template": _BASE_PROMPT.replace(
            "3. HEAD-TO-HEAD — Check the recent H2H record at this venue and overall. Also retrieve the coaching matchup to see how the current coaches have fared against each other during their tenures. Note any psychological edge.",
            "3. HEAD-TO-HEAD — H2H records reveal structural style mismatches that outlast personnel changes. "
            "A team that consistently exploits another's defensive shape will continue to do so. "
            "Weight the last 5 H2H results heavily. Coaching matchup is a secondary signal.",
        ),
    },
    {
        "variantId": "high-confidence-strict",
        "hypothesis": "Strict HIGH confidence threshold — only when 3+ factors clearly align",
        "dimensions": ["confidence_calibration"],
        "prompt_template": _BASE_PROMPT + (
            "\n\nCONFIDENCE CALIBRATION: Only assign HIGH confidence when at least 3 of the following align "
            "clearly: (1) superior recent form, (2) home advantage, (3) no significant injury disruptions, "
            "(4) positive H2H record, (5) favourable weather/venue. "
            "Assign LOW confidence whenever a key factor is missing or contradictory. "
            "When in doubt, use MEDIUM."
        ),
    },
    {
        "variantId": "margin-conservative",
        "hypothesis": "Conservative margins — NRL is a low-variance competition, 10+ pt wins are unusual",
        "dimensions": ["margin_calibration"],
        "prompt_template": _BASE_PROMPT + (
            "\n\nMARGIN CALIBRATION: The NRL is a high-parity competition. The average winning margin is ~12 points. "
            "When uncertain, predict a margin of 6-10 rather than committing to a larger number. "
            "Only predict a margin above 16 points when the evidence is overwhelming (top team vs bottom team, "
            "major injuries to the underdog, or a massive H2H mismatch)."
        ),
    },
    {
        "variantId": "upset-detector",
        "hypothesis": "Actively seeking upset conditions improves accuracy on the 30-40% of matches where the underdog wins",
        "dimensions": ["upset_detection"],
        "prompt_template": _BASE_PROMPT.replace(
            "7. TRAP GAME CHECK — Run the trap game detector. If the trap score is >= 2, seriously consider whether the favourite is vulnerable. Trap games (sandwich fixtures, emotional letdowns, dead rubbers, revenge games) are a major source of upsets. Even a small trap score should nudge your confidence down.",
            "7. TRAP GAME AND UPSET CHECK — Run the trap game detector. ACTIVELY look for reasons the underdog might win: "
            "(a) is the favourite in a sandwich game or emotionally drained? "
            "(b) does the underdog have superior recent form? "
            "(c) is the underdog at home or coming off a rest week? "
            "(d) does the underdog have a structural H2H edge? "
            "If 2+ upset conditions exist, consider picking the underdog unless the talent gap is overwhelming. "
            "At least 35% of NRL matches are won by the underdog — do not default to the favourite.",
        ),
    },
]


def seed(table_name: str, dry_run: bool = False) -> None:
    version = datetime.now(UTC).isoformat()
    print(f"Seeding {len(_VARIANTS)} variants to {table_name} (version={version})")

    if not dry_run:
        table = boto3.resource("dynamodb").Table(table_name)

    for v in _VARIANTS:
        item = {
            "variantId": v["variantId"],
            "version": version,
            "prompt_template": v["prompt_template"],
            "hypothesis": v["hypothesis"],
            "dimensions": v["dimensions"],
            "active": True,
        }
        if dry_run:
            print(f"  [dry-run] would write: {v['variantId']} ({len(v['prompt_template'])} chars)")
        else:
            table.put_item(Item=item)
            print(f"  wrote: {v['variantId']}")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed prompt variants")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--table", default=os.environ.get("PROMPT_VARIANTS_TABLE", "prompt_variants"))
    args = parser.parse_args()
    seed(args.table, dry_run=args.dry_run)
