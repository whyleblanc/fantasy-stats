# analysis/__init__.py

from .constants import CATEGORIES, CAT_TO_DB_COL
from .loaders import get_league, LEAGUE_ID
from .services import (
    get_week_power_cached,
    get_season_power_cached,
    get_week_zscores_cached,
    get_season_zscores_cached,
    get_team_history_cached,
    get_opponent_matrix_cached,
    get_opponent_zdiff_matrix_cached,
    get_opponent_matrix_multi_cached,
    reshape_opponent_matrix_for_team,
)

__all__ = [
    # constants
    "CATEGORIES",
    "CAT_TO_DB_COL",

    # loaders
    "get_league",
    "LEAGUE_ID",

    # power + z-score caches
    "get_week_power_cached",
    "get_season_power_cached",
    "get_week_zscores_cached",
    "get_season_zscores_cached",
    "get_team_history_cached",

    # opponent analysis
    "get_opponent_matrix_cached",
    "get_opponent_zdiff_matrix_cached",
    "get_opponent_matrix_multi_cached",
    "reshape_opponent_matrix_for_team",
]