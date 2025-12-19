# analysis/owners.py

"""
Ownership metadata for fantasy teams.

We care about:
- current owner code (short label)
- which season that current owner took over for a given team_id

This is used for:
- "current owner era only" filters across multi-year stats
- labeling teams consistently across seasons
"""

from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Current owners (as of 2025)
# ---------------------------------------------------------------------------

# Short codes for the *current* owner of each ESPN team_id.
CURRENT_OWNERS_2025: Dict[int, str] = {
    1: "MATTEO",   # MATTEO
    2: "ALE",      # ALE
    3: "WILL",     # WILL
    4: "YANNICK",  # YANNICK
    5: "MARION",   # MARION
    6: "JORDAN",   # JORDAN
    7: "JULES",    # JULES
    8: "CALT",     # CALT
    9: "RYAN",     # RYAN
    10: "ADDIE",   # ADDIE
    11: "THOMAS",  # THOMAS
    12: "RAMZI",   # RAMZI
}

# Season in which the *current* owner took over each team_id.
# Anything before this year is considered a *previous* owner.
OWNER_START_YEAR: Dict[int, int] = {
    1: 2014,
    2: 2016,
    3: 2014,
    4: 2014,
    5: 2023,
    6: 2016,
    7: 2020,
    8: 2014,
    9: 2015,
    10: 2017,
    11: 2023,
    12: 2018,
}


def _normalize_team_id(team_id: int) -> int:
    """Small helper so we can safely call with ints or strings."""
    return int(team_id)


# ---------------------------------------------------------------------------
# Simple helpers used by opponent-analysis code
# ---------------------------------------------------------------------------

def get_current_owner_code(team_id: int) -> Optional[str]:
    """
    Short owner code for the *current* owner of this team_id.

    This is "global" (doesn't depend on year) and matches the 2025 owners.
    """
    return CURRENT_OWNERS_2025.get(_normalize_team_id(team_id))


def get_owner_start_year(team_id: int) -> Optional[int]:
    """Season when the *current* owner started controlling this team_id."""
    return OWNER_START_YEAR.get(_normalize_team_id(team_id))


def is_within_current_owner_era(team_id: int, year: int) -> bool:
    """
    True if this (team_id, year) should be counted for the *current* owner.

    - If we know their start year: only years >= start_year count.
    - If we don't know: return False so we don't silently misattribute.
    """
    start = OWNER_START_YEAR.get(_normalize_team_id(team_id))
    if start is None:
        return False
    return int(year) >= start


# ---------------------------------------------------------------------------
# Main hook used by the Flask analysis routes
# ---------------------------------------------------------------------------

def build_owners_map(year: int) -> Dict[int, str]:
    """
    Build {team_id: owner_code} for a given season.

    Rules:
      - We only label teams for seasons >= OWNER_START_YEAR[team_id].
      - Earlier seasons (before the current owner took over) get no owner
        label so we don't misattribute historical results.
      - When an owner changes in the future, just update:
          - CURRENT_OWNERS_2025  (or rename to CURRENT_OWNERS_20XX)
          - OWNER_START_YEAR
        and the mapping will stay correct for all seasons.

    This function is consumed by the DB-backed analysis endpoints
    (week-power, season-power, week-zscores, season-zscores) via
    webapp.routes.analysis._attach_owners_to_payload.
    """
    season = int(year)
    result: Dict[int, str] = {}

    for team_id, start_year in OWNER_START_YEAR.items():
        if season >= int(start_year):
            code = CURRENT_OWNERS_2025.get(team_id)
            if code:
                result[team_id] = code

    return result