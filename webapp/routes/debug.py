# webapp/routes/debug.py

from flask import Blueprint, jsonify, request

from analysis import get_league

debug_bp = Blueprint("debug", __name__, url_prefix="/api/debug")


@debug_bp.route("/week-raw")
def debug_week_raw():
    year = request.args.get("year", default=2025, type=int)
    week = request.args.get("week", default=1, type=int)

    try:
        league = get_league(year)
        scoreboard = league.scoreboard(week)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to load scoreboard",
                    "year": year,
                    "week": week,
                    "details": str(e),
                }
            ),
            500,
        )

    payload = []
    for matchup in scoreboard:
        payload.append(
            {
                "homeTeam": matchup.home_team.team_name,
                "awayTeam": matchup.away_team.team_name,
                "homeStatsKeys": list(
                    (getattr(matchup, "home_stats", {}) or {}).keys()
                ),
                "awayStatsKeys": list(
                    (getattr(matchup, "away_stats", {}) or {}).keys()
                ),
                "homeStatsSample": getattr(matchup, "home_stats", {}) or {},
                "awayStatsSample": getattr(matchup, "away_stats", {}) or {},
            }
        )

    return jsonify(
        {
            "year": year,
            "week": week,
            "matchups": payload,
        }
    )


@debug_bp.route("/week-cats")
def debug_week_cats():
    year = request.args.get("year", default=2025, type=int)
    week = request.args.get("week", default=1, type=int)

    try:
        league = get_league(year)
        scoreboard = league.scoreboard(week)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": "Failed to load scoreboard",
                    "year": year,
                    "week": week,
                    "details": str(e),
                }
            ),
            500,
        )

    if not scoreboard:
        return jsonify({"year": year, "week": week, "matchups": []})

    matchup = scoreboard[0]

    attrs = [a for a in dir(matchup) if not a.startswith("_")]
    cat_attrs = [a for a in attrs if "cat" in a.lower() or "stat" in a.lower()]

    payload = {
        "year": year,
        "week": week,
        "homeTeam": matchup.home_team.team_name,
        "awayTeam": matchup.away_team.team_name,
        "attrCandidates": cat_attrs,
        "home_team_cats": getattr(matchup, "home_team_cats", None),
        "away_team_cats": getattr(matchup, "away_team_cats", None),
        "home_cats": getattr(matchup, "home_cats", None),
        "away_cats": getattr(matchup, "away_cats", None),
        "home_stats": getattr(matchup, "home_stats", None),
        "away_stats": getattr(matchup, "away_stats", None),
    }

    return jsonify(payload)