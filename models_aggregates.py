# models_aggregates.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime, UniqueConstraint, Index
from db import Base
from webapp.config import LEAGUE_ID

class TeamHistoryAgg(Base):
    """
    Precomputed team history rows (one row per team per week).
    This mirrors what the Team History UI needs, but stored in DB.
    """
    __tablename__ = "team_history_agg"

    id = Column(Integer, primary_key=True)

    league_id = Column(Integer, index=True, nullable=False)
    year = Column(Integer, index=True, nullable=False)
    week = Column(Integer, index=True, nullable=False)

    # ESPN team id (NOT internal Team.id). This aligns with your UI usage.
    team_id = Column(Integer, index=True, nullable=False)
    team_name = Column(String, nullable=True)

    # weekly rank (1 = best)
    rank = Column(Integer, nullable=True)

    # weekly total + cumulative
    total_z = Column(Float, nullable=True)
    cumulative_total_z = Column(Float, nullable=True)

    # league averages for that week
    league_average_total_z = Column(Float, nullable=True)

    # category zscores (weekly)
    fg_z = Column(Float, nullable=True)
    ft_z = Column(Float, nullable=True)
    three_pm_z = Column(Float, nullable=True)
    reb_z = Column(Float, nullable=True)
    ast_z = Column(Float, nullable=True)
    stl_z = Column(Float, nullable=True)
    blk_z = Column(Float, nullable=True)
    dd_z = Column(Float, nullable=True)
    pts_z = Column(Float, nullable=True)

    # category league avg zscores (weekly)
    league_fg_z = Column(Float, nullable=True)
    league_ft_z = Column(Float, nullable=True)
    league_three_pm_z = Column(Float, nullable=True)
    league_reb_z = Column(Float, nullable=True)
    league_ast_z = Column(Float, nullable=True)
    league_stl_z = Column(Float, nullable=True)
    league_blk_z = Column(Float, nullable=True)
    league_dd_z = Column(Float, nullable=True)
    league_pts_z = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("league_id", "year", "week", "team_id", name="uix_team_history_agg"),
        Index("ix_team_history_agg_lookup", "league_id", "year", "team_id"),
    )

class OpponentMatrixAggYear(Base):
    __tablename__ = "opponent_matrix_agg_year"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, nullable=False, default=LEAGUE_ID)

    year = Column(Integer, nullable=False)            # season
    team_id = Column(Integer, nullable=False)         # ESPN team id
    opponent_team_id = Column(Integer, nullable=False) # ESPN team id

    opponent_name = Column(String)  # optional convenience snapshot

    # overall matchup record (W/L/T) vs opponent for this year
    matchups = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)

    # --- per-category W/L/T and avgDiff ---
    fg_w = Column(Integer, default=0); fg_l = Column(Integer, default=0); fg_t = Column(Integer, default=0); fg_diff_sum = Column(Float, default=0.0); fg_diff_n = Column(Integer, default=0)
    ft_w = Column(Integer, default=0); ft_l = Column(Integer, default=0); ft_t = Column(Integer, default=0); ft_diff_sum = Column(Float, default=0.0); ft_diff_n = Column(Integer, default=0)
    three_pm_w = Column(Integer, default=0); three_pm_l = Column(Integer, default=0); three_pm_t = Column(Integer, default=0); three_pm_diff_sum = Column(Float, default=0.0); three_pm_diff_n = Column(Integer, default=0)
    reb_w = Column(Integer, default=0); reb_l = Column(Integer, default=0); reb_t = Column(Integer, default=0); reb_diff_sum = Column(Float, default=0.0); reb_diff_n = Column(Integer, default=0)
    ast_w = Column(Integer, default=0); ast_l = Column(Integer, default=0); ast_t = Column(Integer, default=0); ast_diff_sum = Column(Float, default=0.0); ast_diff_n = Column(Integer, default=0)
    stl_w = Column(Integer, default=0); stl_l = Column(Integer, default=0); stl_t = Column(Integer, default=0); stl_diff_sum = Column(Float, default=0.0); stl_diff_n = Column(Integer, default=0)
    blk_w = Column(Integer, default=0); blk_l = Column(Integer, default=0); blk_t = Column(Integer, default=0); blk_diff_sum = Column(Float, default=0.0); blk_diff_n = Column(Integer, default=0)
    dd_w = Column(Integer, default=0); dd_l = Column(Integer, default=0); dd_t = Column(Integer, default=0); dd_diff_sum = Column(Float, default=0.0); dd_diff_n = Column(Integer, default=0)
    pts_w = Column(Integer, default=0); pts_l = Column(Integer, default=0); pts_t = Column(Integer, default=0); pts_diff_sum = Column(Float, default=0.0); pts_diff_n = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("league_id", "year", "team_id", "opponent_team_id", name="uq_opp_matrix_agg_year"),
    )