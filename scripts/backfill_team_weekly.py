# scripts/backfill_team_weekly.py
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from db import SessionLocal  # noqa: E402
from models_normalized import Team, StatWeekly, StatSeason  # noqa: E402
from analysis.loaders import get_league  # noqa: E402

LEAGUE_ID = 70600

KEYMAP = {
    "3PM": "tpm",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "PTS": "pts",
    "DD": "dd",
    "GP": "games_played",
}

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

def upsert_weekly(session, season: int, week: int, team: Team, stats: Dict[str, Any]) -> None:
    row = (
        session.query(StatWeekly)
        .filter_by(league_id=LEAGUE_ID, season=season, week=week, team_id=team.id)
        .one_or_none()
    )
    if row is None:
        row = StatWeekly(league_id=LEAGUE_ID, season=season, week=week, team_id=team.id)
        session.add(row)

    for espn_key, col in KEYMAP.items():
        val = stats.get(espn_key, 0)
        try:
            setattr(row, col, int(float(val)) if val is not None else 0)
        except Exception:
            setattr(row, col, 0)

    fg = stats.get("FG%")
    ft = stats.get("FT%")
    row.fg_pct = float(fg) if fg is not None else None
    row.ft_pct = float(ft) if ft is not None else None

    # keep makes/attempts as 0 so later math doesn't blow up
    row.fgm = 0
    row.fga = 0
    row.ftm = 0
    row.fta = 0

def refresh_season(session, season: int) -> None:
    session.query(StatSeason).filter_by(league_id=LEAGUE_ID, season=season).delete(synchronize_session=False)

    team_ids = [
        tid for (tid,) in session.query(StatWeekly.team_id)
        .filter_by(league_id=LEAGUE_ID, season=season)
        .distinct()
        .all()
    ]

    for team_id in team_ids:
        weeks = (
            session.query(StatWeekly)
            .filter_by(league_id=LEAGUE_ID, season=season, team_id=team_id)
            .all()
        )
        if not weeks:
            continue

        ss = StatSeason(league_id=LEAGUE_ID, season=season, team_id=team_id)
        ss.games_played = sum(w.games_played or 0 for w in weeks)
        ss.fgm = sum(w.fgm or 0 for w in weeks)
        ss.fga = sum(w.fga or 0 for w in weeks)
        ss.ftm = sum(w.ftm or 0 for w in weeks)
        ss.fta = sum(w.fta or 0 for w in weeks)
        ss.tpm = sum(w.tpm or 0 for w in weeks)
        ss.reb = sum(w.reb or 0 for w in weeks)
        ss.ast = sum(w.ast or 0 for w in weeks)
        ss.stl = sum(w.stl or 0 for w in weeks)
        ss.blk = sum(w.blk or 0 for w in weeks)
        ss.pts = sum(w.pts or 0 for w in weeks)
        ss.dd  = sum(w.dd  or 0 for w in weeks)

        ss.fg_pct = (ss.fgm / ss.fga) if ss.fga else None
        ss.ft_pct = (ss.ftm / ss.fta) if ss.fta else None

        session.add(ss)

def extract_scoreboard_stats(m, side: str) -> Dict[str, Any]:
    for attr in (f"{side}_stats", f"{side}_score", f"{side}_scores"):
        d = getattr(m, attr, None)
        if isinstance(d, dict) and d:
            return d

    team_obj = getattr(m, f"{side}_team", None)
    if team_obj is not None:
        d2 = getattr(team_obj, "stats", None)
        if isinstance(d2, dict) and d2:
            d2 = dict(d2)
            d2["_source"] = "team.stats_season_totals_fallback"
            return d2

    return {}

def _guess_max_week(league) -> int:
    w = getattr(getattr(league, "settings", None), "reg_season_count", None)
    if isinstance(w, int) and w > 0:
        return w
    return 22

def infer_latest_week_with_scoreboard(league, max_week: int) -> int | None:
    latest = None
    for wk in range(1, max_week + 1):
        try:
            sb = league.scoreboard(wk)
        except Exception:
            break
        if not sb:
            break
        latest = wk
    return latest

def main(
    start_year: int = 2014,
    end_year: int | None = None,
    season: int | None = None,
    week: int | None = None,
    latest_only: bool = False,
    refresh_season_totals: bool = False,
):
    if end_year is None:
        end_year = datetime.now().year

    session = SessionLocal()
    try:
        seasons = [season] if season is not None else list(range(start_year, end_year + 1))

        for s in seasons:
            lg = get_league(s)
            teams_by_espn = {t.team_id: ensure_team(session, s, t) for t in lg.teams}
            session.commit()

            max_week = _guess_max_week(lg)

            if latest_only:
                latest = infer_latest_week_with_scoreboard(lg, max_week)
                if latest is None:
                    print(f"{s}: no scoreboard weeks yet")
                    continue
                weeks = [latest]
            elif week is not None:
                weeks = [week]
            else:
                weeks = list(range(1, max_week + 1))

            for wk in weeks:
                sb = lg.scoreboard(wk)
                if not sb:
                    break

                for m in sb:
                    ht = teams_by_espn.get(m.home_team.team_id)
                    at = teams_by_espn.get(m.away_team.team_id)
                    if ht is None or at is None:
                        continue

                    hstats = extract_scoreboard_stats(m, "home")
                    astats = extract_scoreboard_stats(m, "away")

                    upsert_weekly(session, s, wk, ht, hstats)
                    upsert_weekly(session, s, wk, at, astats)

                session.commit()

            if refresh_season_totals and week is None and not latest_only:
                refresh_season(session, s)
                session.commit()

            print(f"Backfilled {s} weeks={weeks}")

    finally:
        session.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start-year", type=int, default=2014)
    p.add_argument("--end-year", type=int, default=None, help="Default = current year")
    p.add_argument("--season", type=int, default=None)
    p.add_argument("--week", type=int, default=None)
    p.add_argument("--latest-only", action="store_true")
    p.add_argument("--refresh-season-totals", action="store_true")
    args = p.parse_args()

    main(
        start_year=args.start_year,
        end_year=args.end_year,
        season=args.season,
        week=args.week,
        latest_only=args.latest_only,
        refresh_season_totals=args.refresh_season_totals,
    )