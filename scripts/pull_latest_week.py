# scripts/pull_latest_week.py
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.backfill_weekly_from_boxscores import main as backfill_boxscores_main  # noqa: E402

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, default=datetime.now().year, help="Default = current year")
    args = p.parse_args()

    backfill_boxscores_main(
        start_season=args.season,
        end_season=args.season,
        season=args.season,
        week=None,
        wipe_season=False,
        latest_only=True,
    )

if __name__ == "__main__":
    main()