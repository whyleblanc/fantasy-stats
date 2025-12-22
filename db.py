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

DB_URL = "sqlite:///fantasy_stats.db"

engine = create_engine(DB_URL, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


class WeekTeamStats(Base):
    __tablename__ = "week_team_stats"
    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, index=True)
    year = Column(Integer, index=True)
    week = Column(Integer, index=True)
    team_id = Column(Integer, index=True)
    team_name = Column(String)
    is_league_average = Column(Boolean, default=False)
    result = Column(String, nullable=True)
    total_z = Column(Float)
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
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("league_id", "year", "week", "team_id", name="uix_league_year_week_team"),
    )


class SeasonTeamMetrics(Base):
    __tablename__ = "season_team_metrics"

    id = Column(Integer, primary_key=True)
    league_id = Column(Integer, index=True)
    year = Column(Integer, index=True)
    team_id = Column(Integer, index=True)
    team_name = Column(String)
    weeks = Column(Integer)
    sum_total_z = Column(Float)
    avg_total_z = Column(Float)
    actual_win_pct = Column(Float)
    expected_win_pct = Column(Float)
    luck_index = Column(Float)
    fraud_score = Column(Float)
    fraud_label = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("league_id", "year", "team_id", name="uix_league_year_team"),
    )

        # db.py
    # ...
    # Ensure aggregate models are registered with Base metadata
    try:
        import models_aggregates  # noqa: F401
    except Exception:
        pass

def init_db():
    Base.metadata.create_all(bind=engine)