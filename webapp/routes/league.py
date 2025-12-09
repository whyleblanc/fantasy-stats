# webapp/routes/league.py

from flask import Blueprint, jsonify, render_template_string, request

from webapp.config import MIN_YEAR, MAX_YEAR
from webapp.services import build_league_payload

league_bp = Blueprint("league", __name__)


@league_bp.route("/api/league")
def league_api():
    """
    GET /api/league?year=2025
    """
    year = request.args.get("year", default=MAX_YEAR, type=int)

    if year < MIN_YEAR:
        year = MIN_YEAR
    if year > MAX_YEAR:
        year = MAX_YEAR

    try:
        payload = build_league_payload(year)
        return jsonify(payload)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "League data not available for this year",
                    "year": year,
                    "details": str(e),
                }
            ),
            404,
        )