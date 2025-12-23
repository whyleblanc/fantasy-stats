from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
import sqlite3


DB_PATH_DEFAULT = "fantasy_stats.db"


def _repo_root() -> Path:
    # scripts/ -> repo root
    return Path(__file__).resolve().parents[1]


def _db_path(db_path: str | None) -> Path:
    if db_path:
        p = Path(db_path)
        return p if p.is_absolute() else (_repo_root() / p)
    return _repo_root() / DB_PATH_DEFAULT


def _latest_completed_week(db_file: Path, league_id: int, season: int) -> int | None:
    """
    Latest week where ALL matchups have winner_team_id populated.
    """
    conn = sqlite3.connect(str(db_file))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT week
            FROM matchups
            WHERE league_id = ?
              AND season = ?
            GROUP BY week
            HAVING SUM(CASE WHEN winner_team_id IS NULL THEN 1 ELSE 0 END) = 0
            ORDER BY week DESC
            LIMIT 1
            """,
            (league_id, season),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


def _run(cmd: list[str]) -> None:
    print(f"[RUN] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-pull a rolling window of completed weeks (stat corrections).")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--league-id", type=int, default=70600)
    ap.add_argument("--window", type=int, default=4, help="How many completed weeks to re-pull (default=4).")
    ap.add_argument("--db", type=str, default=DB_PATH_DEFAULT, help="Path to SQLite db (default=fantasy_stats.db).")
    ap.add_argument("--force", action="store_true", help="Force recompute even if guard would skip.")
    ap.add_argument("--rebuild-opponent-agg", action="store_true", help="Rebuild opponent_matrix_agg_year after pulls.")
    ap.add_argument(
        "--rebuild-team-history-agg",
        action="store_true",
        help="Rebuild team_history_agg after pulls (only works if you have a script/module for it).",
    )

    args = ap.parse_args()

    db_file = _db_path(args.db)
    if not db_file.exists():
        print(f"[ERROR] DB not found: {db_file}")
        return 1

    latest = _latest_completed_week(db_file, args.league_id, args.season)
    if latest is None:
        print(f"[WARN] No completed weeks found for season={args.season} (winner_team_id still null everywhere).")
        return 0

    start = max(1, latest - int(args.window) + 1)
    weeks = list(range(start, latest + 1))

    print(f"[INFO] season={args.season} latest_completed_week={latest} rolling_window={start}..{latest}")

    # Use the same interpreter you invoked this script with (and PYTHONPATH=. from your shell)
    py = sys.executable

    for w in weeks:
        cmd = [py, "scripts/pull_week.py", "--season", str(args.season), "--week", str(w)]
        if args.force:
            cmd.append("--force")
        _run(cmd)

    if args.rebuild_opponent_agg:
        _run([py, "scripts/rebuild_opponent_matrix_agg_year.py", "--year", str(args.season), "--force"])
    
    if args.rebuild_team_history_agg:
        # Only run if you actually have a module/script for this (we can add it in Phase 3)
        # If it fails, you'll see it immediately.
        _run([py, "-m", "scripts.rebuild_team_history_agg", "--year", str(args.season), "--force"])

    print("[DONE] corrections complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())