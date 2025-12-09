# webapp/routes/analysis.py

from flask import Blueprint, jsonify, request

from analysis import (
    get_week_zscores_cached,
    get_season_zscores_cached,
    get_team_history_cached,
    get_week_power_cached,
    get_season_power_cached,
)
from webapp.services import build_owners_map

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/analysis")


@analysis_bp.route("/season-zscores")
def season_zscores_api():
    year = request.args.get("year", default=2025, type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    try:
        payload = get_season_zscores_cached(year, force_refresh=refresh)
        return jsonify(payload)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to compute season z-scores",
                    "year": year,
                    "details": str(e),
                }
            ),
            500,
        )


@analysis_bp.route("/team-history")
def team_history_api():
    year = request.args.get("year", default=2025, type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    if team_id is None:
        return (
            jsonify(
                {
                    "error": "Missing required parameter 'teamId'",
                    "year": year,
                }
            ),
            400,
        )

    try:
        payload = get_team_history_cached(year, team_id, force_refresh=refresh)
        return jsonify(payload)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to compute team history",
                    "year": year,
                    "teamId": team_id,
                    "details": str(e),
                }
            ),
            500,
        )


@analysis_bp.route("/week-zscores")
def week_zscores_api():
    year = request.args.get("year", default=2025, type=int)
    week = request.args.get("week", default=1, type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    try:
        payload = get_week_zscores_cached(year, week, force_refresh=refresh)
        return jsonify(payload)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to compute weekly z-scores",
                    "year": year,
                    "week": week,
                    "details": str(e),
                }
            ),
            500,
        )


@analysis_bp.route("/week-power")
def week_power_api():
    year = request.args.get("year", default=2025, type=int)
    week = request.args.get("week", default=1, type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    try:
        payload = get_week_power_cached(year, week, force_refresh=refresh)

        try:
            owners_map = build_owners_map(year)
        except Exception:
            owners_map = {}

        for t in payload.get("teams", []):
            tid = t.get("teamId")
            if tid and tid != 0:
                t["owners"] = owners_map.get(tid)

        return jsonify(payload)

    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to compute weekly power",
                    "year": year,
                    "week": week,
                    "details": str(e),
                }
            ),
            500,
        )


@analysis_bp.route("/season-power")
def season_power_api():
    year = request.args.get("year", default=2025, type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    try:
        payload = get_season_power_cached(year, force_refresh=refresh)

        try:
            owners_map = build_owners_map(year)
        except Exception:
            owners_map = {}

        for t in payload.get("teams", []):
            tid = t.get("teamId")
            if tid and tid != 0:
                t["owners"] = owners_map.get(tid)

        return jsonify(payload)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to compute season power",
                    "year": year,
                    "details": str(e),
                }
            ),
            500,
        )