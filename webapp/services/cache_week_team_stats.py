# webapp/services/cache_week_team_stats.py

from __future__ import annotations
from typing import Dict, List
import math

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from db import WeekTeamStats
from webapp.config import LEAGUE_ID
from models_normalized import Team, StatWeekly

CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"]

def _z(series: pd.Series) -> pd.Series:
    std = float(series.std(ddof=0)) if series.size else 0.0
    if std == 0:
        return pd.Series([0.0] * len(series), index=series.index)
    mean = float(series.mean())
    return (series - mean) / std

def rebuild_week_team_stats_cache(
    session: Session,
    league_id: int,
    season: int,
    week: int,
) -> None:
    """
    Build WeekTeamStats (cache table) from normalized StatWeekly for one week.
    Overwrites existing cache rows for that (league_id, season, week).
    """

    # Pull weekly totals + team names
    rows = (
        session.query(StatWeekly, Team)
        .join(Team, Team.id == StatWeekly.team_id)
        .filter(
            StatWeekly.league_id == league_id,
            StatWeekly.season == season,
            StatWeekly.week == week,
        )
        .all()
    )

    if not rows:
        # Nothing ingested for that week
        return

    data: List[Dict] = []
    for w, t in rows:
        data.append(
            {
                "team_id": t.espn_team_id,     # IMPORTANT: cache uses ESPN team_id
                "team_name": t.name,
                "FG%": float(w.fg_pct) if w.fg_pct is not None else 0.0,
                "FT%": float(w.ft_pct) if w.ft_pct is not None else 0.0,
                "3PM": float(w.tpm or 0),
                "REB": float(w.reb or 0),
                "AST": float(w.ast or 0),
                "STL": float(w.stl or 0),
                "BLK": float(w.blk or 0),
                "DD":  float(w.dd or 0),
                "PTS": float(w.pts or 0),
            }
        )

    df = pd.DataFrame(data)

    # League average row (raw stats)
    avg_row = {"team_id": 0, "team_name": "League Average"}
    for c in CATEGORIES:
        avg_row[c] = float(df[c].mean()) if len(df) else 0.0
    df = pd.concat([df, pd.DataFrame([avg_row])], ignore_index=True)

    # Z-scores (per category)
    for c in CATEGORIES:
        df[f"{c}_z"] = _z(df[c])

    df["total_z"] = df[[f"{c}_z" for c in CATEGORIES]].sum(axis=1)

    # wipe old cache rows for this week
    session.query(WeekTeamStats).filter(
        WeekTeamStats.league_id == league_id,
        WeekTeamStats.year == season,
        WeekTeamStats.week == week,
    ).delete(synchronize_session=False)

    # write cache rows
    for _, r in df.iterrows():
        team_id = int(r["team_id"])
        rec = WeekTeamStats(
            league_id=league_id,
            year=season,
            week=week,
            team_id=team_id,
            team_name=str(r["team_name"]),
            is_league_average=(team_id == 0),
            total_z=float(r["total_z"]),
            fg_z=float(r["FG%_z"]),
            ft_z=float(r["FT%_z"]),
            three_pm_z=float(r["3PM_z"]),
            reb_z=float(r["REB_z"]),
            ast_z=float(r["AST_z"]),
            stl_z=float(r["STL_z"]),
            blk_z=float(r["BLK_z"]),
            dd_z=float(r["DD_z"]),
            pts_z=float(r["PTS_z"]),
        )
        session.add(rec)