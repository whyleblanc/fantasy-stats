from espn_api.basketball import League
from dotenv import load_dotenv
from functools import lru_cache
from typing import List, Dict
from db import SessionLocal, WeekTeamStats
import os
import pandas as pd
import numpy as np

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


# -----------------------
# EXISTING: player-level
# -----------------------


def build_player_stats_df(year: int) -> pd.DataFrame:
    """
    Return a DataFrame of player-level stats for the given year.
    Columns might look like:
        ['playerId', 'playerName', 'fantasyTeamId', 'fantasyTeamName',
         'FG%', 'FT%', '3PM', 'REB', 'AST', 'STL', 'BLK', 'PTS', ...]
    Currently a skeleton – you can wire in per-player stats later.
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
                    # TODO: add your per-category stats here (FGM, FGA, 3PM, REB, etc.)
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
# NEW: team/week-level
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

    Example input:
      {
        "FG%": {"result": "WIN", "score": 0.4740566},
        "REB": {"result": "WIN", "score": 223.0},
        ...
      }

    We only care about the numeric 'score' per category.
    """
    row: Dict[str, float] = {}

    for cat in CATEGORIES:
        entry = stats_dict.get(cat)

        if isinstance(entry, dict):
            value = entry.get("score", 0)
        else:
            # Just in case it's already a raw number
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

    We use category win%:

        score = (wins + 0.5 * ties) / total_cats_played

    If we can't infer anything, fall back to 0.5 (neutral).
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

    return pd.DataFrame(rows)


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

    Returns a DataFrame with:
      ['year', 'week', 'team_id', 'team_name'] + CATEGORIES + [f"{cat}_z" ...]
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
    return z_df


def _ensure_league_average_row(week_df: pd.DataFrame, year: int, week: int) -> pd.DataFrame:
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

    return pd.concat([week_df, pd.DataFrame([avg_row])], ignore_index=True)


def _week_df_to_teams_payload(week_df: pd.DataFrame) -> List[Dict]:
    """
    Convert a single-week DataFrame into a list of team payloads
    with stats + zscores.
    """
    teams_payload: List[Dict] = []

    for _, row in week_df.iterrows():
        stats = {cat: float(row.get(cat, 0.0)) for cat in CATEGORIES}
        zstats = {f"{cat}_z": float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES}
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
    Return all weeks for a given year:

    {
      "year": 2025,
      "weeks": [
        { "week": 1, "teams": [...] },
        { "week": 2, "teams": [...] },
        ...
      ]
    }
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

    total_z = sum of z-scores across your 9 categories.
    result  = actual weekly category win% vs opponent (0–1), from ESPN cats.
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
        return z_df

    z_df["total_z"] = z_df[z_cols].sum(axis=1)
    return z_df


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
                "FG%_z": r.fg_z or 0.0,
                "FT%_z": r.ft_z or 0.0,
                "3PM_z": r.three_pm_z or 0.0,
                "REB_z": r.reb_z or 0.0,
                "AST_z": r.ast_z or 0.0,
                "STL_z": r.stl_z or 0.0,
                "BLK_z": r.blk_z or 0.0,
                "DD_z": r.dd_z or 0.0,
                "PTS_z": r.pts_z or 0.0,
            }
            teams_payload.append(
                {
                    "teamId": r.team_id,
                    "teamName": r.team_name,
                    "isLeagueAverage": bool(r.is_league_average),
                    "rank": idx,
                    "totalZ": r.total_z or 0.0,
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
            total_z = float(row.get("total_z", 0.0))

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
                    setattr(existing, col_name, float(row[z_col]))

        session.commit()
    finally:
        session.close()


def _compute_all_play_and_luck_for_week(week_df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a week-level DF with at least:
        ['team_id', 'team_name', 'total_z', 'result']
    and optionally a league-average row with team_id == 0,
    compute:
        - all_play_wins / losses / ties
        - all_play_win_pct (expected win probability vs field)
        - actual_result_score (0–1 category win%)
        - luck_index = actual_result_score - all_play_win_pct

    Returns a *new* DataFrame with these columns added.
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

    # Merge those back onto the original week_df (league avg row gets NaN → filled)
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

    return merged


def compute_week_power_for_api(
    year: int,
    week: int,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict:
    """
    Return power ranking for a single week, with all-play + luck:

    {
      "year": 2025,
      "week": 1,
      "teams": [
        {
          "teamId": ...,
          "teamName": "...",
          "isLeagueAverage": false,
          "rank": 1,
          "totalZ": ...,
          "perCategoryZ": { "FG%_z": ..., ... },
          "allPlay": {
            "wins": ...,
            "losses": ...,
            "ties": ...,
            "winPct": ...
          },
          "luckIndex": ...
        },
        ...
      ]
    }
    """

    # Optional full refresh (stat corrections etc.)
    if force_refresh:
        compute_weekly_power_df.cache_clear()
        compute_weekly_zscores.cache_clear()
        _build_week_results_df.cache_clear()

    # If you really want to use DB cache for the *basic* numbers only,
    # you can keep this branch. Note it won't include all-play/luck.
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
            f"{cat}_z": float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES
        }

    teams_payload: List[Dict] = []
    for idx, row in week_df.iterrows():
        per_cat_z = {
            f"{cat}_z": float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES
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
                "totalZ": float(row["total_z"]),
                "perCategoryZ": per_cat_z,
                "perCategoryRank": per_cat_rank,
                "allPlay": {
                    "wins": int(row.get("all_play_wins", 0)),
                    "losses": int(row.get("all_play_losses", 0)),
                    "ties": int(row.get("all_play_ties", 0)),
                    "winPct": float(row.get("all_play_win_pct", 0.0)),
                },
                "luckIndex": float(row.get("luck_index", 0.0)),
            }
        )

    return {
        "year": int(year),
        "week": int(week),
        "teams": teams_payload,
    }


def compute_season_power_for_api(year: int) -> Dict:
    """
    Season-long power rankings with fraud/luck metrics.

    Output:

    {
      "year": 2025,
      "teams": [
        {
          "teamId": ...,
          "teamName": "...",
          "rank": 1,
          "weeks": 20,
          "avgTotalZ": ...,
          "sumTotalZ": ...,
          "actualWins": ...,
          "expectedWins": ...,
          "luck": ...,
          "avgLuck": ...,
          "fraudScore": ...
        },
        ...
      ]
    }

    - actualWins: sum of weekly category win% (0–1)
    - expectedWins: sum of all-play expected win% (0–1)
    - luck: actualWins - expectedWins
    - fraudScore: luck / weeks
    """
    df = compute_weekly_power_df(year)
    if df.empty:
        return {"year": year, "teams": []}

    # Enrich each week with all-play/luck
    enriched_weeks: List[pd.DataFrame] = []
    for wk, group in df.groupby("week"):
        group = _compute_all_play_and_luck_for_week(group)
        enriched_weeks.append(group)

    full = pd.concat(enriched_weeks, ignore_index=True)

    # Ignore league-average pseudo-team for rankings
    full = full[full["team_id"] != 0].copy()
    if full.empty:
        return {"year": year, "teams": []}

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

    # Rank by avgTotalZ (underlying strength)
    grouped = grouped.sort_values("avgTotalZ", ascending=False).reset_index(drop=True)
    grouped["rank"] = grouped.index + 1

    teams_payload: List[Dict] = []
    for _, row in grouped.iterrows():
        avg = float(row["avgTotalZ"])
        teams_payload.append(
            {
                "teamId": int(row["team_id"]),
                "teamName": str(row["team_name"]),
                "rank": int(row["rank"]),
                "weeks": int(row["weeks"]),
                "avgTotalZ": avg,
                "avgZ": avg,  # <--- alias for frontend
                "sumTotalZ": float(row["sumTotalZ"]),
                "actualWins": float(row["actualWins"]),
                "expectedWins": float(row["expectedWins"]),
                "luck": float(row["luck"]),
                "avgLuck": float(row["avgLuck"]),
                "fraudScore": float(row["fraudScore"]),
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
    if z_cols:
        z_df = z_df.copy()
        z_df["total_z"] = z_df[z_cols].sum(axis=1)
    else:
        z_df = z_df.copy()
        z_df["total_z"] = 0.0

    # ---- Compute weekly rank by total_z (ignore league average row) ----
    no_avg = z_df[z_df["team_id"] != 0].copy()
    ranked_groups = []
    for (yr, wk), grp in no_avg.groupby(["year", "week"]):
        grp = grp.copy()
        # higher total_z = better rank (1 is best)
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

        # Team stats/z
        stats = {cat: float(row.get(cat, 0.0)) for cat in CATEGORIES}
        zstats = {f"{cat}_z": float(row.get(f"{cat}_z", 0.0)) for cat in CATEGORIES}
        total_z = float(row.get("total_z", 0.0))
        running_total_z += total_z

        rank_val = int(row.get("weekly_rank_total", 0))

        # League average row for same week (team_id == 0) comes from original z_df
        league_row = z_df[
            (z_df["year"] == year)
            & (z_df["week"] == wk)
            & (z_df["team_id"] == 0)
        ]

        if not league_row.empty:
            lr = league_row.iloc[0]
            league_stats = {cat: float(lr.get(cat, 0.0)) for cat in CATEGORIES}
            league_zstats = {
                f"{cat}_z": float(lr.get(f"{cat}_z", 0.0)) for cat in CATEGORIES
            }
            league_total_z = float(
                sum(league_zstats.values())
            )  # optional, for context
        else:
            league_stats = {cat: 0.0 for cat in CATEGORIES}
            league_zstats = {f"{cat}_z": 0.0 for cat in CATEGORIES}
            league_total_z = 0.0

        history.append(
            {
                "week": int(wk),
                "stats": stats,
                "zscores": zstats,
                "totalZ": total_z,
                "cumulativeTotalZ": running_total_z,
                "rank": rank_val,  # 🔹 new field used by the chart
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