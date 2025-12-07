from analysis import (
    get_league,
    get_week_zscores_cached,
    get_season_zscores_cached,
    get_team_history_cached,
    get_week_power_cached,
    get_season_power_cached,
)
from db import init_db

from flask import Flask, render_template_string, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from functools import lru_cache
import os
import copy

# Load secrets from .env
load_dotenv()

# Init DB (SQLAlchemy)
init_db()

app = Flask(__name__)
CORS(app)  # allow cross-origin calls from React

# Basic config
LEAGUE_ID = int(os.getenv("LEAGUE_ID"))
SWID = os.getenv("SWID")
ESPN_S2 = os.getenv("ESPN_S2")

# Adjust these as your league history grows
MIN_YEAR = 2014
MAX_YEAR = 2026  # allow up to 2026 in UI/API


# ---------- Helper functions ----------
def derive_current_week(league) -> int:
    """
    Derive the current matchup week with reasonable fallbacks.
    Uses the same logic you already have in /api/meta.
    """
    # --- derive max weeks for this year ---
    try:
        max_week = (
            getattr(league.settings, "matchup_period_count", None)
            or getattr(
                league.settings,
                "regular_season_matchup_period_count",
                None,
            )
            or 22
        )
    except Exception:
        max_week = 22

    # --- derive current matchup week, with fallbacks ---
    current_week = None
    for attr in ("current_week", "currentMatchupPeriod", "currentWeek"):
        cw = getattr(league, attr, None)
        if isinstance(cw, int) and 1 <= cw <= max_week:
            current_week = cw
            break

    if current_week is None:
        # Fallback: find last completed / non-empty scoreboard week
        current_week = 1
        try:
            for w in range(1, max_week + 1):
                sb = league.scoreboard(w)
                if not sb:  # empty / future week
                    current_week = max(1, w - 1)
                    break
            else:
                # all weeks have data
                current_week = max_week
        except Exception:
            # if ESPN explodes, just use max_week
            current_week = max_week

    # Clamp just in case
    if current_week < 1:
        current_week = 1
    if current_week > max_week:
        current_week = max_week

    return current_week, max_week

def format_owners(team) -> str:
    """Safely format owners from whatever espn_api gives us."""
    owners_raw = getattr(team, "owners", None)

    if owners_raw is None:
        return "Unknown"

    if isinstance(owners_raw, str):
        return owners_raw

    if isinstance(owners_raw, list):
        formatted = []
        for o in owners_raw:
            if isinstance(o, dict):
                name = (
                    o.get("owner")
                    or o.get("nickname")
                    or o.get("firstName")
                    or o.get("lastName")
                    or None
                )
                formatted.append(name if name is not None else str(o))
            else:
                formatted.append(str(o))
        return ", ".join(formatted)

    return str(owners_raw)

def build_owners_map(year: int) -> dict:
    """Return {team_id: ownerString} for a given year."""
    league = get_league(year)
    return {t.team_id: format_owners(t) for t in league.teams}
    
def build_league_payload(year: int) -> dict:
    """Return a dict with league + team data for a given year."""
    league = get_league(year)

    # Get currentWeek for this league/year
    current_week, _ = derive_current_week(league)

    teams = []
    for t in league.teams:
        teams.append(
            {
                "teamId": t.team_id,
                "teamName": t.team_name,
                "owners": format_owners(t),
                "wins": t.wins,
                "losses": t.losses,
                "ties": t.ties,
                "pointsFor": t.points_for,
                "pointsAgainst": t.points_against,
                "finalStanding": getattr(t, "final_standing", None),
            }
        )

    # Sort by finalStanding if present
    if any(team["finalStanding"] for team in teams):
        teams.sort(
            key=lambda x: x["finalStanding"]
            if x["finalStanding"] is not None
            else 999
        )

    payload = {
        "leagueId": LEAGUE_ID,
        "leagueName": league.settings.name,
        "year": year,
        "teamCount": len(teams),
        "currentWeek": current_week,
        "teams": teams,
    }
    return payload


@lru_cache(maxsize=64)
def get_available_weeks(year: int) -> list[int]:
    """
    Ask ESPN which matchup weeks exist for this season.
    We call league.scoreboard(week) until it returns empty or errors.
    """
    weeks: list[int] = []
    try:
        league = get_league(year)
    except Exception:
        return weeks

    # Basketball seasons rarely exceed 25 weeks – 30 is a safe cap
    for w in range(1, 30):
        try:
            scoreboard = league.scoreboard(w)
        except Exception:
            break

        # If ESPN returns no matchups, we've gone past the last valid week
        if not scoreboard:
            break

        weeks.append(w)

    return weeks


# ---------- Meta / health ----------

@app.route("/health")
def health():
    """Simple healthcheck endpoint (legacy)."""
    return jsonify({"status": "ok"})


@app.route("/api/health")
def api_health():
    """Simple healthcheck endpoint for frontend."""
    return jsonify({"status": "ok"})


@app.route("/api/meta")
def meta_api():
    """
    Return selectable options + live context for frontend dropdowns:
      GET /api/meta
      GET /api/meta?year=2025

    Response:
    {
      "years": [2019, 2020, ..., 2025],
      "year": 2025,
      "weeks": [1, 2, ..., max_week],
      "currentWeek": 12,
      "leagueName": "My League",
      "teamCount": 12
    }
    """
    try:
        # Requested year (or default to MAX_YEAR)
        year = request.args.get("year", default=MAX_YEAR, type=int)
        if year < MIN_YEAR:
            year = MIN_YEAR
        if year > MAX_YEAR:
            year = MAX_YEAR

        league = get_league(year)

        # Use helper to figure out currentWeek + maxWeek
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

# ---------- Core league info ----------

@app.route("/api/league")
def league_api():
    """
    JSON API endpoint:
    GET /api/league?year=2025
    """
    year = request.args.get("year", default=2025, type=int)

    # Clamp year into allowed range
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


# ---------- Analysis: season + week z-scores / history / power ----------

@app.route("/api/analysis/season-zscores")
def season_zscores_api():
    """
    GET /api/analysis/season-zscores?year=2025[&refresh=1]
    """
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


@app.route("/api/analysis/team-history")
def team_history_api():
    """
    GET /api/analysis/team-history?year=2025&teamId=3[&refresh=1]
    """
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


@app.route("/api/analysis/week-zscores")
def week_zscores_api():
    """
    GET /api/analysis/week-zscores?year=2025&week=7[&refresh=1]
    """
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


@app.route("/api/analysis/week-power")
def week_power_api():
    """
    GET /api/analysis/week-power?year=2025&week=1[&refresh=1]
    """
    year = request.args.get("year", default=2025, type=int)
    week = request.args.get("week", default=1, type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    try:
        # If you want to be extra safe about mutating cached data:
        # raw = get_week_power_cached(year, week, force_refresh=refresh)
        # payload = copy.deepcopy(raw)
        payload = get_week_power_cached(year, week, force_refresh=refresh)

        # attach owners
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


@app.route("/api/analysis/season-power")
def season_power_api():
    """
    GET /api/analysis/season-power?year=2025[&refresh=1]
    """
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


# ---------- Debug endpoints ----------

@app.route("/api/debug/week-raw")
def debug_week_raw():
    """
    Debug endpoint to inspect the raw home_stats / away_stats from ESPN.
    Example:
      GET /api/debug/week-raw?year=2025&week=1
    """
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


@app.route("/api/debug/week-cats")
def debug_week_cats():
    """
    Debug endpoint to inspect category-based stats on a matchup.
    Example:
      GET /api/debug/week-cats?year=2025&week=1
    """
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

    matchup = scoreboard[0]  # just inspect the first one to keep it small

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


# ---------- Basic HTML index (legacy, still useful) ----------

@app.route("/")
def index():
    # HTML view, still useful for quick human browsing
    year = request.args.get("year", default=2025, type=int)

    if year < MIN_YEAR:
        year = MIN_YEAR
    if year > MAX_YEAR:
        year = MAX_YEAR

    try:
        payload = build_league_payload(year)
    except Exception:
        error_template = """
        <!doctype html>
        <html>
        <head>
            <title>League not available</title>
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <style>
                body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; }
                .card { max-width: 600px; margin: 40px auto; padding: 20px; border: 1px solid #ddd; border-radius: 8px; }
                h1 { margin-top: 0; }
                a { color: #0b6dfc; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Season {{ year }} not available</h1>
                <p>ESPN isn’t returning data for this season yet (or the league doesn’t exist for {{ year }}).</p>
                <p>Try another year between {{ min_year }} and {{ max_year }}.</p>
                <p><a href="/?year={{ fallback_year }}">Go to {{ fallback_year }}</a></p>
            </div>
        </body>
        </html>
        """
        return render_template_string(
            error_template,
            year=year,
            min_year=MIN_YEAR,
            max_year=MAX_YEAR,
            fallback_year=MAX_YEAR - 1,
        )

    teams = payload["teams"]

    template = """
    <!doctype html>
    <html>
    <head>
        <title>{{ league_name }} ({{ year }})</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; }
            h1 { margin-bottom: 0.2rem; }
            .subtitle { color: #666; margin-bottom: 1rem; }
            table { border-collapse: collapse; width: 100%; max-width: 900px; }
            th, td { padding: 8px 10px; border-bottom: 1px solid #ddd; text-align: left; }
            th { background: #f5f5f5; position: sticky; top: 0; }
            tr:hover { background: #fafafa; }
            .year-form { margin-bottom: 1rem; }
            input[type="number"] { padding: 4px 6px; width: 120px; }
            button { padding: 4px 10px; cursor: pointer; }
            .footnote { margin-top: 1rem; font-size: 0.85rem; color: #777; }
            .api-link { margin-top: 0.5rem; font-size: 0.85rem; }
            .api-link a { color: #0b6dfc; text-decoration: none; }
            .api-link a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>{{ league_name }}</h1>
        <div class="subtitle">Season {{ year }} · {{ team_count }} teams</div>

        <form class="year-form" method="get">
            <label for="year">Jump to year ({{ min_year }}–{{ max_year }}):</label>
            <input type="number" id="year" name="year" value="{{ year }}" min="{{ min_year }}" max="{{ max_year }}">
            <button type="submit">Go</button>
        </form>

        <div class="api-link">
            API for this view:
            <a href="/api/league?year={{ year }}">/api/league?year={{ year }}</a>
        </div>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Team</th>
                    <th>Owner(s)</th>
                    <th>Record</th>
                    <th>PF</th>
                    <th>PA</th>
                    <th>Final Rank</th>
                </tr>
            </thead>
            <tbody>
                {% for t in teams %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ t.teamName }}</td>
                    <td>{{ t.owners }}</td>
                    <td>{{ t.wins }}–{{ t.losses }}{% if t.ties %}–{{ t.ties }}{% endif %}</td>
                    <td>{{ "%.1f"|format(t.pointsFor) }}</td>
                    <td>{{ "%.1f"|format(t.pointsAgainst) }}</td>
                    <td>{% if t.finalStanding %}{{ t.finalStanding }}{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="footnote">
            Live seasons (like {{ max_year }}) will always reflect stats only up to the current matchup week from ESPN.
        </div>
    </body>
    </html>
    """

    return render_template_string(
        template,
        league_name=payload["leagueName"],
        year=payload["year"],
        teams=teams,
        team_count=payload["teamCount"],
        min_year=MIN_YEAR,
        max_year=MAX_YEAR,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)