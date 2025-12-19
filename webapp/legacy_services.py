# webapp/legacy_services.py

"""
Legacy service helpers that talk directly to ESPN via analysis.get_league.

This module is intentionally separate from the new ingestion/analytics engine:

- Used by:
    - /api/league (basic league + team metadata)
    - meta + analysis routes that still depend on live ESPN objects
- Returns simple dicts / primitives consumed by the existing frontend.

Over time, pieces of this should be migrated to DB-backed equivalents.
"""

from functools import lru_cache
from typing import Dict, List, Tuple, Any

from analysis import get_league  # ESPN wrapper
from .config import LEAGUE_ID


def derive_current_week(league) -> Tuple[int, int]:
    """
    Derive the current matchup week with reasonable fallbacks.
    Returns (current_week, max_week).

    This ONLY uses the live ESPN League object; it does not touch the DB.
    """

    # Max week: prefer explicit settings, fall back to 22 if ESPN is weird.
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

    # Try the obvious "current week" attributes first.
    current_week = None
    for attr in ("current_week", "currentMatchupPeriod", "currentWeek"):
        cw = getattr(league, attr, None)
        if isinstance(cw, int) and 1 <= cw <= max_week:
            current_week = cw
            break

    # Fallback: probe scoreboards to find last non-empty week.
    if current_week is None:
        current_week = 1
        try:
            for w in range(1, max_week + 1):
                sb = league.scoreboard(w)
                if not sb:
                    # first empty, so previous week was last active
                    current_week = max(1, w - 1)
                    break
            else:
                # all weeks non-empty
                current_week = max_week
        except Exception:
            # if scoreboard blows up, just assume season complete
            current_week = max_week

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


@lru_cache(maxsize=64)
def build_owners_map(year: int) -> Dict[int, str]:
    """
    Return {team_id: ownerString} for a given year.

    NOTE:
    - team_id here is ESPN's team_id (matches what the frontend / WeekTeamStats uses).
    - This is still ESPN-backed; the DB will eventually become the primary source.
    """
    league = get_league(year)
    return {t.team_id: format_owners(t) for t in league.teams}


@lru_cache(maxsize=32)
def build_league_payload(year: int) -> Dict[str, Any]:
    """
    Return a dict with league + team data for a given year.

    Shape is preserved for the existing frontend:

        {
            "leagueId": int,
            "leagueName": str,
            "year": int,
            "teamCount": int,
            "currentWeek": int,
            "teams": [
                {
                    "teamId": int,
                    "teamName": str,
                    "owners": str,
                    "wins": int,
                    "losses": int,
                    "ties": int,
                    "pointsFor": float,
                    "pointsAgainst": float,
                    "finalStanding": int | None,
                },
                ...
            ],
        }

    This is **read-only** and still hits ESPN. Writing / heavy analytics
    now flow through the new ingestion + analytics engine.
    """
    league = get_league(year)
    current_week, _ = derive_current_week(league)

    teams: List[Dict[str, Any]] = []
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

    # If final standings are available, sort by them (1 = champion, etc.).
    if any(team["finalStanding"] for team in teams):
        teams.sort(
            key=lambda x: x["finalStanding"]
            if x["finalStanding"] is not None
            else 999
        )

    payload: Dict[str, Any] = {
        "leagueId": LEAGUE_ID,
        "leagueName": league.settings.name,
        "year": year,
        "teamCount": len(teams),
        "currentWeek": current_week,
        "teams": teams,
    }
    return payload


@lru_cache(maxsize=64)
def get_available_weeks(year: int) -> List[int]:
    """
    Ask ESPN which matchup weeks exist for this season.

    We call league.scoreboard(week) until it returns empty or errors.
    Cached per (year) to avoid hammering ESPN from the frontend.
    """
    weeks: List[int] = []
    try:
        league = get_league(year)
    except Exception:
        return weeks

    for w in range(1, 30):
        try:
            scoreboard = league.scoreboard(w)
        except Exception:
            break

        if not scoreboard:
            break

        weeks.append(w)

    return weeks