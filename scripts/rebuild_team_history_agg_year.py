from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import argparse

from db import SessionLocal
from webapp.config import MAX_YEAR
from webapp.services.team_history_agg import rebuild_team_history_agg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    year = int(args.year or MAX_YEAR)

    session = SessionLocal()
    try:
        # Rebuild ALL teams for the year (team_id=None)
        rebuild_team_history_agg(session, year=year, team_id=None, force=bool(args.force))
        session.commit()
        print(f"[OK] {year}: rebuilt team_history_agg (all teams)")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()