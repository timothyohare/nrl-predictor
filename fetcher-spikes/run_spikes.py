#!/usr/bin/env python3
"""
NRL Predictor — Data Source Spikes
Run all spikes and print a summary report.

Usage:
    pip install requests beautifulsoup4 lxml
    python run_spikes.py
    python run_spikes.py --source nrl       # single source
    python run_spikes.py --source bom
    python run_spikes.py --source zerotackle
    python run_spikes.py --source supercoach
"""

import argparse
import importlib
import sys
import traceback
from datetime import datetime

SPIKES = ["nrl", "bom", "zerotackle", "supercoach"]

def run(source_name):
    print(f"\n{'='*60}")
    print(f"  SPIKE: {source_name.upper()}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    try:
        mod = importlib.import_module(f"spike_{source_name}")
        mod.run()
    except Exception as e:
        print(f"\n[FAIL] {type(e).__name__}: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=SPIKES, default=None)
    args = parser.parse_args()

    targets = [args.source] if args.source else SPIKES
    for s in targets:
        run(s)

    print(f"\n{'='*60}")
    print("  All spikes complete.")
    print(f"{'='*60}\n")
