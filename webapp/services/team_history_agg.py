# webapp/services/team_history_agg.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from webapp.config import LEAGUE_ID
from db import WeekTeamStats
from models_aggregates import TeamHistoryAgg

# Map your canonical categories to WeekTeamStats columns
CAT_TO_COL = {
    "FG%": "fg_z",
    "FT%": "ft_z",
    "3PM": "three_pm_z",
    "REB": "reb_z",
    "AST": "ast_z",
    "STL": "stl_z",
    "BLK": "blk_z",
    "DD": "dd_z",
    "PTS": "pts_z",
}

LEAGUE_CAT_TO_COL = {
    "FG%": "league_fg_z",
    "FT%": "league_ft_z",
    "3PM": "league_three_pm_z",
    "REB": "league_reb_z",
    "AST": "league_ast_z",
    "STL": "league_stl_z",
    "BLK": "league_blk_z",
    "DD": "league_dd_z",
    "PTS": "league_pts_z",
}


def _week_ranks_from_weekteamstats(
    session: Session, year: int, week: int
) -> Dict[int, int]:
    """
    Returns {team_id: rank} for the week, where team_id is ESPN team id
    based on WeekTeamStats.total_z descending (1 = best).
    """
    rows = (
        session.query(WeekTeamStats.team_id, WeekTeamStats.total_z)
        .filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.year == year,
            WeekTeamStats.week == week,
            WeekTeamStats.is_league_average == False,
        )
        .order_by(WeekTeamStats.total_z.desc())
        .all()
    )

    ranks: Dict[int, int] = {}
    rank = 1
    for tid, _tz in rows:
        if tid is None:
            continue
        ranks[int(tid)] = rank
        rank += 1
    return ranks


def rebuild_team_history_agg(
    session: Session,
    year: int,
    team_id: Optional[int] = None,
    force: bool = False,
) -> int:
    """
    Rebuild team_history_agg for:
      - a single team_id (ESPN team id) if provided, otherwise all teams.
    Uses WeekTeamStats as the source of truth.

    Returns number of rows written.
    """
    # If not forcing: if we already have rows for that year/team, skip
    if not force and team_id is not None:
        exists = (
            session.query(TeamHistoryAgg.id)
            .filter(
                TeamHistoryAgg.league_id == LEAGUE_ID,
                TeamHistoryAgg.year == year,
                TeamHistoryAgg.team_id == int(team_id),
            )
            .first()
        )
        if exists:
            return 0

    # Pull all WeekTeamStats rows for that year (and optionally team)
    q = session.query(WeekTeamStats).filter(
        WeekTeamStats.league_id == LEAGUE_ID,
        WeekTeamStats.year == year,
        WeekTeamStats.is_league_average == False,
    )
    if team_id is not None:
        q = q.filter(WeekTeamStats.team_id == int(team_id))

    week_rows: List[WeekTeamStats] = q.order_by(WeekTeamStats.week.asc()).all()
    if not week_rows:
        return 0

    # Build lookup of league average rows by week
    league_rows = (
        session.query(WeekTeamStats)
        .filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.year == year,
            WeekTeamStats.is_league_average == True,
        )
        .all()
    )
    league_by_week: Dict[int, WeekTeamStats] = {}
    for r in league_rows:
        if r.week is None:
            continue
        league_by_week[int(r.week)] = r

    # If forcing, delete existing agg rows for this scope
    del_q = session.query(TeamHistoryAgg).filter(
        TeamHistoryAgg.league_id == LEAGUE_ID,
        TeamHistoryAgg.year == year,
    )
    if team_id is not None:
        del_q = del_q.filter(TeamHistoryAgg.team_id == int(team_id))
    if force:
        del_q.delete(synchronize_session=False)
        session.flush()

    # Precompute ranks per week (only for weeks we touch)
    weeks = sorted({int(r.week) for r in week_rows if r.week is not None})
    ranks_by_week: Dict[int, Dict[int, int]] = {}
    for wk in weeks:
        ranks_by_week[wk] = _week_ranks_from_weekteamstats(session, year, wk)

    # Group rows by team for cumulative calc
    by_team: Dict[int, List[WeekTeamStats]] = {}
    for r in week_rows:
        if r.team_id is None or r.week is None:
            continue
        by_team.setdefault(int(r.team_id), []).append(r)

    written = 0

    for tid, rows in by_team.items():
        rows.sort(key=lambda x: int(x.week or 0))
        cum = 0.0

        for r in rows:
            wk = int(r.week)
            tz = float(r.total_z or 0.0)
            cum += tz

            league = league_by_week.get(wk)

            agg = TeamHistoryAgg(
                league_id=LEAGUE_ID,
                year=int(year),
                week=wk,
                team_id=int(tid),
                team_name=r.team_name,
                rank=ranks_by_week.get(wk, {}).get(int(tid)),
                total_z=tz,
                cumulative_total_z=float(cum),
                league_average_total_z=float(league.total_z) if league and league.total_z is not None else None,
            )

            # Weekly category z
            for cat, col in CAT_TO_COL.items():
                setattr(agg, col, float(getattr(r, col) or 0.0))

            # League category z
            if league:
                for cat, col in LEAGUE_CAT_TO_COL.items():
                    base_col = CAT_TO_COL[cat]
                    setattr(agg, col, float(getattr(league, base_col) or 0.0))

            session.add(agg)
            written += 1

    return written


def get_team_history_from_agg(
    session: Session,
    year: int,
    team_id: int,
    categories: List[str],
) -> Dict[str, Any]:
    """
    Returns payload compatible with your frontend HistoryTab expectations:
      {
        teamId, teamName,
        history: [
          {
            week, rank, totalZ, cumulativeTotalZ,
            leagueAverageTotalZ,
            zscores: { "FG%_z": ..., ... },
            leagueAverageZscores: { "FG%_z": ..., ... }
          },
          ...
        ]
      }
    """
    rows = (
        session.query(TeamHistoryAgg)
        .filter(
            TeamHistoryAgg.league_id == LEAGUE_ID,
            TeamHistoryAgg.year == int(year),
            TeamHistoryAgg.team_id == int(team_id),
        )
        .order_by(TeamHistoryAgg.week.asc())
        .all()
    )

    if not rows:
        return {"teamId": int(team_id), "teamName": "", "history": []}

    team_name = rows[0].team_name or ""

    history = []
    for r in rows:
        zscores = {}
        league_zscores = {}

        for cat in categories:
            base_col = CAT_TO_COL.get(cat)
            league_col = LEAGUE_CAT_TO_COL.get(cat)
            if not base_col or not league_col:
                continue
            zscores[f"{cat}_z"] = float(getattr(r, base_col) or 0.0)
            league_zscores[f"{cat}_z"] = float(getattr(r, league_col) or 0.0)

        history.append(
            {
                "week": int(r.week),
                "rank": int(r.rank) if r.rank is not None else None,
                "totalZ": float(r.total_z or 0.0),
                "cumulativeTotalZ": float(r.cumulative_total_z or 0.0),
                "leagueAverageTotalZ": float(r.league_average_total_z) if r.league_average_total_z is not None else 0.0,
                "zscores": zscores,
                "leagueAverageZscores": league_zscores,
            }
        )

    return {"teamId": int(team_id), "teamName": team_name, "history": history}