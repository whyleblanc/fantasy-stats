# scripts/backfill_weekly_from_boxscores.py
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, Iterable

# Allow running as: python scripts/xxx.py from repo root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from db import SessionLocal  # noqa: E402
from models_normalized import Team, StatWeekly  # noqa: E402
from analysis.loaders import get_league  # noqa: E402
from webapp.config import LEAGUE_ID  # noqa: E402


# keys present in box_scores stats dict (weekly totals)
COUNTING_KEYS = {
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
    "3PM": "tpm",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "PTS": "pts",
    "DD": "dd",
}

def _unwrap(v):
    return v.get("value") if isinstance(v, dict) else v

def _to_int(v, default=0) -> int:
    v = _unwrap(v)
    if v is None:
        return default
    try:
        return int(float(v))
    except Exception:
        return default

def _to_float(v, default=None):
    v = _unwrap(v)
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default

def ensure_team(session, season: int, espn_team) -> Team:
    team = (
        session.query(Team)
        .filter_by(league_id=LEAGUE_ID, season=season, espn_team_id=espn_team.team_id)
        .one_or_none()
    )
    if team is None:
        team = Team(
            league_id=LEAGUE_ID,
            season=season,
            espn_team_id=espn_team.team_id,
            name=espn_team.team_name,
            abbrev=getattr(espn_team, "team_abbrev", None),
            owner=getattr(espn_team, "owner", None),
        )
        session.add(team)
        session.flush()
    else:
        team.name = espn_team.team_name
        team.abbrev = getattr(espn_team, "team_abbrev", team.abbrev)
        team.owner = getattr(espn_team, "owner", team.owner)
    return team

def upsert_week(session, season: int, week: int, team: Team, stats: Dict[str, Any]) -> None:
    row = (
        session.query(StatWeekly)
        .filter_by(league_id=LEAGUE_ID, season=season, week=week, team_id=team.id)
        .one_or_none()
    )
    if row is None:
        row = StatWeekly(league_id=LEAGUE_ID, season=season, week=week, team_id=team.id)
        session.add(row)

    for k, col in COUNTING_KEYS.items():
        setattr(row, col, _to_int(stats.get(k), 0))

    row.fg_pct = _to_float(stats.get("FG%"), None)
    row.ft_pct = _to_float(stats.get("FT%"), None)

    # ensure safe ints if schema expects them
    row.fgm = row.fgm or 0
    row.fga = row.fga or 0
    row.ftm = row.ftm or 0
    row.fta = row.fta or 0

def _guess_max_week(league) -> int:
    w = getattr(getattr(league, "settings", None), "reg_season_count", None)
    if isinstance(w, int) and w > 0:
        return w
    return 22

def infer_latest_week_with_boxscores(league, max_week: int) -> int | None:
    """
    Returns latest week number that actually returns box_scores().
    Stops at first empty/exception-y future week.
    """
    latest = None
    for wk in range(1, max_week + 1):
        try:
            box = league.box_scores(wk)
        except Exception:
            break
        if not box:
            break
        latest = wk
    return latest

def iter_seasons(start: int | None, end: int | None, season: int | None) -> Iterable[int]:
    if season is not None:
        yield int(season)
        return
    start = int(start) if start is not None else 2019
    end = int(end) if end is not None else datetime.now().year
    if end < start:
        start, end = end, start
    for s in range(start, end + 1):
        yield s

def main(
    start_season: int | None,
    end_season: int | None,
    season: int | None,
    week: int | None,
    wipe_season: bool,
    latest_only: bool,
) -> None:
    session = SessionLocal()
    try:
        for s in iter_seasons(start_season, end_season, season):
            lg = get_league(s)

            teams_by_espn = {t.team_id: ensure_team(session, s, t) for t in lg.teams}
            session.commit()

            max_week = _guess_max_week(lg)

            # Decide which weeks to run
            if latest_only:
                latest = infer_latest_week_with_boxscores(lg, max_week)
                if latest is None:
                    print(f"{s}: no available box_scores weeks yet")
                    continue
                weeks = [latest]
            elif week is not None:
                weeks = [int(week)]
            else:
                weeks = list(range(1, max_week + 1))

            # Wipe only if explicitly requested AND doing a full season rebuild
            if wipe_season and week is None and not latest_only:
                deleted = (
                    session.query(StatWeekly)
                    .filter_by(league_id=LEAGUE_ID, season=s)
                    .delete(synchronize_session=False)
                )
                session.commit()
                print(f"{s}: deleted stats_weekly rows: {deleted}")

            for wk in weeks:
                try:
                    box = lg.box_scores(wk)
                except Exception as e:
                    print(f"{s} week {wk}: ERR {e!r}")
                    break

                if not box:
                    print(f"{s} week {wk}: no box_scores returned")
                    break

                for b in box:
                    ht = teams_by_espn.get(b.home_team.team_id)
                    at = teams_by_espn.get(b.away_team.team_id)
                    if not ht or not at:
                        continue

                    hstats = getattr(b, "home_stats", None) or {}
                    astats = getattr(b, "away_stats", None) or {}

                    if isinstance(hstats, dict) and hstats:
                        upsert_week(session, s, wk, ht, hstats)
                    if isinstance(astats, dict) and astats:
                        upsert_week(session, s, wk, at, astats)

                session.commit()
                print(f"backfilled {s} week {wk} ({len(box)} matchups)")

    finally:
        session.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start-season", type=int, default=2019)
    p.add_argument("--end-season", type=int, default=None, help="Default = current year")
    p.add_argument("--season", type=int, default=None, help="Run a single season only")
    p.add_argument("--week", type=int, default=None, help="Run a single week only")
    p.add_argument("--latest-only", action="store_true", help="Run only the latest available week (per season)")
    p.add_argument("--wipe-season", action="store_true", help="DANGER: wipes stats_weekly for the season (full rebuild only)")
    args = p.parse_args()

    main(
        start_season=args.start_season,
        end_season=args.end_season,
        season=args.season,
        week=args.week,
        wipe_season=args.wipe_season,
        latest_only=args.latest_only,
    )