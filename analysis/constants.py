from typing import List, Dict

# Head-to-head categories you care about (frontend also uses this)
CATEGORIES: List[str] = [
    "FG%",
    "FT%",
    "3PM",
    "REB",
    "AST",
    "STL",
    "BLK",
    "DD",
    "PTS",
]

# Map stat labels -> DB column names for WeekTeamStats
CAT_TO_DB_COL: Dict[str, str] = {
    "FG%": "fg_z",
    "FT%": "ft_z",
    "3PM": "three_pm_z",
    "REB": "reb_z",
    "AST": "ast_z",
    "STL": "stl_z",
    "BLK": "blk_z",
    "DD": "dd_z",
    "PTS": "pts_z",
}

# Playoff start weeks (regular season ends before these)
PLAYOFF_START_WEEKS: Dict[int, int] = {
    2019: 21,
    2020: 21,
    2021: 18,
    2022: 22,
    2023: 19,
    2024: 20,
    2025: 18,  # adjust if needed
    2026: 19,  # placeholder
}