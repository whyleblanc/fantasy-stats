from __future__ import annotations

from functools import lru_cache
from typing import List, Dict, Any

import math
import numpy as np
import pandas as pd

from .constants import CATEGORIES
from .loaders import build_team_week_stats, build_week_results_df, build_player_stats_df


def _clean_float(value: Any, default: float = 0.0) -> float:
    """
    Make sure anything we emit is a finite float.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


# ---------- Player-level helpers (optional) ----------


def compute_zscores(df: pd.DataFrame, stat_cols: List[str]) -> pd.DataFrame:
    """
    Given a stats DataFrame and a list of numeric stat columns,
    return a new DF with z-scores for each stat.
    """
    z_df = df.copy()
    for col in stat_cols:
        if col not in z_df.columns:
            continue
        mean = z_df[col].mean()
        std = z_df[col].std(ddof=0) or 1  # avoid div by zero
        z_df[col + "_z"] = (z_df[col] - mean) / std
    return z_df


def compute_team_zscores(year: int) -> pd.DataFrame:
    """
    Season-level example: aggregate player z-scores to team-level totals/averages.
    Not used by the current API but kept for future work.
    """
    df_players = build_player_stats_df(year)

    # TODO: replace this with your real stat columns
    stat_cols = ["REB", "AST", "STL", "BLK", "PTS"]

    existing = [c for c in stat_cols if c in df_players.columns]
    if not existing:
        return pd.DataFrame()

    df_players = compute_zscores(df_players, existing)

    z_cols = [c + "_z" for c in existing]
    grouped = (
        df_players.groupby(["fantasyTeamId", "fantasyTeamName"])[z_cols]
        .sum()
        .reset_index()
    )

    return grouped


# ---------- Weekly z-scores ----------


def _league_average_row(group: pd.DataFrame) -> Dict:
    """
    Compute league-average row for a given (year, week) group.
    """
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
    """
    For a given year:
      - get team/week stats
      - add a 'League Average' row per week
      - compute z-scores per category, per week
    """
    base_df = build_team_week_stats(year)
    if base_df.empty:
        return base_df

    # Add league average rows
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

    # sanitize
    z_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    z_df = z_df.fillna(0.0)

    return z_df


def _ensure_league_average_row(
    week_df: pd.DataFrame, year: int, week: int
) -> pd.DataFrame:
    """
    Ensure there's a team_id=0, team_name='League Average' row
    for this year/week. If it's already there, return unchanged.
    """
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
    df = df.fillna(0.0)
    return df


def _week_df_to_teams_payload(week_df: pd.DataFrame) -> List[Dict]:
    """
    Convert a single-week DataFrame into a list of team payloads
    with stats + zscores.
    """
    teams_payload: List[Dict] = []

    for _, row in week_df.iterrows():
        stats = {cat: _clean_float(row.get(cat, 0.0)) for cat in CATEGORIES}
        zstats = {
            f"{cat}_z": _clean_float(row.get(f"{cat}_z", 0.0))
            for cat in CATEGORIES
        }
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


# ---------- Power + luck ----------


@lru_cache(maxsize=16)
def compute_weekly_power_df(year: int) -> pd.DataFrame:
    """
    For a given year, return a DF with:
      year, week, team_id, team_name, all cat z-scores, total_z, and result.
    """
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return z_df

    z_df = z_df.copy()

    # Attach "result" from ESPN category results
    results_df = build_week_results_df(year)
    if not results_df.empty:
        z_df = z_df.merge(
            results_df,
            on=["year", "week", "team_id"],
            how="left",
        )

    if "result" in z_df.columns:
        z_df["result"] = z_df["result"].fillna(0.5)
    else:
        z_df["result"] = 0.5

    # Compute total_z
    z_cols = [f"{cat}_z" for cat in CATEGORIES if f"{cat}_z" in z_df.columns]
    if not z_cols:
        z_df["total_z"] = 0.0
    else:
        z_df["total_z"] = z_df[z_cols].sum(axis=1)

    # sanitize
    z_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    z_df = z_df.fillna(0.0)

    return z_df


def _compute_all_play_and_luck_for_week(week_df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a week-level DF with at least:
        ['team_id', 'team_name', 'total_z', 'result']
    compute all-play + luck fields and return a new DF.
    """
    if week_df.empty:
        return week_df

    # Work only on real teams for the calc
    real = week_df[week_df["team_id"] != 0].copy()
    n = len(real)
    if n <= 1:
        # Not enough teams to define all-play; just add zeros.
        for col in [
            "all_play_wins",
            "all_play_losses",
            "all_play_ties",
            "all_play_win_pct",
            "actual_result_score",
            "luck_index",
        ]:
            week_df[col] = (
                0
                if col in ["all_play_wins", "all_play_losses", "all_play_ties"]
                else 0.0
            )
        return week_df

    totals = real["total_z"].to_numpy()
    wins_list: List[int] = []
    ties_list: List[int] = []

    for i, ti in enumerate(totals):
        diff = totals - ti
        wins = int((diff < 0).sum())
        ties = int((diff == 0).sum()) - 1  # exclude self
        wins_list.append(wins)
        ties_list.append(ties)

    real["all_play_wins"] = wins_list
    real["all_play_ties"] = ties_list
    real["all_play_losses"] = (n - 1) - real["all_play_wins"] - real["all_play_ties"]

    real["all_play_win_pct"] = (
        real["all_play_wins"] + 0.5 * real["all_play_ties"]
    ) / (n - 1)

    # result is already a numeric 0–1 category win%
    if "result" in real.columns:
        real["actual_result_score"] = real["result"].astype(float)
    else:
        real["actual_result_score"] = 0.5

    real["luck_index"] = real["actual_result_score"] - real["all_play_win_pct"]

    # Merge back onto the original week_df (league avg row gets NaN → filled)
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

    # Fill defaults for league-average/any missing
    for col in ["all_play_wins", "all_play_losses", "all_play_ties"]:
        merged[col] = merged[col].fillna(0).astype(int)

    for col in ["all_play_win_pct", "actual_result_score", "luck_index"]:
        merged[col] = merged[col].fillna(0.0).astype(float)

    merged.replace([np.inf, -np.inf], np.nan, inplace=True)
    merged = merged.fillna(0.0)

    return merged


def _build_season_summary_df(year: int) -> pd.DataFrame:
    """
    Build a season-level summary DF per team (excluding league average),
    based on weekly power DF enriched with all-play and luck.
    """
    weekly_df = compute_weekly_power_df(year)
    if weekly_df.empty:
        return pd.DataFrame()

    # Enrich each week with all-play and luck
    enriched_weeks: List[pd.DataFrame] = []
    for _, group in weekly_df.groupby("week"):
        group = _compute_all_play_and_luck_for_week(group)
        enriched_weeks.append(group)

    full = pd.concat(enriched_weeks, ignore_index=True)

    # Drop league-average pseudo-team for rankings
    full = full[full["team_id"] != 0].copy()
    if full.empty:
        return pd.DataFrame()

    # Core season aggregates
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

    # Luck + fraud
    grouped["luck"] = grouped["actualWins"] - grouped["expectedWins"]
    grouped["fraudScore"] = grouped["luck"] / grouped["weeks"].replace(0, np.nan)
    grouped["fraudScore"] = grouped["fraudScore"].fillna(0.0)

    # Per-category season-average z
    cat_z_cols = {
        f"{cat}_z": "mean"
        for cat in CATEGORIES
        if f"{cat}_z" in full.columns
    }

    if cat_z_cols:
        cat_means = (
            full.groupby(["team_id", "team_name"], as_index=False)
            .agg(cat_z_cols)
        )
        grouped = grouped.merge(cat_means, on=["team_id", "team_name"], how="left")

        # Per-category season ranks (higher z = better rank)
        for cat in CATEGORIES:
            zcol = f"{cat}_z"
            if zcol in grouped.columns:
                grouped[f"{cat}_seasonRank"] = (
                    grouped[zcol]
                    .rank(method="min", ascending=False)
                    .astype(int)
                )

    # Rank by avgTotalZ (underlying strength)
    grouped = grouped.sort_values("avgTotalZ", ascending=False).reset_index(drop=True)
    grouped["rank"] = grouped.index + 1

    # Sanitize
    grouped.replace([np.inf, -np.inf], np.nan, inplace=True)
    grouped = grouped.fillna(0.0)

    return grouped