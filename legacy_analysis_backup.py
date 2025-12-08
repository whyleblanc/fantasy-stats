from espn_api.basketball import League
from dotenv import load_dotenv
from functools import lru_cache
from typing import List, Dict, Tuple, Any
from db import SessionLocal, WeekTeamStats
import os
import pandas as pd
import numpy as np
import math

load_dotenv()

LEAGUE_ID = int(os.getenv("LEAGUE_ID"))
SWID = os.getenv("SWID")
ESPN_S2 = os.getenv("ESPN_S2")

# Head-to-head categories you care about
CATEGORIES: List[str] = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"]

# Map stat labels -> DB column names for WeekTeamStats
CAT_TO_DB_COL = {
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


@lru_cache(maxsize=64)
def get_league(year: int) -> League:
    """Shared league loader with simple in-memory cache."""
    return League(
        league_id=LEAGUE_ID,
        year=year,
        swid=SWID,
        espn_s2=ESPN_S2,
    )


# ---- Simple in-process caches for heavy computations ----

# key = (year, week) etc.
_WEEK_POWER_CACHE: Dict[Tuple[int, int], Any] = {}
_SEASON_POWER_CACHE: Dict[int, Any] = {}
_WEEK_ZS_CACHE: Dict[Tuple[int, int], Any] = {}
_SEASON_ZS_CACHE: Dict[int, Any] = {}
_TEAM_HISTORY_CACHE: Dict[Tuple[int, int], Any] = {}


def get_week_power_cached(year: int, week: int, force_refresh: bool = False) -> dict:
    """
    Return week power rankings for (year, week) with in-process caching.
    """
    key = (year, week)
    if force_refresh or key not in _WEEK_POWER_CACHE:
        payload = compute_week_power_for_api(year, week)
        _WEEK_POWER_CACHE[key] = payload
    return _WEEK_POWER_CACHE[key]


def get_season_power_cached(year: int, force_refresh: bool = False) -> dict:
    """
    Return season power rankings for a year, cached.
    """
    if force_refresh or year not in _SEASON_POWER_CACHE:
        payload = compute_season_power_for_api(year)
        _SEASON_POWER_CACHE[year] = payload
    return _SEASON_POWER_CACHE[year]


def get_week_zscores_cached(year: int, week: int, force_refresh: bool = False) -> dict:
    """
    Return per-week z-scores for a given week, cached.
    """
    key = (year, week)
    if force_refresh or key not in _WEEK_ZS_CACHE:
        payload = compute_week_zscores_for_api(year, week)
        _WEEK_ZS_CACHE[key] = payload
    return _WEEK_ZS_CACHE[key]


def get_season_zscores_cached(year: int, force_refresh: bool = False) -> dict:
    """
    Return all-season z-scores for a given year, cached.
    """
    if force_refresh or year not in _SEASON_ZS_CACHE:
        payload = compute_season_zscores_for_api(year)
        _SEASON_ZS_CACHE[year] = payload
    return _SEASON_ZS_CACHE[year]


def get_team_history_cached(
    year: int, team_id: int, force_refresh: bool = False
) -> dict:
    """
    Return per-week history for a team (year, team_id), cached.
    """
    key = (year, team_id)
    if force_refresh or key not in _TEAM_HISTORY_CACHE:
        payload = compute_team_history_for_api(year, team_id)
        _TEAM_HISTORY_CACHE[key] = payload
    return _TEAM_HISTORY_CACHE[key]


# -----------------------
# Player-level (placeholder, still there if you want it later)
# -----------------------


def build_player_stats_df(year: int) -> pd.DataFrame:
    """
    Return a DataFrame of player-level stats for the given year.
    """
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

    df = pd.DataFrame(rows)
    return df


def compute_zscores(df: pd.DataFrame, stat_cols: List[str]) -> pd.DataFrame:
    """
    Given a player stats DataFrame and a list of numeric stat columns,
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


# -----------------------
# Helpers
# -----------------------


def _max_week_for_year(year: int, league: League) -> int:
    """
    Decide how many matchup weeks to include for a given year.
    Uses your PLAYOFF_START_WEEKS when defined, else fallback to league data.
    """
    if year in PLAYOFF_START_WEEKS:
        # +2 like your old scripts (reg season + early playoffs)
        return PLAYOFF_START_WEEKS[year] + 2

    # Fallback: use ESPN's matchup period count if available
    try:
        return (
            getattr(league.settings, "matchup_period_count", None)
            or getattr(league.settings, "regular_season_matchup_period_count", 20)
        )
    except Exception:
        return 20


def _extract_category_stats(stats_dict: Dict) -> Dict[str, float]:
    """
    Convert ESPN's home_team_cats / away_team_cats dict into our flat category row.
    """
    row: Dict[str, float] = {}

    for cat in CATEGORIES:
        entry = stats_dict.get(cat)

        if isinstance(entry, dict):
            value = entry.get("score", 0)
        else:
            value = entry

        try:
            row[cat] = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            row[cat] = 0.0

    return row


def _compute_result_score_from_cats(cats: Dict) -> float:
    """
    Turn per-category results into a single scalar "actual result score"
    for the week, on [0,1].
    """
    if not cats:
        return 0.5

    wins = losses = ties = 0

    for cat in CATEGORIES:
        entry = cats.get(cat)
        if not isinstance(entry, dict):
            continue
        res = (entry.get("result") or "").strip().upper()
        if res.startswith("W"):
            wins += 1
        elif res.startswith("L"):
            losses += 1
        elif res.startswith("T") or res.startswith("D"):
            ties += 1

    total = wins + losses + ties
    if total == 0:
        return 0.5

    return (wins + 0.5 * ties) / total


def _clean_float(value: Any, default: float = 0.0) -> float:
    """
    Make sure anything we emit as JSON is a finite float.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


@lru_cache(maxsize=16)
def _build_week_results_df(year: int) -> pd.DataFrame:
    """
    One row per team/week, with a numeric "result" score based on category wins.
    Columns:
      - year
      - week
      - team_id
      - result  (float in [0,1])
    """
    league = get_league(year)
    max_week = _max_week_for_year(year, league)

    rows: List[Dict] = []

    for week in range(1, max_week + 1):
        try:
            scoreboard = league.scoreboard(week)
        except Exception:
            # ESPN may error out on future weeks – stop there
            break

        for matchup in scoreboard:
            home_team = matchup.home_team
            away_team = matchup.away_team

            home_cats = getattr(matchup, "home_team_cats", {}) or {}
            away_cats = getattr(matchup, "away_team_cats", {}) or {}

            home_score = _compute_result_score_from_cats(home_cats)
            away_score = _compute_result_score_from_cats(away_cats)

            rows.append(
                {
                    "year": year,
                    "week": week,
                    "team_id": home_team.team_id,
                    "result": home_score,
                }
            )
            rows.append(
                {
                    "year": year,
                    "week": week,
                    "team_id": away_team.team_id,
                    "result": away_score,
                }
            )

    if not rows:
        return pd.DataFrame(columns=["year", "week", "team_id", "result"])

    df = pd.DataFrame(rows)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df = df.fillna(0.0)
    return df


def build_team_week_stats(year: int) -> pd.DataFrame:
    """
    Build a DataFrame with one row per team per week:
        ['year', 'week', 'team_id', 'team_name'] + CATEGORIES
    """
    league = get_league(year)
    max_week = _max_week_for_year(year, league)

    rows: List[Dict] = []

    for week in range(1, max_week + 1):
        try:
            scoreboard = league.scoreboard(week)
        except Exception:
            # ESPN may error out on future weeks – stop there
            break

        for matchup in scoreboard:
            home_team = matchup.home_team
            away_team = matchup.away_team

            home_stats_raw = getattr(matchup, "home_team_cats", {}) or {}
            away_stats_raw = getattr(matchup, "away_team_cats", {}) or {}

            home_row = {
                "year": year,
                "week": week,
                "team_id": home_team.team_id,
                "team_name": home_team.team_name,
            }
            home_row.update(_extract_category_stats(home_stats_raw))
            rows.append(home_row)

            away_row = {
                "year": year,
                "week": week,
                "team_id": away_team.team_id,
                "team_name": away_team.team_name,
            }
            away_row.update(_extract_category_stats(away_stats_raw))
            rows.append(away_row)

    if not rows:
        return pd.DataFrame(columns=["year", "week", "team_id", "team_name"] + CATEGORIES)

    df = pd.DataFrame(rows)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df = df.fillna(0.0)
    return df


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

    # 🔒 make sure nothing NaN/Inf leaks to the API
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


def compute_week_zscores_for_api(year: int, week: int) -> Dict:
    """
    Return z-score data for a single year+week, JSON-friendly.
    """
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return {"year": year, "week": week, "teams": []}

    week_df = z_df[(z_df["year"] == year) & (z_df["week"] == week)].copy()
    if week_df.empty:
        return {"year": year, "week": week, "teams": []}

    week_df = _ensure_league_average_row(week_df, year, week)
    teams_payload = _week_df_to_teams_payload(week_df)

    return {
        "year": int(year),
        "week": int(week),
        "teams": teams_payload,
    }


def compute_season_zscores_for_api(year: int) -> Dict:
    """
    Return all weeks for a given year.
    """
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return {"year": year, "weeks": []}

    weeks = sorted(z_df["week"].unique())
    weeks_payload: List[Dict] = []

    for wk in weeks:
        week_df = z_df[(z_df["year"] == year) & (z_df["week"] == wk)].copy()
        if week_df.empty:
            continue
        week_df = _ensure_league_average_row(week_df, year, wk)
        teams_payload = _week_df_to_teams_payload(week_df)
        weeks_payload.append(
            {
                "week": int(wk),
                "teams": teams_payload,
            }
        )

    return {
        "year": int(year),
        "weeks": weeks_payload,
    }


# -----------------------
# POWER + DB CACHING
# -----------------------


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
    results_df = _build_week_results_df(year)
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

    # 🔒 sanitize everything for downstream computations
    z_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    z_df = z_df.fillna(0.0)

    return z_df

def _build_season_summary_df(year: int) -> pd.DataFrame:
    """
    Build a season-level summary DF per team (excluding league average),
    based on weekly power DF enriched with all-play and luck.

    Columns (per team_id, team_name):
      - weeks          (number of weeks with data)
      - sumTotalZ
      - avgTotalZ
      - actualWins     (sum of weekly result scores)
      - expectedWins   (sum of all-play win pct)
      - avgLuck        (mean weekly luck_index)
      - luck           (actualWins - expectedWins)
      - fraudScore     (luck / weeks)
      - <cat>_z        (season-average z-score per category)
      - <cat>_seasonRank (rank by season-average z; 1 = best)
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

def _week_power_from_db(year: int, week: int) -> Dict | None:
    """Return cached week power payload from DB, or None if missing."""
    session = SessionLocal()
    try:
        rows = (
            session.query(WeekTeamStats)
            .filter(
                WeekTeamStats.league_id == LEAGUE_ID,
                WeekTeamStats.year == year,
                WeekTeamStats.week == week,
            )
            .all()
        )
        if not rows:
            return None

        # sort by total_z desc
        rows_sorted = sorted(
            rows,
            key=lambda r: (r.total_z or 0.0),
            reverse=True,
        )

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

        return {"year": year, "week": week, "teams": teams_payload}
    finally:
        session.close()


def _save_week_power_to_db(year: int, week: int, week_df: pd.DataFrame) -> None:
    """Upsert week/team z-scores into WeekTeamStats."""
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
                    WeekTeamStats.year == year,
                    WeekTeamStats.week == week,
                    WeekTeamStats.team_id == team_id,
                )
                .one_or_none()
            )

            if existing is None:
                existing = WeekTeamStats(
                    league_id=LEAGUE_ID,
                    year=year,
                    week=week,
                    team_id=team_id,
                )
                session.add(existing)

            existing.team_name = team_name
            existing.is_league_average = is_league_avg
            existing.total_z = total_z

            # per-category z cols
            for cat, col_name in CAT_TO_DB_COL.items():
                z_col = f"{cat}_z"
                if z_col in row:
                    setattr(existing, col_name, _clean_float(row[z_col]))

        session.commit()
    finally:
        session.close()


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
                if col
                in ["all_play_wins", "all_play_losses", "all_play_ties"]
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


def compute_week_power_for_api(
    year: int,
    week: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict:
    """
    Return power ranking for a single week, with all-play + luck.
    """
    # Optional full refresh (stat corrections etc.)
    if force_refresh:
        compute_weekly_power_df.cache_clear()
        compute_weekly_zscores.cache_clear()
        _build_week_results_df.cache_clear()

    # DB cache for base numbers (no luck/all-play)
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

    # Ensure league-average row exists, then compute all-play/luck
    week_df = _ensure_league_average_row(week_df, year, week)
    week_df = _compute_all_play_and_luck_for_week(week_df)

    # Compute per-category ranks for this week (best z-score = rank 1)
    for cat in CATEGORIES:
        zcol = f"{cat}_z"
        if zcol not in week_df.columns:
            continue

        real = week_df[week_df["team_id"] != 0].copy()
        real = real.sort_values(zcol, ascending=False).reset_index(drop=True)

        rank_map = {int(r["team_id"]): idx + 1 for idx, r in real.iterrows()}
        week_df[f"{cat}_rank"] = week_df["team_id"].map(rank_map)

    # Sort best → worst by total_z
    week_df = week_df.sort_values("total_z", ascending=False).reset_index(drop=True)

    # Persist base z-scores to DB (we don't store luck/all-play columns)
    _save_week_power_to_db(year, week, week_df)

    teams_payload: List[Dict] = []
    for idx, row in week_df.iterrows():
        per_cat_z = {
            f"{cat}_z": _clean_float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES
        }

        per_cat_rank: Dict[str, int | None] = {}
        for cat in CATEGORIES:
            rank_val = row.get(f"{cat}_rank")
            if pd.notna(rank_val):
                per_cat_rank[f"{cat}_rank"] = int(rank_val)
            else:
                per_cat_rank[f"{cat}_rank"] = None

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

    return {
        "year": int(year),
        "week": int(week),
        "teams": teams_payload,
    }


def compute_season_power_for_api(year: int) -> Dict:
    """
    Season-long power rankings with fraud/luck + per-category season stats.

    For each team, returns:
      - rank, weeks, avgTotalZ, sumTotalZ
      - actualWins, expectedWins, luck, avgLuck, fraudScore
      - perCategoryZSeason:  { "<CAT>_z": float }   (season-average z)
      - perCategoryRankSeason: { "<CAT>_seasonRank": int | None }
    """
    grouped = _build_season_summary_df(year)
    if grouped.empty:
        return {"year": year, "teams": []}

    teams_payload: List[Dict] = []
    for _, row in grouped.iterrows():
        avg = _clean_float(row["avgTotalZ"])

        # Season per-category z (same key style as weekly perCategoryZ)
        per_cat_z_season: Dict[str, float] = {}
        per_cat_rank_season: Dict[str, int | None] = {}

        for cat in CATEGORIES:
            zcol = f"{cat}_z"
            rcol = f"{cat}_seasonRank"

            if zcol in grouped.columns:
                per_cat_z_season[zcol] = _clean_float(row.get(zcol, 0.0))
            else:
                per_cat_z_season[zcol] = 0.0

            if rcol in grouped.columns and pd.notna(row.get(rcol)):
                per_cat_rank_season[rcol] = int(row.get(rcol))
            else:
                per_cat_rank_season[rcol] = None

        teams_payload.append(
            {
                "teamId": int(row["team_id"]),
                "teamName": str(row["team_name"]),
                "rank": int(row["rank"]),
                "weeks": int(row["weeks"]),
                "avgTotalZ": avg,
                "avgZ": avg,  # alias for frontend
                "sumTotalZ": _clean_float(row["sumTotalZ"]),
                "actualWins": _clean_float(row["actualWins"]),
                "expectedWins": _clean_float(row["expectedWins"]),
                "luck": _clean_float(row["luck"]),
                "avgLuck": _clean_float(row["avgLuck"]),
                "fraudScore": _clean_float(row["fraudScore"]),
                # NEW: season category stats for heatmaps + sorting
                "perCategoryZSeason": per_cat_z_season,
                "perCategoryRankSeason": per_cat_rank_season,
            }
        )

    return {
        "year": int(year),
        "teams": teams_payload,
    }


def compute_team_history_for_api(year: int, team_id: int) -> Dict:
    """
    Return all weeks for a specific team in a given year, including:
    - per-week stats & zscores
    - league average stats & zscores
    - totalZ (sum of z-scores across cats for that week)
    - cumulativeTotalZ (running sum over the season)
    - rank (weekly rank by totalZ; 1 = best)
    """
    z_df = compute_weekly_zscores(year)
    if z_df.empty:
        return {
            "year": year,
            "teamId": team_id,
            "teamName": None,
            "history": [],
        }

    # ---- Compute total_z per row ----
    z_cols = [f"{cat}_z" for cat in CATEGORIES if f"{cat}_z" in z_df.columns]
    z_df = z_df.copy()
    if z_cols:
        z_df["total_z"] = z_df[z_cols].sum(axis=1)
    else:
        z_df["total_z"] = 0.0

    z_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    z_df = z_df.fillna(0.0)

    # ---- Compute weekly rank by total_z (ignore league average row) ----
    no_avg = z_df[z_df["team_id"] != 0].copy()
    ranked_groups = []
    for (yr, wk), grp in no_avg.groupby(["year", "week"]):
        grp = grp.copy()
        grp["weekly_rank_total"] = grp["total_z"].rank(
            method="min", ascending=False
        ).astype(int)
        ranked_groups.append(grp)

    if not ranked_groups:
        return {
            "year": year,
            "teamId": team_id,
            "teamName": None,
            "history": [],
        }

    ranked_df = pd.concat(ranked_groups, ignore_index=True)

    # ---- Slice out this team's rows ----
    team_df = ranked_df[
        (ranked_df["year"] == year) & (ranked_df["team_id"] == team_id)
    ].copy()

    if team_df.empty:
        return {
            "year": year,
            "teamId": team_id,
            "teamName": None,
            "history": [],
        }

    team_name = str(team_df["team_name"].iloc[0])

    history: List[Dict] = []
    running_total_z = 0.0

    for wk in sorted(team_df["week"].unique()):
        row = team_df[team_df["week"] == wk].iloc[0]

        stats = {cat: _clean_float(row.get(cat, 0.0)) for cat in CATEGORIES}
        zstats = {
            f"{cat}_z": _clean_float(row.get(f"{cat}_z", 0.0))
            for cat in CATEGORIES
        }
        total_z = _clean_float(row.get("total_z", 0.0))
        running_total_z += total_z

        rank_val = int(row.get("weekly_rank_total", 0))

        # League average row for same week (team_id == 0)
        league_row = z_df[
            (z_df["year"] == year)
            & (z_df["week"] == wk)
            & (z_df["team_id"] == 0)
        ]

        if not league_row.empty:
            lr = league_row.iloc[0]
            league_stats = {cat: _clean_float(lr.get(cat, 0.0)) for cat in CATEGORIES}
            league_zstats = {
                f"{cat}_z": _clean_float(lr.get(f"{cat}_z", 0.0))
                for cat in CATEGORIES
            }
            league_total_z = _clean_float(sum(league_zstats.values()))
        else:
            league_stats = {cat: 0.0 for cat in CATEGORIES}
            league_zstats = {f"{cat}_z": 0.0 for cat in CATEGORIES}
            league_total_z = 0.0

        history.append(
            {
                "week": int(wk),
                "stats": league_stats if False else stats,  # keep same API shape
                "zscores": zstats,
                "totalZ": total_z,
                "cumulativeTotalZ": running_total_z,
                "rank": rank_val,
                "leagueAverageStats": league_stats,
                "leagueAverageZscores": league_zstats,
                "leagueAverageTotalZ": league_total_z,
            }
        )

    return {
        "year": int(year),
        "teamId": int(team_id),
        "teamName": team_name,
        "history": history,
    }