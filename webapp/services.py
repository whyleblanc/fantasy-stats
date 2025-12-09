# webapp/services.py

from functools import lru_cache
from typing import Dict, List, Tuple, Any

from analysis import get_league  # your existing ESPN wrapper
from .config import LEAGUE_ID, MIN_YEAR, MAX_YEAR


def derive_current_week(league) -> Tuple[int, int]:
    """
    Derive the current matchup week with reasonable fallbacks.
    Returns (current_week, max_week).
    """

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

    current_week = None
    for attr in ("current_week", "currentMatchupPeriod", "currentWeek"):
        cw = getattr(league, attr, None)
        if isinstance(cw, int) and 1 <= cw <= max_week:
            current_week = cw
            break

    if current_week is None:
        current_week = 1
        try:
            for w in range(1, max_week + 1):
                sb = league.scoreboard(w)
                if not sb:
                    current_week = max(1, w - 1)
                    break
            else:
                current_week = max_week
        except Exception:
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


def build_owners_map(year: int) -> Dict[int, str]:
    """Return {team_id: ownerString} for a given year."""
    league = get_league(year)
    return {t.team_id: format_owners(t) for t in league.teams}


def build_league_payload(year: int) -> Dict[str, Any]:
    """Return a dict with league + team data for a given year."""
    league = get_league(year)
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
def get_available_weeks(year: int) -> List[int]:
    """
    Ask ESPN which matchup weeks exist for this season.
    We call league.scoreboard(week) until it returns empty or errors.
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