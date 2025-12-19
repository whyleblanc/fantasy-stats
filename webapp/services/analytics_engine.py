# webapp/services/analytics_engine.py
"""
Analytics engine v1.

Bridges normalized per-team-per-week stats (StatWeekly)
into the legacy analytics tables:

- WeekTeamStats (per-team-per-week z-scores + total_z)
- SeasonTeamMetrics (per-team-per-season aggregates)

This is the glue between the new ingestion pipeline and your existing
frontend / build_league_payload logic.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from sqlalchemy.orm import Session

from db import WeekTeamStats, SeasonTeamMetrics
from models_normalized import (
    Player,
    Team,
    Matchup,
    StatRaw,
    StatWeekly,
    StatSeason,
)


# ---------- Public API ----------


def recompute_week_team_stats(
    session: Session,
    league_id: int,
    season: int,
    week: int,
) -> None:
    """
    Compute z-scores and total power for all teams for a given week,
    using StatWeekly as the source of truth, and write into WeekTeamStats.

    This will:
    - delete existing WeekTeamStats rows for (league_id, season, week)
    - insert fresh rows, one per fantasy team

    NOTE:
    - Uses population std dev (divide by N). If std == 0, z = 0 for that cat.
    - WeekTeamStats.team_id is set to the ESPN team id (Team.espn_team_id)
      to preserve compatibility with existing code.
    """
    # 1. Load weekly stats + team metadata
    rows: List[Tuple[StatWeekly, Team]] = (
        session.query(StatWeekly, Team)
        .join(Team, StatWeekly.team_id == Team.id)
        .filter(
            StatWeekly.league_id == league_id,
            StatWeekly.season == season,
            StatWeekly.week == week,
        )
        .all()
    )

    if not rows:
        # Nothing to compute; no teams for this week.
        session.query(WeekTeamStats).filter_by(
            league_id=league_id,
            year=season,
            week=week,
        ).delete(synchronize_session=False)
        return

    # 2. Extract per-category raw values into lists for mean/std computation

    # category -> list of values
    cat_values: Dict[str, List[float]] = defaultdict(list)

    # We build a simple cache so we don't have to recompute later.
    team_data: List[Dict] = []

    for weekly, team in rows:
        # derive percentages safely
        fg_pct = (
            float(weekly.fgm) / weekly.fga
            if (weekly.fga and weekly.fga > 0)
            else None
        )
        ft_pct = (
            float(weekly.ftm) / weekly.fta
            if (weekly.fta and weekly.fta > 0)
            else None
        )

        data = {
            "espn_team_id": team.espn_team_id,
            "team_name": team.name,
            "fg_pct": fg_pct,
            "ft_pct": ft_pct,
            "three_pm": float(weekly.tpm or 0),
            "reb": float(weekly.reb or 0),
            "ast": float(weekly.ast or 0),
            "stl": float(weekly.stl or 0),
            "blk": float(weekly.blk or 0),
            "dd": float(weekly.dd or 0),
            "pts": float(weekly.pts or 0),
        }
        team_data.append(data)

        # collect for league distribution
        if fg_pct is not None:
            cat_values["fg_pct"].append(fg_pct)
        if ft_pct is not None:
            cat_values["ft_pct"].append(ft_pct)

        cat_values["three_pm"].append(data["three_pm"])
        cat_values["reb"].append(data["reb"])
        cat_values["ast"].append(data["ast"])
        cat_values["stl"].append(data["stl"])
        cat_values["blk"].append(data["blk"])
        cat_values["dd"].append(data["dd"])
        cat_values["pts"].append(data["pts"])

    # 3. Compute mean/std per category
    cat_mean_std: Dict[str, Tuple[float, float]] = {}
    for cat, vals in cat_values.items():
        mean, std = _mean_std(vals)
        cat_mean_std[cat] = (mean, std)

    # 4. Clear existing WeekTeamStats for this slice
    session.query(WeekTeamStats).filter_by(
        league_id=league_id,
        year=season,
        week=week,
    ).delete(synchronize_session=False)

    # 5. Insert fresh WeekTeamStats rows
    for data in team_data:
        fg_z = _z_score(data["fg_pct"], *cat_mean_std.get("fg_pct", (0.0, 0.0)))
        ft_z = _z_score(data["ft_pct"], *cat_mean_std.get("ft_pct", (0.0, 0.0)))
        three_pm_z = _z_score(
            data["three_pm"], *cat_mean_std.get("three_pm", (0.0, 0.0))
        )
        reb_z = _z_score(data["reb"], *cat_mean_std.get("reb", (0.0, 0.0)))
        ast_z = _z_score(data["ast"], *cat_mean_std.get("ast", (0.0, 0.0)))
        stl_z = _z_score(data["stl"], *cat_mean_std.get("stl", (0.0, 0.0)))
        blk_z = _z_score(data["blk"], *cat_mean_std.get("blk", (0.0, 0.0)))
        dd_z = _z_score(data["dd"], *cat_mean_std.get("dd", (0.0, 0.0)))
        pts_z = _z_score(data["pts"], *cat_mean_std.get("pts", (0.0, 0.0)))

        # sum of all non-None z's
        total_z = sum(
            z for z in [
                fg_z,
                ft_z,
                three_pm_z,
                reb_z,
                ast_z,
                stl_z,
                blk_z,
                dd_z,
                pts_z,
            ]
            if z is not None
        )

        row = WeekTeamStats(
            league_id=league_id,
            year=season,
            week=week,
            team_id=data["espn_team_id"],   # preserve old semantics
            team_name=data["team_name"],
            is_league_average=False,
            result=None,  # to be filled later from matchup/category outcomes
            total_z=total_z,
            fg_z=fg_z,
            ft_z=ft_z,
            three_pm_z=three_pm_z,
            reb_z=reb_z,
            ast_z=ast_z,
            stl_z=stl_z,
            blk_z=blk_z,
            dd_z=dd_z,
            pts_z=pts_z,
        )
        session.add(row)


def recompute_season_team_metrics(
    session: Session,
    league_id: int,
    season: int,
) -> None:
    """
    Aggregate WeekTeamStats into SeasonTeamMetrics for a given league+season.

    For now, we only compute:
    - weeks
    - sum_total_z
    - avg_total_z

    We leave expected/actual win%, luck_index, fraud_score as None.
    That can be layered on once we define the correct math.
    """
    # Delete existing rows for this slice
    session.query(SeasonTeamMetrics).filter_by(
        league_id=league_id,
        year=season,
    ).delete(synchronize_session=False)

    # Fetch all week-level rows (excluding any league-average rows)
    rows: List[WeekTeamStats] = (
        session.query(WeekTeamStats)
        .filter_by(league_id=league_id, year=season, is_league_average=False)
        .all()
    )

    if not rows:
        return

    # Group by team_id
    by_team: Dict[int, List[WeekTeamStats]] = defaultdict(list)
    for r in rows:
        by_team[r.team_id].append(r)

    for team_id, team_rows in by_team.items():
        weeks = len(team_rows)
        sum_total_z = sum(r.total_z or 0.0 for r in team_rows)
        avg_total_z = sum_total_z / weeks if weeks > 0 else 0.0

        # Use the most recent team_name we see
        team_name = sorted(team_rows, key=lambda r: (r.year, r.week))[-1].team_name

        season_row = SeasonTeamMetrics(
            league_id=league_id,
            year=season,
            team_id=team_id,
            team_name=team_name,
            weeks=weeks,
            sum_total_z=sum_total_z,
            avg_total_z=avg_total_z,
            actual_win_pct=None,
            expected_win_pct=None,
            luck_index=None,
            fraud_score=None,
            fraud_label=None,
        )
        session.add(season_row)


# ---------- Internal helpers ----------


def _mean_std(values: Iterable[float]) -> Tuple[float, float]:
    vals = list(values)
    if not vals:
        return 0.0, 0.0
    n = len(vals)
    mean = sum(vals) / n
    if n == 1:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in vals) / n  # population std
    std = var ** 0.5
    return mean, std


def _z_score(value: float | None, mean: float, std: float) -> float | None:
    if value is None:
        return None
    if std == 0:
        return 0.0
    return (value - mean) / std