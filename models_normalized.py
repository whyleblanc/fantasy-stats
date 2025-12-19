# models_normalized.py

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from db import Base  # <-- use the existing Base from db.py

class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    espn_player_id = Column(Integer, nullable=False)
    full_name = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    positions = Column(String)  # e.g. "PG,SG"
    pro_team = Column(String)   # e.g. "LAL"
    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("espn_player_id", name="uq_players_espn_player_id"),
    )

    # relationships
    raw_stats = relationship("StatRaw", back_populates="player")


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    espn_team_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    abbrev = Column(String)
    owner = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "season",
            "espn_team_id",
            name="uq_teams_league_season_espn_team_id",
        ),
    )

    # relationships
    raw_stats = relationship("StatRaw", back_populates="team")
    weekly_stats = relationship("StatWeekly", back_populates="team")
    season_stats = relationship("StatSeason", back_populates="team")


class Matchup(Base):
    __tablename__ = "matchups"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    matchup_id = Column(Integer, nullable=False)  # ESPN matchup index / id

    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    winner_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    is_playoffs = Column(Boolean, default=False)
    is_consolation = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "season",
            "week",
            "matchup_id",
            name="uq_matchups_league_season_week_matchup",
        ),
    )

    # relationships (optional; only if you care in ORM)
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    winner_team = relationship("Team", foreign_keys=[winner_team_id])


class StatRaw(Base):
    """
    Per-player per-week raw stats, from ESPN.

    One row per (league, season, week, team, player).
    """
    __tablename__ = "stats_raw"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)

    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)

    games_played = Column(Integer, default=0)

    fgm = Column(Integer, default=0)
    fga = Column(Integer, default=0)
    ftm = Column(Integer, default=0)
    fta = Column(Integer, default=0)
    tpm = Column(Integer, default=0)
    reb = Column(Integer, default=0)
    ast = Column(Integer, default=0)
    stl = Column(Integer, default=0)
    blk = Column(Integer, default=0)
    pts = Column(Integer, default=0)
    dd = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "season",
            "week",
            "team_id",
            "player_id",
            name="uq_stats_raw_player_week",
        ),
    )

    # relationships
    team = relationship("Team", back_populates="raw_stats")
    player = relationship("Player", back_populates="raw_stats")


class StatWeekly(Base):
    """
    Per-team per-week aggregated stats.
    """
    __tablename__ = "stats_weekly"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    games_played = Column(Integer, default=0)

    fgm = Column(Integer, default=0)
    fga = Column(Integer, default=0)
    ftm = Column(Integer, default=0)
    fta = Column(Integer, default=0)
    tpm = Column(Integer, default=0)
    reb = Column(Integer, default=0)
    ast = Column(Integer, default=0)
    stl = Column(Integer, default=0)
    blk = Column(Integer, default=0)
    pts = Column(Integer, default=0)
    dd = Column(Integer, default=0)

    # optional denormalized percentages
    fg_pct = Column(Float)
    ft_pct = Column(Float)

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "season",
            "week",
            "team_id",
            name="uq_stats_weekly_team_week",
        ),
    )

    team = relationship("Team", back_populates="weekly_stats")


class MatchupCategoryResult(Base):
    __tablename__ = "matchup_category_results"

    id = Column(Integer, primary_key=True)

    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    matchup_id = Column(Integer, nullable=False)  # ESPN matchup index/id

    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    opponent_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    category = Column(String, nullable=False)     # "FG%", "FT%", ...
    result = Column(String, nullable=False)       # "W" / "L" / "T"

    # optional: store scores if present in scoreboard cats
    team_score = Column(Float)
    opp_score = Column(Float)

    __table_args__ = (
        UniqueConstraint(
            "league_id","season","week","matchup_id",
            "team_id","category",
            name="uq_matchup_cat_result"
        ),
    )


class StatSeason(Base):
    """
    Per-team per-season aggregated stats.
    """
    __tablename__ = "stats_season"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    games_played = Column(Integer, default=0)

    fgm = Column(Integer, default=0)
    fga = Column(Integer, default=0)
    ftm = Column(Integer, default=0)
    fta = Column(Integer, default=0)
    tpm = Column(Integer, default=0)
    reb = Column(Integer, default=0)
    ast = Column(Integer, default=0)
    stl = Column(Integer, default=0)
    blk = Column(Integer, default=0)
    pts = Column(Integer, default=0)
    dd = Column(Integer, default=0)

    fg_pct = Column(Float)
    ft_pct = Column(Float)

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "season",
            "team_id",
            name="uq_stats_season_team",
        ),
    )

    team = relationship("Team", back_populates="season_stats")