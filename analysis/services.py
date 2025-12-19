from __future__ import annotations

from functools import lru_cache
from typing import List, Dict, Tuple, Any
import math

import numpy as np
import pandas as pd
from espn_api.basketball import League  # only for type hints

from db import SessionLocal, WeekTeamStats
from .constants import CATEGORIES, CAT_TO_DB_COL, PLAYOFF_START_WEEKS
from .loaders import get_league, LEAGUE_ID
from .owners import is_within_current_owner_era  # currently unused in DB impl


# ---- Simple in-process caches for heavy computations ----

_WEEK_POWER_CACHE: Dict[Tuple[int, int], Any] = {}
_SEASON_POWER_CACHE: Dict[int, Any] = {}
_WEEK_ZS_CACHE: Dict[Tuple[int, int], Any] = {}
_SEASON_ZS_CACHE: Dict[int, Any] = {}
_TEAM_HISTORY_CACHE: Dict[Tuple[int, int], Any] = {}

_OPPONENT_MATRIX_CACHE: Dict[int, Any] = {}
_OPPONENT_ZDIFF_CACHE: Dict[int, Any] = {}
_OPPONENT_MATRIX_MULTI_CACHE: Dict[Tuple[int, int, bool], Any] = {}


# ---------------------------------------------------------
# Public cached wrappers (these are imported by analysis/__init__.py)
# ---------------------------------------------------------

def get_week_power_cached(year: int, week: int, force_refresh: bool = False) -> dict:
    key = (int(year), int(week))
    if force_refresh or key not in _WEEK_POWER_CACHE:
        _WEEK_POWER_CACHE[key] = compute_week_power_for_api(year, week, force_refresh=force_refresh)
    return _WEEK_POWER_CACHE[key]


def get_season_power_cached(year: int, force_refresh: bool = False) -> dict:
    year = int(year)
    if force_refresh or year not in _SEASON_POWER_CACHE:
        _SEASON_POWER_CACHE[year] = compute_season_power_for_api(year)
    return _SEASON_POWER_CACHE[year]


def get_week_zscores_cached(year: int, week: int, force_refresh: bool = False) -> dict:
    key = (int(year), int(week))
    if force_refresh or key not in _WEEK_ZS_CACHE:
        _WEEK_ZS_CACHE[key] = compute_week_zscores_for_api(year, week)
    return _WEEK_ZS_CACHE[key]


def get_season_zscores_cached(year: int, force_refresh: bool = False) -> dict:
    year = int(year)
    if force_refresh or year not in _SEASON_ZS_CACHE:
        _SEASON_ZS_CACHE[year] = compute_season_zscores_for_api(year)
    return _SEASON_ZS_CACHE[year]


def get_team_history_cached(year: int, team_id: int, force_refresh: bool = False) -> dict:
    key = (int(year), int(team_id))
    if force_refresh or key not in _TEAM_HISTORY_CACHE:
        _TEAM_HISTORY_CACHE[key] = compute_team_history_for_api(year, team_id)
    return _TEAM_HISTORY_CACHE[key]


def get_opponent_matrix_cached(year: int, force_refresh: bool = False) -> Dict:
    """
    Single-year opponent matrix (DB-driven).
    """
    year = int(year)
    if force_refresh:
        _OPPONENT_MATRIX_CACHE.pop(year, None)

    if year not in _OPPONENT_MATRIX_CACHE:
        _OPPONENT_MATRIX_CACHE[year] = compute_opponent_matrix_for_api(year)

    return _OPPONENT_MATRIX_CACHE[year]


def get_opponent_zdiff_matrix_cached(year: int, force_refresh: bool = False) -> Dict:
    """
    Single-year opponent z-diff cache (Q1 endpoint).
    """
    year = int(year)
    if force_refresh:
        _OPPONENT_ZDIFF_CACHE.pop(year, None)

    if year not in _OPPONENT_ZDIFF_CACHE:
        _OPPONENT_ZDIFF_CACHE[year] = compute_opponent_zdiff_matrix_for_api(year)

    return _OPPONENT_ZDIFF_CACHE[year]


# analysis/services.py

def get_opponent_matrix_multi_cached(
    start_year: int,
    end_year: int,
    current_owner_era_only: bool = False,
    force_refresh: bool = False,
) -> Dict:
    """
    Multi-year opponent matrix (aggregated) with caching.
    Cache key: (start_year, end_year, current_owner_era_only)
    """
    start_year = int(start_year)
    end_year = int(end_year)
    current_owner_era_only = bool(current_owner_era_only)

    # Normalize order so cache works consistently
    if end_year < start_year:
        start_year, end_year = end_year, start_year

    key = (start_year, end_year, current_owner_era_only)

    if force_refresh:
        _OPPONENT_MATRIX_MULTI_CACHE.pop(key, None)

    if key not in _OPPONENT_MATRIX_MULTI_CACHE:
        _OPPONENT_MATRIX_MULTI_CACHE[key] = compute_opponent_matrix_multi_for_api(
            start_year=start_year,
            end_year=end_year,
            current_owner_era_only=current_owner_era_only,
        )

    return _OPPONENT_MATRIX_MULTI_CACHE[key]


# -----------------------
# Player-level (optional)
# -----------------------

def build_player_stats_df(year: int) -> pd.DataFrame:
    league = get_league(year)

    rows = []
    for team in league.teams:
        for player in team.roster:
            rows.append(
                {
                    "playerId": player.playerId,
                    "playerName": player.name,
                    "espnProTeam": player.proTeam,
                    "fantasyTeamId": team.team_id,
                    "fantasyTeamName": team.team_name,
                }
            )

    return pd.DataFrame(rows)


def compute_zscores(df: pd.DataFrame, stat_cols: List[str]) -> pd.DataFrame:
    z_df = df.copy()
    for col in stat_cols:
        if col not in z_df.columns:
            continue
        mean = z_df[col].mean()
        std = z_df[col].std(ddof=0) or 1
        z_df[col + "_z"] = (z_df[col] - mean) / std
    return z_df


def compute_team_zscores(year: int) -> pd.DataFrame:
    df_players = build_player_stats_df(year)

    stat_cols = ["REB", "AST", "STL", "BLK", "PTS"]
    existing = [c for c in stat_cols if c in df_players.columns]
    if not existing:
        return pd.DataFrame()

    df_players = compute_zscores(df_players, existing)
    z_cols = [c + "_z" for c in existing]

    return (
        df_players.groupby(["fantasyTeamId", "fantasyTeamName"])[z_cols]
        .sum()
        .reset_index()
    )


# -----------------------
# Helpers
# -----------------------

def _max_week_for_year(year: int, league: League) -> int:
    if year in PLAYOFF_START_WEEKS:
        return PLAYOFF_START_WEEKS[year] + 2

    try:
        return (
            getattr(league.settings, "matchup_period_count", None)
            or getattr(league.settings, "regular_season_matchup_period_count", 20)
        )
    except Exception:
        return 20


def _clean_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


@lru_cache(maxsize=16)
def _build_week_results_df(year: int) -> pd.DataFrame:
    # TEMP: disable until we persist matchup category W/L/T in DB
    return pd.DataFrame(columns=["year", "week", "team_id", "result"])


def build_team_week_stats(year: int) -> pd.DataFrame:
    """
    DB-backed: one row per ESPN team per week from normalized tables.
    Output columns:
      ['year','week','team_id','team_name'] + CATEGORIES
    """
    from models_normalized import StatWeekly, Team

    session = SessionLocal()
    try:
        rows = (
            session.query(StatWeekly, Team)
            .join(Team, Team.id == StatWeekly.team_id)
            .filter(
                StatWeekly.league_id == LEAGUE_ID,
                StatWeekly.season == year,
                Team.league_id == LEAGUE_ID,
                Team.season == year,
            )
            .all()
        )

        if not rows:
            return pd.DataFrame(columns=["year", "week", "team_id", "team_name"] + CATEGORIES)

        data = []
        for w, t in rows:
            data.append(
                {
                    "year": int(year),
                    "week": int(w.week),
                    "team_id": int(t.espn_team_id),
                    "team_name": str(t.name),
                    "FG%": float(w.fg_pct) if w.fg_pct is not None else 0.0,
                    "FT%": float(w.ft_pct) if w.ft_pct is not None else 0.0,
                    "3PM": float(w.tpm or 0),
                    "REB": float(w.reb or 0),
                    "AST": float(w.ast or 0),
                    "STL": float(w.stl or 0),
                    "BLK": float(w.blk or 0),
                    "DD": float(w.dd or 0),
                    "PTS": float(w.pts or 0),
                }
            )

        df = pd.DataFrame(data)
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df.fillna(0.0)

    finally:
        session.close()


def _league_average_row(group: pd.DataFrame) -> Dict:
    avg = group[CATEGORIES].mean().to_dict()
    avg.update(
        {
            "year": int(group["year"].iloc[0]),
            "week": int(group["week"].iloc[0]),
            "team_id": 0,
            "team_name": "League Average",
        }
    )
    return avg


@lru_cache(maxsize=16)
def compute_weekly_zscores(year: int) -> pd.DataFrame:
    base_df = build_team_week_stats(year)
    if base_df.empty:
        return base_df

    league_avg_rows = (
        base_df.groupby(["year", "week"])
        .apply(_league_average_row)
        .reset_index(drop=True)
    )
    df = pd.concat([base_df, league_avg_rows], ignore_index=True)

    all_groups: List[pd.DataFrame] = []

    for (_, _wk), group in df.groupby(["year", "week"]):
        group = group.copy()
        for cat in CATEGORIES:
            if cat not in group.columns:
                continue
            col = group[cat]
            std = float(col.std(ddof=0)) if col.std(ddof=0) is not None else 0.0
            if std == 0:
                group[f"{cat}_z"] = 0.0
            else:
                mean = float(col.mean())
                group[f"{cat}_z"] = (col - mean) / std
        all_groups.append(group)

    z_df = pd.concat(all_groups, ignore_index=True)
    z_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    return z_df.fillna(0.0)


def _ensure_league_average_row(week_df: pd.DataFrame, year: int, week: int) -> pd.DataFrame:
    if week_df.empty:
        return week_df
    if (week_df["team_id"] == 0).any():
        return week_df

    avg_stats: Dict[str, float] = {}
    avg_z: Dict[str, float] = {}

    for cat in CATEGORIES:
        if cat in week_df.columns:
            avg_stats[cat] = float(week_df[cat].mean())
        zcol = f"{cat}_z"
        if zcol in week_df.columns:
            avg_z[zcol] = float(week_df[zcol].mean())

    avg_row = {
        "year": int(year),
        "week": int(week),
        "team_id": 0,
        "team_name": "League Average",
    }
    avg_row.update(avg_stats)
    avg_row.update(avg_z)

    df = pd.concat([week_df, pd.DataFrame([avg_row])], ignore_index=True)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    return df.fillna(0.0)


def _week_df_to_teams_payload(week_df: pd.DataFrame) -> List[Dict]:
    teams_payload: List[Dict] = []
    for _, row in week_df.iterrows():
        stats = {cat: _clean_float(row.get(cat, 0.0)) for cat in CATEGORIES}
        zstats = {f"{cat}_z": _clean_float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES}
        teams_payload.append(
            {
                "teamId": int(row["team_id"]),
                "teamName": str(row["team_name"]),
                "isLeagueAverage": int(row["team_id"]) == 0,
                "stats": stats,
                "zscores": zstats,
            }
        )
    return teams_payload


def compute_week_zscores_for_api(year: int, week: int) -> Dict:
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return {"year": int(year), "week": int(week), "teams": []}

    week_df = z_df[(z_df["year"] == int(year)) & (z_df["week"] == int(week))].copy()
    if week_df.empty:
        return {"year": int(year), "week": int(week), "teams": []}

    week_df = _ensure_league_average_row(week_df, year, week)
    return {"year": int(year), "week": int(week), "teams": _week_df_to_teams_payload(week_df)}


def compute_season_zscores_for_api(year: int) -> Dict:
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return {"year": int(year), "weeks": []}

    weeks = sorted(z_df["week"].unique())
    weeks_payload: List[Dict] = []

    for wk in weeks:
        week_df = z_df[(z_df["year"] == int(year)) & (z_df["week"] == int(wk))].copy()
        if week_df.empty:
            continue
        week_df = _ensure_league_average_row(week_df, year, wk)
        weeks_payload.append({"week": int(wk), "teams": _week_df_to_teams_payload(week_df)})

    return {"year": int(year), "weeks": weeks_payload}


# -----------------------
# POWER + DB CACHING
# -----------------------

@lru_cache(maxsize=16)
def compute_weekly_power_df(year: int) -> pd.DataFrame:
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return z_df

    z_df = z_df.copy()

    results_df = _build_week_results_df(year)
    if not results_df.empty:
        z_df = z_df.merge(results_df, on=["year", "week", "team_id"], how="left")

    z_df["result"] = z_df["result"].fillna(0.5) if "result" in z_df.columns else 0.5

    z_cols = [f"{cat}_z" for cat in CATEGORIES if f"{cat}_z" in z_df.columns]
    z_df["total_z"] = z_df[z_cols].sum(axis=1) if z_cols else 0.0

    z_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    return z_df.fillna(0.0)


def _week_power_from_db(year: int, week: int) -> Dict | None:
    session = SessionLocal()
    try:
        rows = (
            session.query(WeekTeamStats)
            .filter(
                WeekTeamStats.league_id == LEAGUE_ID,
                WeekTeamStats.year == int(year),
                WeekTeamStats.week == int(week),
            )
            .all()
        )
        if not rows:
            return None

        rows_sorted = sorted(rows, key=lambda r: (r.total_z or 0.0), reverse=True)

        teams_payload: List[Dict] = []
        for idx, r in enumerate(rows_sorted, start=1):
            per_cat_z = {
                "FG%_z": _clean_float(r.fg_z),
                "FT%_z": _clean_float(r.ft_z),
                "3PM_z": _clean_float(r.three_pm_z),
                "REB_z": _clean_float(r.reb_z),
                "AST_z": _clean_float(r.ast_z),
                "STL_z": _clean_float(r.stl_z),
                "BLK_z": _clean_float(r.blk_z),
                "DD_z": _clean_float(r.dd_z),
                "PTS_z": _clean_float(r.pts_z),
            }
            teams_payload.append(
                {
                    "teamId": r.team_id,
                    "teamName": r.team_name,
                    "isLeagueAverage": bool(r.is_league_average),
                    "rank": idx,
                    "totalZ": _clean_float(r.total_z),
                    "perCategoryZ": per_cat_z,
                }
            )

        return {"year": int(year), "week": int(week), "teams": teams_payload}
    finally:
        session.close()


def _save_week_power_to_db(year: int, week: int, week_df: pd.DataFrame) -> None:
    session = SessionLocal()
    try:
        for _, row in week_df.iterrows():
            team_id = int(row["team_id"])
            team_name = str(row["team_name"])
            is_league_avg = team_id == 0
            total_z = _clean_float(row.get("total_z", 0.0))

            existing: WeekTeamStats | None = (
                session.query(WeekTeamStats)
                .filter(
                    WeekTeamStats.league_id == LEAGUE_ID,
                    WeekTeamStats.year == int(year),
                    WeekTeamStats.week == int(week),
                    WeekTeamStats.team_id == int(team_id),
                )
                .one_or_none()
            )

            if existing is None:
                existing = WeekTeamStats(
                    league_id=LEAGUE_ID,
                    year=int(year),
                    week=int(week),
                    team_id=int(team_id),
                )
                session.add(existing)

            existing.team_name = team_name
            existing.is_league_average = is_league_avg
            existing.total_z = total_z

            for cat, col_name in CAT_TO_DB_COL.items():
                z_col = f"{cat}_z"
                if z_col in row:
                    setattr(existing, col_name, _clean_float(row[z_col]))

        session.commit()
    finally:
        session.close()


def _compute_all_play_and_luck_for_week(week_df: pd.DataFrame) -> pd.DataFrame:
    if week_df.empty:
        return week_df

    real = week_df[week_df["team_id"] != 0].copy()
    n = len(real)
    if n <= 1:
        for col in [
            "all_play_wins",
            "all_play_losses",
            "all_play_ties",
            "all_play_win_pct",
            "actual_result_score",
            "luck_index",
        ]:
            week_df[col] = 0 if col in ["all_play_wins", "all_play_losses", "all_play_ties"] else 0.0
        return week_df

    totals = real["total_z"].to_numpy()
    wins_list: List[int] = []
    ties_list: List[int] = []

    for ti in totals:
        diff = totals - ti
        wins = int((diff < 0).sum())
        ties = int((diff == 0).sum()) - 1
        wins_list.append(wins)
        ties_list.append(ties)

    real["all_play_wins"] = wins_list
    real["all_play_ties"] = ties_list
    real["all_play_losses"] = (n - 1) - real["all_play_wins"] - real["all_play_ties"]
    real["all_play_win_pct"] = (real["all_play_wins"] + 0.5 * real["all_play_ties"]) / (n - 1)

    real["actual_result_score"] = real["result"].astype(float) if "result" in real.columns else 0.5
    real["luck_index"] = real["actual_result_score"] - real["all_play_win_pct"]

    merged = week_df.merge(
        real[
            [
                "team_id",
                "all_play_wins",
                "all_play_losses",
                "all_play_ties",
                "all_play_win_pct",
                "actual_result_score",
                "luck_index",
            ]
        ],
        on="team_id",
        how="left",
    )

    for col in ["all_play_wins", "all_play_losses", "all_play_ties"]:
        merged[col] = merged[col].fillna(0).astype(int)
    for col in ["all_play_win_pct", "actual_result_score", "luck_index"]:
        merged[col] = merged[col].fillna(0.0).astype(float)

    merged.replace([np.inf, -np.inf], np.nan, inplace=True)
    return merged.fillna(0.0)


def compute_week_power_for_api(
    year: int,
    week: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict:
    year = int(year)
    week = int(week)

    if force_refresh:
        compute_weekly_power_df.cache_clear()
        compute_weekly_zscores.cache_clear()
        _build_week_results_df.cache_clear()

    if use_cache and not force_refresh:
        cached = _week_power_from_db(year, week)
        if cached is not None:
            return cached

    df = compute_weekly_power_df(year)
    if df.empty:
        return {"year": year, "week": week, "teams": []}

    week_df = df[(df["year"] == year) & (df["week"] == week)].copy()
    if week_df.empty:
        return {"year": year, "week": week, "teams": []}

    week_df = _ensure_league_average_row(week_df, year, week)
    week_df = _compute_all_play_and_luck_for_week(week_df)

    for cat in CATEGORIES:
        zcol = f"{cat}_z"
        if zcol not in week_df.columns:
            continue
        real = week_df[week_df["team_id"] != 0].copy()
        real = real.sort_values(zcol, ascending=False).reset_index(drop=True)
        rank_map = {int(r["team_id"]): idx + 1 for idx, r in real.iterrows()}
        week_df[f"{cat}_rank"] = week_df["team_id"].map(rank_map)

    week_df = week_df.sort_values("total_z", ascending=False).reset_index(drop=True)

    _save_week_power_to_db(year, week, week_df)

    teams_payload: List[Dict] = []
    for idx, row in week_df.iterrows():
        per_cat_z = {f"{cat}_z": _clean_float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES}

        per_cat_rank: Dict[str, int | None] = {}
        for cat in CATEGORIES:
            rv = row.get(f"{cat}_rank")
            per_cat_rank[f"{cat}_rank"] = int(rv) if pd.notna(rv) else None

        teams_payload.append(
            {
                "teamId": int(row["team_id"]),
                "teamName": str(row["team_name"]),
                "isLeagueAverage": int(row["team_id"]) == 0,
                "rank": int(idx + 1),
                "totalZ": _clean_float(row.get("total_z", 0.0)),
                "perCategoryZ": per_cat_z,
                "perCategoryRank": per_cat_rank,
                "allPlay": {
                    "wins": int(row.get("all_play_wins", 0)),
                    "losses": int(row.get("all_play_losses", 0)),
                    "ties": int(row.get("all_play_ties", 0)),
                    "winPct": _clean_float(row.get("all_play_win_pct", 0.0)),
                },
                "luckIndex": _clean_float(row.get("luck_index", 0.0)),
            }
        )

    return {"year": year, "week": week, "teams": teams_payload}


def _build_season_summary_df(year: int) -> pd.DataFrame:
    weekly_df = compute_weekly_power_df(year)
    if weekly_df.empty:
        return pd.DataFrame()

    enriched_weeks: List[pd.DataFrame] = []
    for _, group in weekly_df.groupby("week"):
        enriched_weeks.append(_compute_all_play_and_luck_for_week(group))

    full = pd.concat(enriched_weeks, ignore_index=True)

    full = full[full["team_id"] != 0].copy()
    if full.empty:
        return pd.DataFrame()

    grouped = (
        full.groupby(["team_id", "team_name"], as_index=False)
        .agg(
            weeks=("week", "nunique"),
            sumTotalZ=("total_z", "sum"),
            avgTotalZ=("total_z", "mean"),
            actualWins=("actual_result_score", "sum"),
            expectedWins=("all_play_win_pct", "sum"),
            avgLuck=("luck_index", "mean"),
        )
    )

    grouped["luck"] = grouped["actualWins"] - grouped["expectedWins"]
    grouped["fraudScore"] = grouped["luck"] / grouped["weeks"].replace(0, np.nan)
    grouped["fraudScore"] = grouped["fraudScore"].fillna(0.0)

    cat_z_cols = {f"{cat}_z": "mean" for cat in CATEGORIES if f"{cat}_z" in full.columns}
    if cat_z_cols:
        cat_means = full.groupby(["team_id", "team_name"], as_index=False).agg(cat_z_cols)
        grouped = grouped.merge(cat_means, on=["team_id", "team_name"], how="left")

        for cat in CATEGORIES:
            zcol = f"{cat}_z"
            if zcol in grouped.columns:
                grouped[f"{cat}_seasonRank"] = grouped[zcol].rank(method="min", ascending=False).astype(int)

    grouped = grouped.sort_values("avgTotalZ", ascending=False).reset_index(drop=True)
    grouped["rank"] = grouped.index + 1

    grouped.replace([np.inf, -np.inf], np.nan, inplace=True)
    return grouped.fillna(0.0)


def compute_season_power_for_api(year: int) -> Dict:
    grouped = _build_season_summary_df(int(year))
    if grouped.empty:
        return {"year": int(year), "teams": []}

    teams_payload: List[Dict] = []
    for _, row in grouped.iterrows():
        avg = _clean_float(row.get("avgTotalZ", 0.0))

        per_cat_z_season: Dict[str, float] = {}
        per_cat_rank_season: Dict[str, int | None] = {}

        for cat in CATEGORIES:
            zcol = f"{cat}_z"
            rcol = f"{cat}_seasonRank"
            per_cat_z_season[zcol] = _clean_float(row.get(zcol, 0.0))
            per_cat_rank_season[rcol] = int(row.get(rcol)) if rcol in grouped.columns and pd.notna(row.get(rcol)) else None

        teams_payload.append(
            {
                "teamId": int(row["team_id"]),
                "teamName": str(row["team_name"]),
                "rank": int(row["rank"]),
                "weeks": int(row["weeks"]),
                "avgTotalZ": avg,
                "avgZ": avg,
                "sumTotalZ": _clean_float(row.get("sumTotalZ", 0.0)),
                "actualWins": _clean_float(row.get("actualWins", 0.0)),
                "expectedWins": _clean_float(row.get("expectedWins", 0.0)),
                "luck": _clean_float(row.get("luck", 0.0)),
                "avgLuck": _clean_float(row.get("avgLuck", 0.0)),
                "fraudScore": _clean_float(row.get("fraudScore", 0.0)),
                "perCategoryZSeason": per_cat_z_season,
                "perCategoryRankSeason": per_cat_rank_season,
            }
        )

    return {"year": int(year), "teams": teams_payload}


def _completed_weeks_from_db(session, year: int) -> set[int]:
    from models_normalized import Matchup

    rows = (
        session.query(Matchup.week)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == int(year),
            Matchup.winner_team_id.isnot(None),
        )
        .distinct()
        .all()
    )
    return {int(r[0]) for r in rows if r and r[0] is not None}


def _team_history_from_db(year: int, team_id: int) -> Dict | None:
    session = SessionLocal()
    try:
        team_rows = (
            session.query(WeekTeamStats)
            .filter(
                WeekTeamStats.league_id == LEAGUE_ID,
                WeekTeamStats.year == int(year),
                WeekTeamStats.team_id == int(team_id),
                WeekTeamStats.is_league_average == False,
            )
            .order_by(WeekTeamStats.week.asc())
            .all()
        )
        if not team_rows:
            return None

        completed = _completed_weeks_from_db(session, year)
        if completed:
            team_rows = [r for r in team_rows if int(r.week) in completed]
        if not team_rows:
            return None

        weeks = sorted({int(r.week) for r in team_rows})

        all_rows = (
            session.query(WeekTeamStats)
            .filter(
                WeekTeamStats.league_id == LEAGUE_ID,
                WeekTeamStats.year == int(year),
                WeekTeamStats.week.in_(weeks),
                WeekTeamStats.is_league_average == False,
            )
            .all()
        )

        by_week: Dict[int, List[WeekTeamStats]] = {}
        for r in all_rows:
            by_week.setdefault(int(r.week), []).append(r)

        rank_map: Dict[Tuple[int, int], int] = {}
        for wk, rows in by_week.items():
            rows_sorted = sorted(rows, key=lambda x: (x.total_z or 0.0), reverse=True)
            for idx, rr in enumerate(rows_sorted, start=1):
                rank_map[(wk, int(rr.team_id))] = idx

        league_avg_rows = (
            session.query(WeekTeamStats)
            .filter(
                WeekTeamStats.league_id == LEAGUE_ID,
                WeekTeamStats.year == int(year),
                WeekTeamStats.week.in_(weeks),
                WeekTeamStats.is_league_average == True,
            )
            .all()
        )
        league_by_week = {int(r.week): r for r in league_avg_rows}

        history = []
        running_total = 0.0
        team_name = str(team_rows[0].team_name)

        for r in team_rows:
            wk = int(r.week)
            total_z = _clean_float(r.total_z, 0.0)
            running_total += total_z

            zscores = {
                "FG%_z": _clean_float(r.fg_z),
                "FT%_z": _clean_float(r.ft_z),
                "3PM_z": _clean_float(r.three_pm_z),
                "REB_z": _clean_float(r.reb_z),
                "AST_z": _clean_float(r.ast_z),
                "STL_z": _clean_float(r.stl_z),
                "BLK_z": _clean_float(r.blk_z),
                "DD_z": _clean_float(r.dd_z),
                "PTS_z": _clean_float(r.pts_z),
            }

            lr = league_by_week.get(wk)
            if lr:
                league_z = {
                    "FG%_z": _clean_float(lr.fg_z),
                    "FT%_z": _clean_float(lr.ft_z),
                    "3PM_z": _clean_float(lr.three_pm_z),
                    "REB_z": _clean_float(lr.reb_z),
                    "AST_z": _clean_float(lr.ast_z),
                    "STL_z": _clean_float(lr.stl_z),
                    "BLK_z": _clean_float(lr.blk_z),
                    "DD_z": _clean_float(lr.dd_z),
                    "PTS_z": _clean_float(lr.pts_z),
                }
                league_total = _clean_float(sum(league_z.values()), 0.0)
            else:
                league_z = {f"{cat}_z": 0.0 for cat in CATEGORIES}
                league_total = 0.0

            history.append(
                {
                    "week": wk,
                    "stats": {cat: 0.0 for cat in CATEGORIES},
                    "zscores": zscores,
                    "totalZ": total_z,
                    "cumulativeTotalZ": _clean_float(running_total),
                    "rank": int(rank_map.get((wk, int(team_id)), 0)),
                    "leagueAverageStats": {cat: 0.0 for cat in CATEGORIES},
                    "leagueAverageZscores": league_z,
                    "leagueAverageTotalZ": league_total,
                }
            )

        return {
            "year": int(year),
            "teamId": int(team_id),
            "teamName": team_name,
            "history": history,
            "source": "db_weekteamstats",
        }
    finally:
        session.close()


def compute_team_history_for_api(year: int, team_id: int) -> Dict:
    db_payload = _team_history_from_db(int(year), int(team_id))
    if db_payload is not None:
        return db_payload

    return {
        "year": int(year),
        "teamId": int(team_id),
        "teamName": None,
        "history": [],
        "source": "missing_weekteamstats",
    }


# -----------------------
# Opponent analysis
# -----------------------

def compute_opponent_zdiff_matrix_for_api(year: int) -> Dict:
    z_df = compute_weekly_zscores(int(year))
    if z_df.empty:
        return {"year": int(year), "rows": []}

    z_df = z_df[z_df["team_id"] != 0].copy()
    if z_df.empty:
        return {"year": int(year), "rows": []}

    z_index: Dict[Tuple[int, int], pd.Series] = {}
    for _, row in z_df.iterrows():
        z_index[(int(row["week"]), int(row["team_id"]))] = row

    league = get_league(int(year))
    max_week = _max_week_for_year(int(year), league)

    zdiff_rows: List[Dict[str, Any]] = []

    for week in range(1, max_week + 1):
        try:
            scoreboard = league.scoreboard(week)
        except Exception:
            break
        if not scoreboard:
            break

        for matchup in scoreboard:
            home = matchup.home_team
            away = matchup.away_team

            home_id = int(home.team_id)
            away_id = int(away.team_id)
            home_name = str(home.team_name)
            away_name = str(away.team_name)

            home_row = z_index.get((week, home_id))
            away_row = z_index.get((week, away_id))
            if home_row is None or away_row is None:
                continue

            home_payload: Dict[str, Any] = {
                "year": int(year),
                "week": int(week),
                "team_id": home_id,
                "team_name": home_name,
                "opp_team_id": away_id,
                "opp_team_name": away_name,
            }
            away_payload: Dict[str, Any] = {
                "year": int(year),
                "week": int(week),
                "team_id": away_id,
                "team_name": away_name,
                "opp_team_id": home_id,
                "opp_team_name": home_name,
            }

            for cat in CATEGORIES:
                zcol = f"{cat}_z"
                hz = _clean_float(home_row.get(zcol, 0.0))
                az = _clean_float(away_row.get(zcol, 0.0))
                home_payload[cat] = _clean_float(hz - az)
                away_payload[cat] = _clean_float(az - hz)

            zdiff_rows.append(home_payload)
            zdiff_rows.append(away_payload)

    if not zdiff_rows:
        return {"year": int(year), "rows": []}

    zdiff_df = pd.DataFrame(zdiff_rows)
    zdiff_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    zdiff_df = zdiff_df.fillna(0.0)

    agg = (
        zdiff_df.groupby(["team_id", "team_name", "opp_team_id", "opp_team_name"], as_index=False)[CATEGORIES]
        .mean()
    )

    rows_payload: List[Dict[str, Any]] = []
    for _, row in agg.iterrows():
        rows_payload.append(
            {
                "teamId": int(row["team_id"]),
                "teamName": str(row["team_name"]),
                "opponentId": int(row["opp_team_id"]),
                "opponentName": str(row["opp_team_name"]),
                "categoryZDiff": {cat: _clean_float(row.get(cat, 0.0)) for cat in CATEGORIES},
            }
        )

    return {"year": int(year), "rows": rows_payload}


def compute_opponent_matrix_for_api(year: int) -> Dict:
    return _opponent_matrix_from_db(int(year))


def compute_opponent_matrix_multi_for_api(
    start_year: int,
    end_year: int,
    current_owner_era_only: bool = False,
) -> Dict:
    if int(end_year) < int(start_year):
        start_year, end_year = int(end_year), int(start_year)

    start_year = max(int(start_year), 2019)
    end_year = int(end_year)

    combined_pairs: Dict[Tuple[int, int], Dict[str, Any]] = {}

    def merge_rows(rows: List[Dict[str, Any]]):
        for rec in rows:
            key = (int(rec["teamId"]), int(rec["opponentId"]))
            if key not in combined_pairs:
                combined_pairs[key] = {
                    **{k: rec[k] for k in ["teamId", "teamName", "opponentId", "opponentName"]},
                    "matchups": 0,
                    "overall": {"wins": 0, "losses": 0, "ties": 0},
                    "categories": {
                        cat: {"wins": 0, "losses": 0, "ties": 0, "sumDiff": 0.0}
                        for cat in CATEGORIES
                    },
                }

            dst = combined_pairs[key]
            dst["matchups"] += int(rec.get("matchups", 0))

            o = rec.get("overall", {})
            dst["overall"]["wins"] += int(o.get("wins", 0))
            dst["overall"]["losses"] += int(o.get("losses", 0))
            dst["overall"]["ties"] += int(o.get("ties", 0))

            cats = rec.get("categories", {})
            for cat in CATEGORIES:
                c = cats.get(cat, {})
                cw = int(c.get("wins", 0))
                cl = int(c.get("losses", 0))
                ct = int(c.get("ties", 0))
                t = cw + cl + ct
                dst["categories"][cat]["wins"] += cw
                dst["categories"][cat]["losses"] += cl
                dst["categories"][cat]["ties"] += ct
                dst["categories"][cat]["sumDiff"] += _clean_float(c.get("avgDiff", 0.0)) * (t or 0)

    for yr in range(start_year, end_year + 1):
        payload = _opponent_matrix_from_db(yr)
        merge_rows(payload.get("rows", []))

    out_rows = []
    for rec in combined_pairs.values():
        ow, ol, ot = rec["overall"]["wins"], rec["overall"]["losses"], rec["overall"]["ties"]
        total = ow + ol + ot
        rec["overall"]["winPct"] = _clean_float((ow + 0.5 * ot) / total) if total else 0.5

        cat_payload = {}
        for cat, stat in rec["categories"].items():
            cw, cl, ct = stat["wins"], stat["losses"], stat["ties"]
            t = cw + cl + ct
            cat_payload[cat] = {
                "wins": cw,
                "losses": cl,
                "ties": ct,
                "winPct": _clean_float((cw + 0.5 * ct) / t) if t else 0.5,
                "avgDiff": _clean_float(stat["sumDiff"] / t) if t else 0.0,
            }
        rec["categories"] = cat_payload
        out_rows.append(rec)

    return {
        "startYear": start_year,
        "endYear": end_year,
        "rows": out_rows,
        "source": "db_aggregate",
    }


def reshape_opponent_matrix_for_team(team_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    rows = payload.get("rows", [])
    categories = CATEGORIES

    team_rows = [r for r in rows if int(r.get("teamId", -1)) == int(team_id)]

    if not team_rows:
        return {
            "teamId": int(team_id),
            "year": payload.get("year"),
            "opponents": [],
            "opponentIds": [],
            "categories": categories,
            "matrix": [],
        }

    team_rows.sort(key=lambda r: str(r.get("opponentName", "")).lower())

    opponents = [r.get("opponentName") for r in team_rows]
    opponent_ids = [int(r.get("opponentId")) for r in team_rows]

    matrix: List[List[float]] = []
    for cat in categories:
        row_vals: List[float] = []
        for rec in team_rows:
            cat_stats = rec.get("categories", {}).get(cat, {})
            row_vals.append(float(cat_stats.get("winPct", 0.5)))
        matrix.append(row_vals)

    return {
        "teamId": int(team_id),
        "year": payload.get("year"),
        "opponents": opponents,
        "opponentIds": opponent_ids,
        "categories": categories,
        "matrix": matrix,
    }


def _opponent_matrix_from_db(year: int, team_filter_ids: List[int] | None = None) -> Dict:
    """
    DB-driven opponent matrix:
      - completed matchups only (winner_team_id is not null)
      - compare StatWeekly category totals between the two teams for that week
    Uses ESPN team ids in the payload to match your frontend.
    """
    from models_normalized import Matchup, StatWeekly, Team

    session = SessionLocal()
    try:
        matchups = (
            session.query(Matchup)
            .filter(
                Matchup.league_id == LEAGUE_ID,
                Matchup.season == int(year),
                Matchup.winner_team_id.isnot(None),
            )
            .all()
        )
        if not matchups:
            return {"year": int(year), "rows": [], "source": "db"}

        teams = (
            session.query(Team)
            .filter(Team.league_id == LEAGUE_ID, Team.season == int(year))
            .all()
        )
        team_map = {
            int(t.id): (int(t.espn_team_id), str(t.name))
            for t in teams
            if t.espn_team_id is not None
        }

        weekly = (
            session.query(StatWeekly)
            .filter(StatWeekly.league_id == LEAGUE_ID, StatWeekly.season == int(year))
            .all()
        )
        stat_map: Dict[Tuple[int, int], StatWeekly] = {(int(w.week), int(w.team_id)): w for w in weekly}

        pairs: Dict[Tuple[int, int], Dict[str, Any]] = {}

        def ensure_pair(team_espn: int, team_name: str, opp_espn: int, opp_name: str) -> Dict[str, Any]:
            key = (team_espn, opp_espn)
            if key not in pairs:
                pairs[key] = {
                    "teamId": int(team_espn),
                    "teamName": str(team_name),
                    "opponentId": int(opp_espn),
                    "opponentName": str(opp_name),
                    "matchups": 0,
                    "overall": {"wins": 0, "losses": 0, "ties": 0},
                    "categories": {
                        cat: {"wins": 0, "losses": 0, "ties": 0, "sumDiff": 0.0}
                        for cat in CATEGORIES
                    },
                }
            return pairs[key]

        def get_cat_value(sw: StatWeekly, cat: str) -> float:
            if cat == "FG%":
                return float(sw.fg_pct or 0.0)
            if cat == "FT%":
                return float(sw.ft_pct or 0.0)
            if cat == "3PM":
                return float(sw.tpm or 0.0)
            if cat == "REB":
                return float(sw.reb or 0.0)
            if cat == "AST":
                return float(sw.ast or 0.0)
            if cat == "STL":
                return float(sw.stl or 0.0)
            if cat == "BLK":
                return float(sw.blk or 0.0)
            if cat == "DD":
                return float(sw.dd or 0.0)
            if cat == "PTS":
                return float(sw.pts or 0.0)
            return 0.0

        for m in matchups:
            wk = int(m.week)
            home_db_id = int(m.home_team_id)
            away_db_id = int(m.away_team_id)

            if home_db_id not in team_map or away_db_id not in team_map:
                continue

            home_espn, home_name = team_map[home_db_id]
            away_espn, away_name = team_map[away_db_id]

            if team_filter_ids and (home_espn not in team_filter_ids and away_espn not in team_filter_ids):
                continue

            home_sw = stat_map.get((wk, home_db_id))
            away_sw = stat_map.get((wk, away_db_id))
            if home_sw is None or away_sw is None:
                continue

            home_pair = ensure_pair(home_espn, home_name, away_espn, away_name)
            away_pair = ensure_pair(away_espn, away_name, home_espn, home_name)

            home_cat_wins = away_cat_wins = 0

            for cat in CATEGORIES:
                h = _clean_float(get_cat_value(home_sw, cat))
                a = _clean_float(get_cat_value(away_sw, cat))
                diff = h - a

                if h > a:
                    home_result = "win"
                    away_result = "loss"
                    home_cat_wins += 1
                elif h < a:
                    home_result = "loss"
                    away_result = "win"
                    away_cat_wins += 1
                else:
                    home_result = "tie"
                    away_result = "tie"

                h_cat = home_pair["categories"][cat]
                a_cat = away_pair["categories"][cat]

                if home_result == "win":
                    h_cat["wins"] += 1
                    a_cat["losses"] += 1
                elif home_result == "loss":
                    h_cat["losses"] += 1
                    a_cat["wins"] += 1
                else:
                    h_cat["ties"] += 1
                    a_cat["ties"] += 1

                h_cat["sumDiff"] += diff
                a_cat["sumDiff"] -= diff

            if home_cat_wins > away_cat_wins:
                home_pair["overall"]["wins"] += 1
                away_pair["overall"]["losses"] += 1
            elif home_cat_wins < away_cat_wins:
                home_pair["overall"]["losses"] += 1
                away_pair["overall"]["wins"] += 1
            else:
                home_pair["overall"]["ties"] += 1
                away_pair["overall"]["ties"] += 1

            home_pair["matchups"] += 1
            away_pair["matchups"] += 1

        rows: List[Dict[str, Any]] = []
        for rec in pairs.values():
            ow = int(rec["overall"]["wins"])
            ol = int(rec["overall"]["losses"])
            ot = int(rec["overall"]["ties"])
            total = ow + ol + ot

            rec["overall"] = {
                "wins": ow,
                "losses": ol,
                "ties": ot,
                "winPct": _clean_float((ow + 0.5 * ot) / total) if total else 0.5,
            }

            cat_payload: Dict[str, Any] = {}
            for cat, stat in rec["categories"].items():
                cw, cl, ct = int(stat["wins"]), int(stat["losses"]), int(stat["ties"])
                t = cw + cl + ct
                cat_payload[cat] = {
                    "wins": cw,
                    "losses": cl,
                    "ties": ct,
                    "winPct": _clean_float((cw + 0.5 * ct) / t) if t else 0.5,
                    "avgDiff": _clean_float(stat["sumDiff"] / t) if t else 0.0,
                }

            rec["categories"] = cat_payload
            rows.append(rec)

        return {"year": int(year), "rows": rows, "source": "db_matchups_statweekly"}

    finally:
        session.close()