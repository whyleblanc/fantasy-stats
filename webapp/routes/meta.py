# webapp/routes/meta.py

from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy import or_

from webapp.config import MIN_YEAR, MAX_YEAR, LEAGUE_ID
from db import SessionLocal, WeekTeamStats
from models_normalized import Matchup, StatWeekly, Team

meta_bp = Blueprint("meta", __name__, url_prefix="/api/meta")

def _weeks_with_data_from_statweekly(session, year: int) -> List[int]:
    rows = (
        session.query(StatWeekly.week)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season == year,
            or_(
                StatWeekly.pts > 0,
                StatWeekly.fga > 0,
                StatWeekly.fta > 0,
                StatWeekly.tpm > 0,
                StatWeekly.reb > 0,
                StatWeekly.ast > 0,
                StatWeekly.stl > 0,
                StatWeekly.blk > 0,
                StatWeekly.dd > 0,
            ),
        )
        .distinct()
        .order_by(StatWeekly.week)
        .all()
    )
    return [w[0] for w in rows if w[0] is not None]


def _weeks_completed_from_matchups(session, year: int) -> List[int]:
    rows = (
        session.query(Matchup.week)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == year,
            Matchup.winner_team_id.isnot(None),
        )
        .distinct()
        .order_by(Matchup.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _weeks_from_weekteamstats(session, year: int) -> List[int]:
    rows = (
        session.query(WeekTeamStats.week)
        .filter_by(
            league_id=LEAGUE_ID,
            year=year,
            is_league_average=False,
        )
        .distinct()
        .order_by(WeekTeamStats.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _weeks_from_statweekly(session, year: int) -> List[int]:
    rows = (
        session.query(StatWeekly.week)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season == year,
        )
        .distinct()
        .order_by(StatWeekly.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _weeks_from_matchups(session, year: int) -> List[int]:
    rows = (
        session.query(Matchup.week)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == year,
        )
        .distinct()
        .order_by(Matchup.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _db_year_bounds(session) -> Tuple[int, int]:
    """
    Prefer WeekTeamStats years, then StatWeekly, then Matchup.
    Falls back to config MIN_YEAR/MAX_YEAR if DB empty.
    """
    # 1) WeekTeamStats
    mn, mx = (
        session.query(func.min(WeekTeamStats.year), func.max(WeekTeamStats.year))
        .filter(WeekTeamStats.league_id == LEAGUE_ID, WeekTeamStats.is_league_average == False)
        .one()
    )
    if mn is not None and mx is not None:
        return int(mn), int(mx)

    # 2) StatWeekly
    mn, mx = (
        session.query(func.min(StatWeekly.season), func.max(StatWeekly.season))
        .filter(StatWeekly.league_id == LEAGUE_ID)
        .one()
    )
    if mn is not None and mx is not None:
        return int(mn), int(mx)

    # 3) Matchup
    mn, mx = (
        session.query(func.min(Matchup.season), func.max(Matchup.season))
        .filter(Matchup.league_id == LEAGUE_ID)
        .one()
    )
    if mn is not None and mx is not None:
        return int(mn), int(mx)

    return int(MIN_YEAR), int(MAX_YEAR)


def _meta_db_first(year: int) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        # capability source (weekteamstats > statweekly > matchups)
        weeks = _weeks_from_weekteamstats(session, year)
        source = "db_weekteamstats"

        if not weeks:
            weeks = _weeks_from_statweekly(session, year)
            source = "db_statweekly"

        if not weeks:
            weeks = _weeks_from_matchups(session, year)
            source = "db_matchups"

        weeks = [int(w) for w in weeks]

        # clamp selectable weeks for latest season only
        db_min_year, db_max_year = _db_year_bounds(session)
        if year == db_max_year:
            completed = _weeks_completed_from_matchups(session, year)
            if completed:
                weeks = sorted(set(weeks) & set(completed))

        current_week: Optional[int] = max(weeks) if weeks else None

        team_count = (
            session.query(Team)
            .filter(
                Team.league_id == LEAGUE_ID,
                Team.season == year,
            )
            .count()
        )

        return {
            "year": int(year),
            "currentWeek": int(current_week) if current_week is not None else None,
            "maxWeek": int(current_week) if current_week is not None else None,
            "availableWeeks": weeks,
            "teamCount": int(team_count),
            "source": source,
            "advancedStatsAvailable": source == "db_weekteamstats",
            "weeklyStatsAvailable": source in ("db_weekteamstats", "db_statweekly"),
        }
    finally:
        session.close()


@meta_bp.route("", methods=["GET"])
def meta_api():
    session = SessionLocal()
    try:
        db_min_year, db_max_year = _db_year_bounds(session)
    finally:
        session.close()

    # Default to latest year present in DB
    year = request.args.get("year", default=db_max_year, type=int)

    # Clamp to DB bounds (NOT config bounds)
    year = max(db_min_year, min(db_max_year, year))

    payload = _meta_db_first(year)
    payload["minYear"] = db_min_year
    payload["maxYear"] = db_max_year

    return jsonify(payload)