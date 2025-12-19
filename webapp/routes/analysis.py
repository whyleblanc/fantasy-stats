from __future__ import annotations
from sqlalchemy import func
from collections import defaultdict
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from analysis import (
    get_opponent_matrix_cached,
    get_opponent_matrix_multi_cached,
    get_opponent_zdiff_matrix_cached,
    get_team_history_cached,
)
from analysis.constants import CATEGORIES, CAT_TO_DB_COL
from analysis.owners import build_owners_map
from db import SessionLocal, WeekTeamStats
from models_normalized import StatSeason, StatWeekly, Team, Matchup
from webapp.config import LEAGUE_ID, MAX_YEAR

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/analysis")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed_weeks_from_matchups(session, season: int) -> List[int]:
    rows = (
        session.query(Matchup.week)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == season,
            Matchup.winner_team_id.isnot(None),
        )
        .distinct()
        .order_by(Matchup.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _category_name_map() -> Dict[str, str]:
    # CAT_TO_DB_COL is label -> db_col; invert to db_col -> label
    return {db_col: label for label, db_col in CAT_TO_DB_COL.items()}


def _z_score(val: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return (val - mean) / std


def _attach_owners_to_payload(year: int, payload: dict) -> dict:
    try:
        owners_map = build_owners_map(year)
    except Exception:
        owners_map = {}

    teams = payload.get("teams")
    if not isinstance(teams, list):
        return payload

    for t in teams:
        if not isinstance(t, dict):
            continue
        tid = t.get("teamId")
        if not tid:
            continue
        t["owners"] = owners_map.get(int(tid))

    return payload


def _compute_category_ranks(teams: List[Dict[str, Any]]) -> None:
    cat_values: Dict[str, List[tuple]] = defaultdict(list)

    for idx, t in enumerate(teams):
        cz = t.get("category_z") or {}
        for cat, z in cz.items():
            if z is None:
                continue
            try:
                z_val = float(z)
            except (TypeError, ValueError):
                continue
            cat_values[cat].append((idx, z_val))

    for cat, entries in cat_values.items():
        entries_sorted = sorted(entries, key=lambda x: x[1], reverse=True)
        rank = 1
        for team_idx, _z in entries_sorted:
            teams[team_idx].setdefault("category_rank", {})
            teams[team_idx]["category_rank"][cat] = rank
            rank += 1

    # legacy camelCase alias
    for t in teams:
        if "category_rank" in t and "categoryRank" not in t:
            t["categoryRank"] = t["category_rank"]


def _add_legacy_zscore_aliases_for_week(teams: List[Dict[str, Any]]) -> None:
    for t in teams:
        if "total_z" in t and "totalZ" not in t:
            t["totalZ"] = t["total_z"]
        elif "power_score" in t and "totalZ" not in t:
            t["totalZ"] = t["power_score"]

        cz = t.get("category_z") or {}
        per_cat = t.get("perCategoryZ") or {}
        for label, z in cz.items():
            per_cat[f"{label}_z"] = z
        t["perCategoryZ"] = per_cat


def _add_legacy_zscore_aliases_for_season(
    teams: List[Dict[str, Any]],
    *,
    avg_key: str,
    sum_key: str,
) -> None:
    for t in teams:
        avg_val = float(t.get(avg_key, 0.0))
        sum_val = float(t.get(sum_key, 0.0))

        t.setdefault("avgTotalZ", avg_val)
        t.setdefault("sumTotalZ", sum_val)

        cz = t.get("category_z") or {}
        per_cat = t.get("perCategoryZ") or {}
        for label, z in cz.items():
            per_cat[f"{label}_z"] = z
        t["perCategoryZ"] = per_cat


def _raw_stats_from_statweekly_row(w: StatWeekly) -> Dict[str, Optional[float]]:
    fg_pct = float(w.fg_pct) if w.fg_pct is not None else (
        (float(w.fgm or 0) / float(w.fga or 0)) if (w.fga or 0) > 0 else None
    )
    ft_pct = float(w.ft_pct) if w.ft_pct is not None else (
        (float(w.ftm or 0) / float(w.fta or 0)) if (w.fta or 0) > 0 else None
    )

    return {
        "FG%": fg_pct,
        "FT%": ft_pct,
        "3PM": float(w.tpm or 0),
        "REB": float(w.reb or 0),
        "AST": float(w.ast or 0),
        "STL": float(w.stl or 0),
        "BLK": float(w.blk or 0),
        "DD": float(w.dd or 0),
        "PTS": float(w.pts or 0),
    }


def _week_power_from_stats_weekly(session, season: int, week: int) -> Dict[str, Any]:
    """
    Fallback when WeekTeamStats isn't present for a week:
    compute week power directly from stats_weekly + teams.

    Returns teamId as ESPN team id.
    """
    weekly_rows = (
        session.query(StatWeekly, Team)
        .join(Team, StatWeekly.team_id == Team.id)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season == season,
            StatWeekly.week == week,
        )
        .all()
    )

    if not weekly_rows:
        return {
            "season": season,
            "week": week,
            "categories": CATEGORIES,
            "teams": [],
            "noData": True,
            "source": "stats_weekly_fallback",
        }

    team_values: Dict[int, Dict[str, Any]] = {}
    for w, t in weekly_rows:
        espn_tid = int(t.espn_team_id)
        team_values[espn_tid] = {
            "teamName": t.name,
            "raw_stats": _raw_stats_from_statweekly_row(w),
        }

    means: Dict[str, float] = {}
    stds: Dict[str, float] = {}
    for cat in CATEGORIES:
        vals = [
            v["raw_stats"][cat]
            for v in team_values.values()
            if v["raw_stats"].get(cat) is not None
        ]
        if not vals:
            means[cat] = 0.0
            stds[cat] = 0.0
            continue

        n = len(vals)
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / n
        std = var ** 0.5

        means[cat] = mean
        stds[cat] = std

    teams: List[Dict[str, Any]] = []
    for espn_tid, rec in team_values.items():
        cz: Dict[str, float] = {}
        total = 0.0
        for cat in CATEGORIES:
            val = rec["raw_stats"].get(cat)
            if val is None:
                continue
            z = _z_score(float(val), means[cat], stds[cat])
            cz[cat] = z
            total += z

        teams.append(
            {
                "teamId": int(espn_tid),
                "teamName": rec["teamName"],
                "power_score": float(total),
                "category_z": cz,
                "raw_stats": rec["raw_stats"],
            }
        )

    _compute_category_ranks(teams)
    teams.sort(key=lambda t: t["power_score"], reverse=True)
    for idx, t in enumerate(teams, start=1):
        t["rank"] = idx

    _add_legacy_zscore_aliases_for_week(teams)

    payload: Dict[str, Any] = {
        "season": season,
        "week": week,
        "categories": CATEGORIES,
        "teams": teams,
        "source": "stats_weekly_fallback",
    }
    return _attach_owners_to_payload(season, payload)


def _season_power_from_weekteamstats(session, season: int) -> Dict[str, Any]:
    # Use matchup completion as the source of truth for "completed weeks"
    completed_weeks = _completed_weeks_from_matchups(session, season)

    rows_q = (
        session.query(
            WeekTeamStats.team_id.label("teamId"),
            WeekTeamStats.team_name.label("teamName"),
            func.count(func.distinct(WeekTeamStats.week)).label("totalWeeks"),
            func.sum(WeekTeamStats.total_z).label("sumTotalZ"),
            func.avg(WeekTeamStats.total_z).label("avgTotalZ"),
        )
        .filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.year == season,
            WeekTeamStats.is_league_average == False,
        )
    )

    # Clamp if we have completed weeks (this fixes 2026)
    if completed_weeks:
        rows_q = rows_q.filter(WeekTeamStats.week.in_(completed_weeks))

    rows = (
        rows_q
        .group_by(WeekTeamStats.team_id, WeekTeamStats.team_name)
        .all()
    )

    if not rows:
        return {
            "season": season,
            "teams": [],
            "noData": True,
            "source": "week_team_stats",
        }

    teams: List[Dict[str, Any]] = []
    for r in rows:
        teams.append({
            "teamId": int(r.teamId),
            "teamName": r.teamName,
            "weeks": int(r.totalWeeks or 0),
            "games_played": None,
            "season_power_score": float(r.sumTotalZ or 0.0),
            "sumTotalZ": float(r.sumTotalZ or 0.0),
            "avgTotalZ": float(r.avgTotalZ or 0.0),
            "category_z": None,
        })

    teams.sort(key=lambda t: t["sumTotalZ"], reverse=True)
    for idx, t in enumerate(teams, start=1):
        t["rank"] = idx

    _add_legacy_zscore_aliases_for_season(teams, avg_key="avgTotalZ", sum_key="sumTotalZ")

    payload: Dict[str, Any] = {
        "season": season,
        "teams": teams,
        "source": "week_team_stats",
        "completedWeeks": completed_weeks if completed_weeks else None,
    }
    return _attach_owners_to_payload(season, payload)


# ---------------------------------------------------------------------------
# WEEK Z-SCORES – DB-backed (WeekTeamStats)
# ---------------------------------------------------------------------------

@analysis_bp.route("/week-zscores")
def week_zscores_api():
    season = request.args.get("year", default=MAX_YEAR, type=int)
    week = request.args.get("week", default=1, type=int)

    session = SessionLocal()
    try:
        rows: List[WeekTeamStats] = (
            session.query(WeekTeamStats)
            .filter_by(
                league_id=LEAGUE_ID,
                year=season,
                week=week,
                is_league_average=False,
            )
            .all()
        )

        if not rows:
            return jsonify(
                {"season": season, "week": week, "categories": CATEGORIES, "teams": [], "noData": True}
            )

        cat_map = _category_name_map()
        teams: List[Dict[str, Any]] = []

        for r in rows:
            cat_z: Dict[str, float] = {}
            for field, label in cat_map.items():
                z_val = getattr(r, field, None)
                if z_val is None:
                    continue
                cat_z[label] = float(z_val)

            teams.append(
                {
                    "teamId": int(r.team_id),      # WeekTeamStats.team_id is ESPN team id
                    "teamName": r.team_name,
                    "total_z": float(r.total_z or 0.0),
                    "category_z": cat_z,
                }
            )

        teams.sort(key=lambda t: t["total_z"], reverse=True)
        for idx, t in enumerate(teams, start=1):
            t["rank"] = idx

        _add_legacy_zscore_aliases_for_week(teams)

        payload = {
            "season": season,
            "week": week,
            "categories": CATEGORIES,
            "teams": teams,
            "source": "week_team_stats",
        }
        return jsonify(_attach_owners_to_payload(season, payload))

    except Exception as e:
        session.rollback()
        return (
            jsonify(
                {
                    "error": "Failed to compute weekly z-scores",
                    "year": season,
                    "week": week,
                    "details": str(e),
                }
            ),
            500,
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SEASON Z-SCORES – DB-backed (avg of WeekTeamStats)
# ---------------------------------------------------------------------------

@analysis_bp.route("/season-zscores")
def season_zscores_api():
    season = request.args.get("year", default=MAX_YEAR, type=int)

    session = SessionLocal()
    try:
        weeks_with_data = _completed_weeks_from_matchups(session, season)

        q = session.query(WeekTeamStats).filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.year == season,
            WeekTeamStats.is_league_average == False,
        )

        if weeks_with_data:
            q = q.filter(WeekTeamStats.week.in_(weeks_with_data))

        rows: List[WeekTeamStats] = q.all()

        if not rows:
            return jsonify({"season": season, "categories": CATEGORIES, "teams": [], "noData": True})

        cat_map = _category_name_map()
        agg: Dict[int, Dict[str, Any]] = defaultdict(
            lambda: {
                "team_name": "",
                "weeks": 0,
                "sum_total_z": 0.0,
                "sum_cat_z": defaultdict(float),
                "count_cat": defaultdict(int),
            }
        )

        for r in rows:
            rec = agg[r.team_id]
            rec["team_name"] = r.team_name
            rec["weeks"] += 1
            rec["sum_total_z"] += float(r.total_z or 0.0)

            for field, label in cat_map.items():
                z_val = getattr(r, field, None)
                if z_val is None:
                    continue
                rec["sum_cat_z"][label] += float(z_val)
                rec["count_cat"][label] += 1

        teams: List[Dict[str, Any]] = []
        for tid, rec in agg.items():
            weeks = rec["weeks"] or 1
            avg_total = rec["sum_total_z"] / weeks

            cat_z: Dict[str, float] = {}
            for label in CATEGORIES:
                cnt = rec["count_cat"][label]
                if cnt == 0:
                    continue
                cat_z[label] = rec["sum_cat_z"][label] / cnt

            teams.append(
                {
                    "teamId": int(tid),
                    "teamName": rec["team_name"],
                    "weeks": int(weeks),
                    "avg_total_z": avg_total,
                    "sum_total_z": rec["sum_total_z"],
                    "category_z": cat_z,
                }
            )

        teams.sort(key=lambda t: t["avg_total_z"], reverse=True)
        for idx, t in enumerate(teams, start=1):
            t["rank"] = idx

        _add_legacy_zscore_aliases_for_season(teams, avg_key="avg_total_z", sum_key="sum_total_z")

        payload = {
            "season": season,
            "categories": CATEGORIES,
            "teams": teams,
            "source": "week_team_stats",
        }
        return jsonify(_attach_owners_to_payload(season, payload))

    except Exception as e:
        session.rollback()
        return (
            jsonify({"error": "Failed to compute season z-scores", "year": season, "details": str(e)}),
            500,
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# WEEK POWER – WeekTeamStats with stats_weekly raw-stats enrichment + fallback
# ---------------------------------------------------------------------------

@analysis_bp.route("/week-power")
def week_power_api():
    season = request.args.get("year", default=MAX_YEAR, type=int)
    week = request.args.get("week", default=1, type=int)
    _ = request.args.get("refresh", default=0, type=int)  # no-op

    session = SessionLocal()
    try:
        rows: List[WeekTeamStats] = (
            session.query(WeekTeamStats)
            .filter_by(
                league_id=LEAGUE_ID,
                year=season,
                week=week,
                is_league_average=False,
            )
            .all()
        )

        # If no advanced cache row exists, compute from stats_weekly
        if not rows:
            return jsonify(_week_power_from_stats_weekly(session, season, week))

        cat_map = _category_name_map()

        # raw_stats from stats_weekly keyed by ESPN team id
        raw_map: Dict[int, Dict[str, Optional[float]]] = {}
        weekly_rows = (
            session.query(StatWeekly, Team)
            .join(Team, StatWeekly.team_id == Team.id)
            .filter(
                StatWeekly.league_id == LEAGUE_ID,
                StatWeekly.season == season,
                StatWeekly.week == week,
            )
            .all()
        )
        for w, t in weekly_rows:
            raw_map[int(t.espn_team_id)] = _raw_stats_from_statweekly_row(w)

        teams: List[Dict[str, Any]] = []
        for r in rows:
            cat_z: Dict[str, float] = {}
            for field, label in cat_map.items():
                z_val = getattr(r, field, None)
                if z_val is None:
                    continue
                cat_z[label] = float(z_val)

            espn_tid = int(r.team_id)  # WeekTeamStats.team_id is ESPN team id
            team_entry: Dict[str, Any] = {
                "teamId": espn_tid,
                "teamName": r.team_name,
                "power_score": float(r.total_z or 0.0),
                "category_z": cat_z,
            }

            if espn_tid in raw_map:
                team_entry["raw_stats"] = raw_map[espn_tid]

            teams.append(team_entry)

        _compute_category_ranks(teams)

        teams.sort(key=lambda t: t["power_score"], reverse=True)
        for idx, t in enumerate(teams, start=1):
            t["rank"] = idx

        _add_legacy_zscore_aliases_for_week(teams)

        payload: Dict[str, Any] = {
            "season": season,
            "week": week,
            "categories": CATEGORIES,
            "teams": teams,
            "source": "week_team_stats",
        }
        return jsonify(_attach_owners_to_payload(season, payload))

    except Exception as e:
        session.rollback()
        return (
            jsonify({"error": "Failed to compute weekly power", "year": season, "week": week, "details": str(e)}),
            500,
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SEASON POWER – stats_season fallback
# ---------------------------------------------------------------------------

@analysis_bp.route("/season-power")
def season_power_api():
    season = request.args.get("year", default=MAX_YEAR, type=int)
    _ = request.args.get("refresh", default=0, type=int)

    session = SessionLocal()
    try:
        payload = _season_power_from_weekteamstats(session, season)
        if payload.get("noData"):
            payload = _season_power_from_stats_season(session, season)
        return jsonify(payload)
    except Exception as e:
        session.rollback()
        return jsonify({"error": "Failed to compute season power", "year": season, "details": str(e)}), 500
    finally:
        session.close()


# ---------------------------------------------------------------------------
# TEAM HISTORY – legacy ESPN-backed (soft-fail)
# ---------------------------------------------------------------------------

@analysis_bp.route("/team-history")
def team_history_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    if team_id is None:
        return jsonify({"error": "Missing required parameter 'teamId'", "year": year}), 400

    try:
        payload = get_team_history_cached(year, team_id, force_refresh=refresh)
        if isinstance(payload, dict) and "teams" in payload:
            payload = _attach_owners_to_payload(year, payload)
        return jsonify(payload)
    except Exception as e:
        return jsonify(
            {
                "year": year,
                "teamId": team_id,
                "history": [],
                "weeks": [],
                "source": "espn_fallback_error",
                "error": "Failed to compute team history",
                "details": str(e),
            }
        )


# ---------------------------------------------------------------------------
# OPPONENT ENDPOINTS – legacy ESPN-backed (soft-fail)
# ---------------------------------------------------------------------------

@analysis_bp.route("/opponent-matrix")
def opponent_matrix_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)

    start_year = request.args.get("startYear", type=int)
    end_year = request.args.get("endYear", type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1
    era_only = request.args.get("currentOwnerEraOnly", default=0, type=int) == 1

    try:
        if start_year is not None or end_year is not None:
            if start_year is None:
                start_year = year
            if end_year is None:
                end_year = start_year
            if end_year < start_year:
                start_year, end_year = end_year, start_year

            payload = get_opponent_matrix_multi_cached(
                start_year,
                end_year,
                current_owner_era_only=era_only,
                force_refresh=refresh,
            )
            rows = payload.get("rows", [])
            result = {
                "startYear": payload.get("startYear", start_year),
                "endYear": payload.get("endYear", end_year),
                "rows": rows,
            }
        else:
            payload = get_opponent_matrix_cached(year, force_refresh=refresh)
            rows = payload.get("rows", [])
            result = {"year": year, "startYear": year, "endYear": year, "rows": rows}

        rows_filtered = result["rows"]
        if team_id is not None:
            rows_filtered = [r for r in rows_filtered if r.get("teamId") == team_id]

        result["rows"] = rows_filtered
        result["teamId"] = team_id
        return jsonify(result)

    except Exception as e:
        return jsonify(
            {
                "year": year,
                "startYear": start_year or year,
                "endYear": end_year or start_year or year,
                "teamId": team_id,
                "rows": [],
                "source": "espn_fallback_error",
                "error": "Failed to compute opponent matrix",
                "details": str(e),
            }
        )


@analysis_bp.route("/opponent-heatmap")
def opponent_heatmap_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    if team_id is None:
        return jsonify({"error": "Missing required parameter 'teamId'", "year": year}), 400

    try:
        raw_matrix = get_opponent_matrix_cached(year, force_refresh=refresh)
        from analysis.services import reshape_opponent_matrix_for_team

        return jsonify(reshape_opponent_matrix_for_team(team_id, raw_matrix))
    except Exception as e:
        return jsonify(
            {
                "year": year,
                "teamId": team_id,
                "rows": [],
                "categories": CATEGORIES,
                "source": "espn_fallback_error",
                "error": "Failed to compute opponent heatmap",
                "details": str(e),
            }
        )


@analysis_bp.route("/opponent-zdiff")
def opponent_zdiff_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = request.args.get("refresh", default=0, type=int) == 1

    try:
        payload = get_opponent_zdiff_matrix_cached(year, force_refresh=refresh)
        rows = payload.get("rows", [])
        if team_id is not None:
            rows = [r for r in rows if r.get("teamId") == team_id]
        return jsonify({"year": year, "rows": rows})
    except Exception as e:
        return jsonify(
            {
                "year": year,
                "teamId": team_id,
                "rows": [],
                "source": "espn_fallback_error",
                "error": "Failed to compute opponent z-diff matrix",
                "details": str(e),
            }
        )


@analysis_bp.route("/opponent-matrix-multi")
def opponent_matrix_multi_api():
    start_year = request.args.get("startYear", default=2019, type=int)
    end_year = request.args.get("endYear", default=MAX_YEAR, type=int)

    team_id = request.args.get("teamId", type=int)

    # NOTE: match your frontend/querystring: currentOwnerEraOnly
    owner_era_only = request.args.get("currentOwnerEraOnly", default="false")
    owner_era_only = str(owner_era_only).lower() in ("1", "true", "yes", "y")

    # NOTE: match your frontend/querystring: forceRefresh
    refresh = request.args.get("forceRefresh", default="false")
    refresh = str(refresh).lower() in ("1", "true", "yes", "y")

    if end_year < start_year:
        start_year, end_year = end_year, start_year

    try:
        raw = get_opponent_matrix_multi_cached(
            start_year,
            end_year,
            current_owner_era_only=owner_era_only,
            force_refresh=refresh,
        )

        all_rows = raw.get("rows", [])

        # Optional filter by teamId (only if provided)
        rows = all_rows
        if team_id is not None:
            rows = [r for r in all_rows if int(r.get("teamId", 0)) == int(team_id)]

        return jsonify(
            {
                # keep both naming conventions if you want
                "startYear": int(raw.get("startYear", start_year)),
                "endYear": int(raw.get("endYear", end_year)),
                "minYear": int(raw.get("startYear", start_year)),
                "maxYear": int(raw.get("endYear", end_year)),

                "teamId": int(team_id) if team_id is not None else None,
                "ownerEraOnly": bool(owner_era_only),
                "rows": rows,
                "source": raw.get("source"),
            }
        )

    except Exception as e:
        return jsonify(
            {
                "startYear": start_year,
                "endYear": end_year,
                "minYear": start_year,
                "maxYear": end_year,
                "teamId": team_id,
                "ownerEraOnly": owner_era_only,
                "rows": [],
                "source": "route_error",
                "error": "Failed to compute multi-year opponent matrix",
                "details": str(e),
            }
        ), 500