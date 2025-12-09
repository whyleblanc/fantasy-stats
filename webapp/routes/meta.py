# webapp/routes/meta.py

from flask import Blueprint, jsonify, request

from analysis import get_league
from webapp.config import MIN_YEAR, MAX_YEAR
from webapp.services import derive_current_week, get_available_weeks

meta_bp = Blueprint("meta", __name__)


@meta_bp.route("/health")
def health():
    """Legacy healthcheck."""
    return jsonify({"status": "ok"})


@meta_bp.route("/api/health")
def api_health():
    """Healthcheck for frontend."""
    return jsonify({"status": "ok"})


@meta_bp.route("/api/meta")
def meta_api():
    """
    GET /api/meta
    GET /api/meta?year=2025
    """
    try:
        year = request.args.get("year", default=MAX_YEAR, type=int)
        if year < MIN_YEAR:
            year = MIN_YEAR
        if year > MAX_YEAR:
            year = MAX_YEAR

        league = get_league(year)

        current_week, max_week = derive_current_week(league)
        weeks = list(range(1, max_week + 1))

        years = list(range(MIN_YEAR, MAX_YEAR + 1))

        return jsonify(
            {
                "years": years,
                "year": year,
                "weeks": weeks,
                "currentWeek": current_week,
                "leagueName": league.settings.name,
                "teamCount": len(league.teams),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500