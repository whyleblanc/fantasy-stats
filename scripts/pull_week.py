#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from typing import Dict, Optional, Tuple, List

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

from db import SessionLocal, WeekTeamStats
from models_normalized import StatWeekly, Team
from analysis.constants import CATEGORIES, CAT_TO_DB_COL
from webapp.config import LEAGUE_ID
from webapp.services.espn_ingest import sync_week


# -----------------------------
# dotenv loading (robust)
# -----------------------------
def _load_env() -> None:
    """
    Avoid dotenv AssertionError in some interactive contexts by explicitly pointing to .env.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dotenv_path = os.path.join(repo_root, ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)


# -----------------------------
# DB helpers for defaults/latest
# -----------------------------
def _default_season_from_db(session: Session) -> int:
    """
    Most recent season present in DB for this league (teams table).
    """
    row = session.execute(
        text("""
            SELECT MAX(season) AS season
            FROM teams
            WHERE league_id = :lid
        """),
        {"lid": LEAGUE_ID},
    ).fetchone()

    season = row[0] if row else None
    if season is None:
        raise RuntimeError("Could not determine default season from DB (teams table empty?)")
    return int(season)


def _latest_completed_week_from_db(session: Session, season: int) -> Optional[int]:
    """
    Latest week that is completed (winner_team_id NOT NULL).
    """
    row = session.execute(
        text("""
            SELECT MAX(week) AS week
            FROM matchups
            WHERE league_id = :lid
              AND season = :season
              AND winner_team_id IS NOT NULL
        """),
        {"lid": LEAGUE_ID, "season": int(season)},
    ).fetchone()

    wk = row[0] if row else None
    return int(wk) if wk is not None else None


def _status_for_week(session: Session, season: int, week: int) -> Tuple[int, int, int]:
    """
    Returns:
      completed_matchups, weekteamstats_rows, teams_in_season
    """
    completed_matchups = session.execute(
        text("""
            SELECT COUNT(*)
            FROM matchups
            WHERE league_id = :lid
              AND season = :season
              AND week = :week
              AND winner_team_id IS NOT NULL
        """),
        {"lid": LEAGUE_ID, "season": int(season), "week": int(week)},
    ).fetchone()[0]

    weekteamstats_rows = session.execute(
        text("""
            SELECT COUNT(*)
            FROM week_team_stats
            WHERE league_id = :lid
              AND year = :season
              AND week = :week
        """),
        {"lid": LEAGUE_ID, "season": int(season), "week": int(week)},
    ).fetchone()[0]

    teams = session.execute(
        text("""
            SELECT COUNT(*)
            FROM teams
            WHERE league_id = :lid
              AND season = :season
        """),
        {"lid": LEAGUE_ID, "season": int(season)},
    ).fetchone()[0]

    return int(completed_matchups), int(weekteamstats_rows), int(teams)


# -----------------------------
# WeekTeamStats builder (single week)
# -----------------------------
def _z(val: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return (val - mean) / std


def _raw_from_weekly(w: StatWeekly) -> Dict[str, float | None]:
    fg = float(w.fg_pct) if w.fg_pct is not None else None
    ft = float(w.ft_pct) if w.ft_pct is not None else None
    return {
        "FG%": fg,
        "FT%": ft,
        "3PM": float(w.tpm or 0),
        "REB": float(w.reb or 0),
        "AST": float(w.ast or 0),
        "STL": float(w.stl or 0),
        "BLK": float(w.blk or 0),
        "DD": float(w.dd or 0),
        "PTS": float(w.pts or 0),
    }


def rebuild_weekteamstats_for_week(session: Session, season: int, week: int) -> int:
    """
    Build week_team_stats rows for one (season, week) from stats_weekly + teams.
    """
    session.query(WeekTeamStats).filter(
        WeekTeamStats.league_id == LEAGUE_ID,
        WeekTeamStats.year == int(season),
        WeekTeamStats.week == int(week),
    ).delete(synchronize_session=False)
    session.flush()

    rows: List[Tuple[StatWeekly, Team]] = (
        session.query(StatWeekly, Team)
        .join(Team, StatWeekly.team_id == Team.id)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season == int(season),
            StatWeekly.week == int(week),
            Team.league_id == LEAGUE_ID,
            Team.season == int(season),
        )
        .all()
    )
    if not rows:
        return 0

    team_raw: Dict[int, Dict[str, float | None]] = {}
    team_name: Dict[int, str] = {}

    for w, t in rows:
        if t.espn_team_id is None:
            continue
        tid = int(t.espn_team_id)
        team_raw[tid] = _raw_from_weekly(w)
        team_name[tid] = str(t.name)

    if not team_raw:
        return 0

    means: Dict[str, float] = {}
    stds: Dict[str, float] = {}

    for cat in CATEGORIES:
        vals = [v[cat] for v in team_raw.values() if v.get(cat) is not None]
        if not vals:
            means[cat] = 0.0
            stds[cat] = 0.0
            continue
        n = len(vals)
        mean = sum(float(x) for x in vals) / n
        var = sum((float(x) - mean) ** 2 for x in vals) / n
        means[cat] = float(mean)
        stds[cat] = float(var ** 0.5)

    built = 0
    for tid, raw in team_raw.items():
        total_z = 0.0
        row = WeekTeamStats(
            league_id=LEAGUE_ID,
            year=int(season),
            week=int(week),
            team_id=int(tid),
            team_name=team_name.get(tid, f"Team {tid}"),
            is_league_average=False,
        )

        for cat in CATEGORIES:
            val = raw.get(cat)
            z = _z(float(val), means[cat], stds[cat]) if val is not None else 0.0
            total_z += z
            setattr(row, CAT_TO_DB_COL[cat], float(z))

        row.total_z = float(total_z)
        session.add(row)
        built += 1

    return built


# -----------------------------
# Main
# -----------------------------
def main(season: Optional[int], week: Optional[int], latest: bool, force: bool) -> int:
    _load_env()

    espn_swid = os.getenv("ESPN_SWID")
    espn_s2 = os.getenv("ESPN_S2")
    if not espn_swid or not espn_s2:
        raise SystemExit("Missing ESPN_SWID / ESPN_S2 in .env")

    session = SessionLocal()
    try:
        if season is None:
            season = _default_season_from_db(session)

        if latest:
            wk = _latest_completed_week_from_db(session, season)
            if wk is None:
                print(f"[ERR] No completed weeks found for season={season}.")
                return 2
            week = wk

        if week is None:
            print("[ERR] Must provide --week or --latest.")
            return 2

        completed_matchups, weekteamstats_rows, teams = _status_for_week(session, season, week)

        if (not force) and completed_matchups > 0 and teams > 0 and weekteamstats_rows == teams:
            print(
                f"[SKIP] {season} week {week} already completed and computed "
                f"(completed_matchups={completed_matchups}, weekteamstats_rows={weekteamstats_rows}, teams={teams}). "
                f"Use --force to override."
            )
            return 0

        print(f"[INGEST] season={season} week={week}")
        sync_week(
            session=session,
            league_id=LEAGUE_ID,
            season=int(season),
            week=int(week),
            espn_swid=espn_swid,
            espn_s2=espn_s2,
        )

        built = rebuild_weekteamstats_for_week(session, int(season), int(week))
        session.commit()

        print(f"[OK] season={season} week={week} | week_team_stats rows built={built}")
        return 0

    except Exception as e:
        session.rollback()
        print(f"[ERR] Failed season={season} week={week}: {e!r}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, default=None, help="Season year (default: latest season in DB)")
    p.add_argument("--week", type=int, default=None, help="Week number to pull/compute")
    p.add_argument("--latest", action="store_true", help="Use most recent completed week from DB (winner_team_id not null)")
    p.add_argument("--force", action="store_true", help="Force recompute even if guard says completed+computed")
    args = p.parse_args()

    raise SystemExit(main(args.season, args.week, args.latest, args.force))