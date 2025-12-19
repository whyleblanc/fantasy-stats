import sqlite3
import pytest

LEAGUE_ID = 70600
DB_PATH = "fantasy_stats.db"


def test_meta_only_exposes_completed_weeks(client):
    """
    Regression guard:
    - Every week exposed by /api/meta must have week_team_stats rows.
    - Prevents half-ingested weeks from appearing in the UI.
    """

    year = 2026
    res = client.get(f"/api/meta?year={year}")
    assert res.status_code == 200

    payload = res.json
    weeks = payload.get("availableWeeks", [])
    assert weeks, "No weeks returned by meta"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for week in weeks:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM week_team_stats
            WHERE league_id = ?
              AND year = ?
              AND week = ?
            """,
            (LEAGUE_ID, year, week),
        )
        count = cur.fetchone()[0]

        assert count > 0, f"Meta exposes week {week} but week_team_stats is empty"

    conn.close()