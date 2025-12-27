# scripts/rebuild_season_team_metrics.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from sqlalchemy import text
from db import SessionLocal
from webapp.config import LEAGUE_ID, MAX_YEAR


SQL_DELETE_YEAR = """
DELETE FROM season_team_metrics
WHERE league_id = :league_id AND year = :year;
"""

SQL_INSERT_YEAR = """
INSERT INTO season_team_metrics (
  league_id,
  year,
  team_id,
  team_name,
  weeks,
  sum_total_z,
  avg_total_z,
  actual_win_pct,
  expected_win_pct,
  luck_index,
  fraud_score,
  fraud_label,
  created_at,
  updated_at
)
SELECT
  w.league_id,
  w.year,
  w.team_id,
  MAX(w.team_name) AS team_name,
  COUNT(w.week) AS weeks,
  SUM(w.total_z) AS sum_total_z,
  AVG(w.total_z) AS avg_total_z,
  NULL AS actual_win_pct,
  NULL AS expected_win_pct,
  NULL AS luck_index,
  NULL AS fraud_score,
  NULL AS fraud_label,
  CURRENT_TIMESTAMP AS created_at,
  CURRENT_TIMESTAMP AS updated_at
FROM week_team_stats w
WHERE
  w.league_id = :league_id
  AND w.is_league_average = 0
  AND w.year = :year
GROUP BY
  w.league_id, w.year, w.team_id;
"""

SQL_YEARS_AVAILABLE = """
SELECT DISTINCT year
FROM week_team_stats
WHERE league_id = :league_id AND is_league_average = 0
ORDER BY year;
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=None, help="Single year (e.g. 2026)")
    p.add_argument("--all", action="store_true", help="All years available in week_team_stats")
    p.add_argument("--force", action="store_true", help="Delete rows before insert")
    args = p.parse_args()

    session = SessionLocal()
    try:
        if args.all:
            years = [
                int(r[0])
                for r in session.execute(text(SQL_YEARS_AVAILABLE), {"league_id": LEAGUE_ID}).fetchall()
            ]
            # safety clamp
            years = [y for y in years if 2014 <= y <= int(MAX_YEAR)]
        else:
            years = [int(args.year or MAX_YEAR)]

        total = 0
        for y in years:
            if args.force:
                session.execute(text(SQL_DELETE_YEAR), {"league_id": LEAGUE_ID, "year": int(y)})

            session.execute(text(SQL_INSERT_YEAR), {"league_id": LEAGUE_ID, "year": int(y)})
            session.commit()

            n = session.execute(
                text("SELECT COUNT(*) FROM season_team_metrics WHERE league_id=:league_id AND year=:year;"),
                {"league_id": LEAGUE_ID, "year": int(y)},
            ).scalar() or 0

            print(f"[OK] {y}: season_team_metrics rows={int(n)}")
            total += int(n)

        print(f"[DONE] total rows inserted (sum across years): {total}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()