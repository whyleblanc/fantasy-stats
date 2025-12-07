# db.py
from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    Float,
    String,
    Boolean,
    UniqueConstraint,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite DB in project root
DB_URL = "sqlite:///fantasy_stats.db"

engine = create_engine(DB_URL, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


class WeekTeamStats(Base):
    """
    One row per team, per week, per league, per year.
    Stores z-scores and total power for that matchup period.
    """
    __tablename__ = "week_team_stats"

    id = Column(Integer, primary_key=True)

    league_id = Column(Integer, index=True)
    year = Column(Integer, index=True)
    week = Column(Integer, index=True)

    team_id = Column(Integer, index=True)
    team_name = Column(String)
    is_league_average = Column(Boolean, default=False)

    # WIN / LOSS / TIE / None
    result = Column(String, nullable=True)

    # total z-score across all 9 cats
    total_z = Column(Float)

    # per-category z-scores
    fg_z = Column(Float, nullable=True)
    ft_z = Column(Float, nullable=True)
    three_pm_z = Column(Float, nullable=True)
    reb_z = Column(Float, nullable=True)
    ast_z = Column(Float, nullable=True)
    stl_z = Column(Float, nullable=True)
    blk_z = Column(Float, nullable=True)
    dd_z = Column(Float, nullable=True)
    pts_z = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "year",
            "week",
            "team_id",
            name="uix_league_year_week_team",
        ),
    )


class SeasonTeamMetrics(Base):
    """
    Aggregated season-level metrics fed by WeekTeamStats.
    One row per team per season.
    """
    __tablename__ = "season_team_metrics"

    id = Column(Integer, primary_key=True)

    league_id = Column(Integer, index=True)
    year = Column(Integer, index=True)

    team_id = Column(Integer, index=True)
    team_name = Column(String)

    weeks = Column(Integer)        # weeks with data
    sum_total_z = Column(Float)    # sum of weekly total_z
    avg_total_z = Column(Float)    # average weekly total_z

    actual_win_pct = Column(Float)     # actual wins / weeks
    expected_win_pct = Column(Float)   # expected wins / weeks
    luck_index = Column(Float)         # actual - expected
    fraud_score = Column(Float)        # expected - actual
    fraud_label = Column(String)       # "Fraud", "Juggernaut", etc.

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "year",
            "team_id",
            name="uix_league_year_team",
        ),
    )


def init_db():
    """
    Create all tables if they don't exist.
    Call this once on app startup.
    """
    Base.metadata.create_all(bind=engine)