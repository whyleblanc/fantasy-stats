# webapp/routes/legacy.py

from flask import Blueprint, render_template_string, request

from webapp.config import MIN_YEAR, MAX_YEAR
from webapp.legacy_services import build_league_payload

legacy_bp = Blueprint("legacy", __name__, url_prefix="/legacy")


@legacy_bp.route("/")
def legacy_index():
    year = request.args.get("year", default=MAX_YEAR, type=int)

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
                <p><a href="/legacy/?year={{ fallback_year }}">Go to {{ fallback_year }}</a></p>
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