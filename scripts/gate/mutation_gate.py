#!/usr/bin/env python3
"""Mutation gate runner (CHG-0027 pilot) — bound as `mutation` in .claude/harness.json.

Drives mutmut over the pilot surface declared in [tool.mutmut] (pyproject.toml),
converts the results into a Stryker-schema report at reports/mutation/mutation.json
(the file gate-mutation reads for its survivor summary), and applies the verdict:
exit 1 when the mutation score is below the break threshold.

The break threshold is 100: every mutant on the pilot surface must be killed.
Genuinely equivalent mutants are exempted at the source with `# pragma: no mutate`
(visible in diff review) — never by lowering the threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# gate-mutation runs the bound command without the binding's env block, and the
# suite imports boto3 clients — provide the same dummy AWS env the CI gate uses.
ENV = dict(os.environ)
for _key, _value in {
    "AWS_DEFAULT_REGION": "ap-southeast-2",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
}.items():
    ENV.setdefault(_key, _value)
DEFAULT_REPORT = REPO_ROOT / "reports" / "mutation" / "mutation.json"
MUTANTS_DIR = REPO_ROOT / "mutants"
SURVIVOR_DETAIL_CAP = 20

# Copy of mutmut.__main__.status_by_exit_code (mutmut 3.6) so we don't import
# mutmut internals; unknown exit codes are "suspicious", like mutmut itself.
STATUS_BY_EXIT_CODE = {
    1: "killed",
    3: "killed",  # pytest internal error while the mutant was active counts as a kill
    0: "survived",
    5: "no tests",
    33: "no tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "caught by type check",
    24: "timeout",
    152: "timeout",
    255: "timeout",
    -24: "timeout",
    -11: "segfault",
    -9: "segfault",
    2: "interrupted",
    None: "not checked",
}

# mutmut status → Stryker mutation-testing schema status. A segfault under the
# mutant is a detection (the suite blew up); suspicious is conservatively treated
# as undetected so it demands attention rather than hiding.
STRYKER_STATUS = {
    "killed": "Killed",
    "caught by type check": "Killed",
    "segfault": "Killed",
    "timeout": "Timeout",
    "survived": "Survived",
    "suspicious": "Survived",
    "no tests": "NoCoverage",
    "skipped": "Ignored",
    "interrupted": "RuntimeError",
    "not checked": "Pending",
}

DETECTED = {"Killed", "Timeout"}
UNDETECTED = {"Survived", "NoCoverage"}


def run_mutmut() -> None:
    """Run mutmut; its own failure surfaces via the meta files (or their absence)."""
    subprocess.run([sys.executable, "-m", "mutmut", "run"], cwd=REPO_ROOT, env=ENV, check=False)


def collect_mutants() -> dict[str, list[dict[str, Any]]]:
    """Read mutmut's per-file .meta results into {source_path: [mutant, ...]}."""
    files: dict[str, list[dict[str, Any]]] = {}
    for meta_path in sorted(MUTANTS_DIR.rglob("*.meta")):
        source = str(meta_path.relative_to(MUTANTS_DIR))[: -len(".meta")]
        meta = json.loads(meta_path.read_text())
        mutants = []
        for name, exit_code in meta.get("exit_code_by_key", {}).items():
            status = STATUS_BY_EXIT_CODE.get(exit_code, "suspicious")
            mutants.append(
                {
                    "id": name,
                    "mutatorName": name.rsplit(".", 1)[-1],
                    "replacement": "",
                    "status": STRYKER_STATUS[status],
                    "location": {"start": {"line": None, "column": 1}},
                }
            )
        if mutants:
            files[source] = mutants
    return files


def enrich_survivor(source: str, mutant: dict[str, Any]) -> None:
    """Best-effort: pull the mutated line + real line number from `mutmut show`."""
    show = subprocess.run(
        [sys.executable, "-m", "mutmut", "show", mutant["id"]],
        cwd=REPO_ROOT,
        env=ENV,
        capture_output=True,
        text=True,
    )
    removed, added = None, None
    for line in show.stdout.splitlines():
        if re.match(r"^-(?![-])", line):
            removed = line[1:].strip()
        elif re.match(r"^\+(?![+])", line):
            added = line[1:].strip()
    if added:
        mutant["replacement"] = added
    if removed:
        # mutmut's hunk offsets are function-relative; recover the absolute line
        # by finding the removed line in the real source instead.
        source_lines = (REPO_ROOT / source).read_text().splitlines()
        matches = [i + 1 for i, text in enumerate(source_lines) if text.strip() == removed]
        if len(matches) == 1:
            mutant["location"]["start"]["line"] = matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--break", dest="break_at", type=float, default=100.0,
                        help="minimum mutation score (default 100)")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-run", action="store_true",
                        help="reuse existing mutmut results; only rebuild the report")
    args = parser.parse_args()

    if not args.skip_run:
        run_mutmut()

    files = collect_mutants()
    if not files:
        print("✗ mutation gate: no mutmut results found (run failed before testing mutants?)")
        return 1

    all_mutants = [(source, m) for source, mutants in files.items() for m in mutants]
    incomplete = [m["id"] for _, m in all_mutants if m["status"] in ("Pending", "RuntimeError")]
    if incomplete:
        print(f"✗ mutation gate: {len(incomplete)} mutant(s) not checked (interrupted run?) — re-run.")
        return 1

    survivors = [(source, m) for source, m in all_mutants if m["status"] in UNDETECTED]
    for source, mutant in survivors[:SURVIVOR_DETAIL_CAP]:
        enrich_survivor(source, mutant)

    detected = sum(1 for _, m in all_mutants if m["status"] in DETECTED)
    undetected = len(survivors)
    total = detected + undetected
    score = round(detected / total * 100, 1) if total else 100.0

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "schemaVersion": "1",
                "thresholds": {"high": 100, "low": args.break_at},
                "mutationScore": score,
                "files": {
                    source: {"language": "python", "mutants": mutants}
                    for source, mutants in files.items()
                },
            },
            indent=2,
        )
        + "\n"
    )

    print(f"\nmutation score: {score}% ({detected}/{total} detected, {undetected} survived)")
    print(f"report: {args.report.relative_to(REPO_ROOT)}")
    if score < args.break_at:
        print(f"✗ below break threshold ({args.break_at}%)")
        return 1
    print(f"✓ at or above break threshold ({args.break_at}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
