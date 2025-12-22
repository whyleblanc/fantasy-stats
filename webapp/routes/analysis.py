from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from analysis import (
    get_opponent_matrix_cached,
    get_opponent_matrix_multi_cached,
    get_opponent_zdiff_matrix_cached,
)
from analysis.constants import CATEGORIES, CAT_TO_DB_COL
from analysis.owners import build_owners_map
from analysis.owners import get_owner_start_year
from models_aggregates import OpponentMatrixAggYear

from db import SessionLocal, WeekTeamStats
from models_normalized import StatWeekly, Team, Matchup  # StatSeason only needed if you use season fallback
from webapp.config import LEAGUE_ID, MAX_YEAR
from webapp.services.opponent_matrix_db import get_opponent_matrix_multi_db
from webapp.services.opponent_matrix_agg_year import get_opponent_matrix_from_agg_year

from webapp.services.team_history_agg import (
    get_team_history_from_agg,
    rebuild_team_history_agg,
)

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/analysis")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bool_arg(name: str, default: bool = False) -> bool:
    v = request.args.get(name, None)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _row_to_ui_shape(r: OpponentMatrixAggYear) -> dict:
    def cat_block(prefix: str):
        w = int(getattr(r, f"{prefix}_w") or 0)
        l = int(getattr(r, f"{prefix}_l") or 0)
        t = int(getattr(r, f"{prefix}_t") or 0)
        n = int(getattr(r, f"{prefix}_diff_n") or 0)
        s = float(getattr(r, f"{prefix}_diff_sum") or 0.0)
        total = w + l + t
        return {
            "wins": w,
            "losses": l,
            "ties": t,
            "winPct": (w / total) if total else 0.0,
            "avgDiff": (s / n) if n else 0.0,
        }

    wins = int(r.wins or 0)
    losses = int(r.losses or 0)
    ties = int(r.ties or 0)
    matchups = int(r.matchups or 0)
    total = wins + losses + ties

    return {
        "opponentTeamId": int(r.opponent_team_id),
        "opponentName": r.opponent_name or "",
        "matchups": matchups,
        "overall": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "matchups": matchups,
            "winPct": (wins / total) if total else 0.0,
        },
        "categories": {
            "FG%": cat_block("fg"),
            "FT%": cat_block("ft"),
            "3PM": cat_block("three_pm"),
            "REB": cat_block("reb"),
            "AST": cat_block("ast"),
            "STL": cat_block("stl"),
            "BLK": cat_block("blk"),
            "DD": cat_block("dd"),
            "PTS": cat_block("pts"),
        },
    }


def _merge_ui_rows(rows: list[dict]) -> list[dict]:
    """
    Merge multiple year rows (same opponent) into one combined row.
    """
    merged = {}

    for row in rows:
        oid = int(row.get("opponentTeamId") or 0)
        if not oid:
            continue

        m = merged.setdefault(
            oid,
            {
                "opponentTeamId": oid,
                "opponentName": row.get("opponentName") or "",
                "matchups": 0,
                "overall": {"wins": 0, "losses": 0, "ties": 0, "matchups": 0, "winPct": 0.0},
                "categories": {},
            },
        )

        # overall
        m["matchups"] += int(row.get("matchups") or 0)
        o = row.get("overall") or {}
        m["overall"]["wins"] += int(o.get("wins") or 0)
        m["overall"]["losses"] += int(o.get("losses") or 0)
        m["overall"]["ties"] += int(o.get("ties") or 0)
        m["overall"]["matchups"] += int(o.get("matchups") or 0)

        # categories
        cats = row.get("categories") or {}
        for cat, blk in cats.items():
            cur = m["categories"].setdefault(
                cat,
                {"wins": 0, "losses": 0, "ties": 0, "diffSum": 0.0, "diffN": 0},
            )
            cur["wins"] += int(blk.get("wins") or 0)
            cur["losses"] += int(blk.get("losses") or 0)
            cur["ties"] += int(blk.get("ties") or 0)

            # We can't perfectly merge avgDiff without sums, so convert back into sums.
            # blk.avgDiff = diffSum/diffN, but we don't have diffN in UI shape.
            # So: just approximate by weighting by total (wins+losses+ties) as N.
            # Better: keep diff_n and diff_sum in UI, but you don't today.
            # We'll approximate using matchups as weight:
            weight = (int(blk.get("wins") or 0) + int(blk.get("losses") or 0) + int(blk.get("ties") or 0))
            cur["diffSum"] += float(blk.get("avgDiff") or 0.0) * float(weight)
            cur["diffN"] += int(weight)

    # finalize
    out = []
    for oid, m in merged.items():
        # overall winPct
        total = m["overall"]["wins"] + m["overall"]["losses"] + m["overall"]["ties"]
        m["overall"]["winPct"] = (m["overall"]["wins"] / total) if total else 0.0

        # per-cat finalize avgDiff + winPct
        finalized_cats = {}
        for cat, cur in m["categories"].items():
            total_cat = cur["wins"] + cur["losses"] + cur["ties"]
            finalized_cats[cat] = {
                "wins": cur["wins"],
                "losses": cur["losses"],
                "ties": cur["ties"],
                "winPct": (cur["wins"] / total_cat) if total_cat else 0.0,
                "avgDiff": (cur["diffSum"] / cur["diffN"]) if cur["diffN"] else 0.0,
            }
        m["categories"] = finalized_cats

        out.append(m)

    # sort: best overall winPct then most matchups
    out.sort(key=lambda r: (r["overall"]["winPct"], r["matchups"]), reverse=True)
    return out

def _bool_arg(name: str, default: bool = False) -> bool:
    raw = request.args.get(name, None)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "t")


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

    if completed_weeks:
        rows_q = rows_q.filter(WeekTeamStats.week.in_(completed_weeks))

    rows = (
        rows_q
        .group_by(WeekTeamStats.team_id, WeekTeamStats.team_name)
        .all()
    )

    if not rows:
        return {"season": season, "teams": [], "noData": True, "source": "week_team_stats"}

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


# If you already have a real stats_season fallback elsewhere, use it.
def _season_power_from_stats_season(session, season: int) -> Dict[str, Any]:
    return {"season": season, "teams": [], "noData": True, "source": "stats_season_fallback_missing"}


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
            return jsonify({"season": season, "week": week, "categories": CATEGORIES, "teams": [], "noData": True})

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
                    "teamId": int(r.team_id),
                    "teamName": r.team_name,
                    "total_z": float(r.total_z or 0.0),
                    "category_z": cat_z,
                }
            )

        teams.sort(key=lambda t: t["total_z"], reverse=True)
        for idx, t in enumerate(teams, start=1):
            t["rank"] = idx

        _add_legacy_zscore_aliases_for_week(teams)

        payload = {"season": season, "week": week, "categories": CATEGORIES, "teams": teams, "source": "week_team_stats"}
        return jsonify(_attach_owners_to_payload(season, payload))

    except Exception as e:
        session.rollback()
        return jsonify({"error": "Failed to compute weekly z-scores", "year": season, "week": week, "details": str(e)}), 500
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
            rec = agg[int(r.team_id)]
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
                if cnt:
                    cat_z[label] = rec["sum_cat_z"][label] / cnt

            teams.append(
                {
                    "teamId": int(tid),
                    "teamName": rec["team_name"],
                    "weeks": int(weeks),
                    "avg_total_z": float(avg_total),
                    "sum_total_z": float(rec["sum_total_z"]),
                    "category_z": cat_z,
                }
            )

        teams.sort(key=lambda t: t["avg_total_z"], reverse=True)
        for idx, t in enumerate(teams, start=1):
            t["rank"] = idx

        _add_legacy_zscore_aliases_for_season(teams, avg_key="avg_total_z", sum_key="sum_total_z")

        payload = {"season": season, "categories": CATEGORIES, "teams": teams, "source": "week_team_stats"}
        return jsonify(_attach_owners_to_payload(season, payload))

    except Exception as e:
        session.rollback()
        return jsonify({"error": "Failed to compute season z-scores", "year": season, "details": str(e)}), 500
    finally:
        session.close()


# ---------------------------------------------------------------------------
# WEEK POWER – WeekTeamStats with stats_weekly raw-stats enrichment + fallback
# ---------------------------------------------------------------------------

@analysis_bp.route("/week-power")
def week_power_api():
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

            espn_tid = int(r.team_id)
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

        payload: Dict[str, Any] = {"season": season, "week": week, "categories": CATEGORIES, "teams": teams, "source": "week_team_stats"}
        return jsonify(_attach_owners_to_payload(season, payload))

    except Exception as e:
        session.rollback()
        return jsonify({"error": "Failed to compute weekly power", "year": season, "week": week, "details": str(e)}), 500
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SEASON POWER – week_team_stats, fallback to stats_season
# ---------------------------------------------------------------------------

@analysis_bp.route("/season-power")
def season_power_api():
    season = request.args.get("year", default=MAX_YEAR, type=int)

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
# TEAM HISTORY – DB-backed (TeamHistoryAgg), with rebuild on demand
# ---------------------------------------------------------------------------

@analysis_bp.route("/team-history")
def team_history_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = _bool_arg("refresh", False)

    if team_id is None:
        return jsonify({"error": "Missing required parameter 'teamId'", "year": year}), 400

    categories = CATEGORIES[:]  # canonical list

    session = SessionLocal()
    try:
        if refresh:
            rebuild_team_history_agg(session, year=year, team_id=team_id, force=True)
            session.commit()

        payload = get_team_history_from_agg(session, year=year, team_id=team_id, categories=categories)

        if not payload.get("history"):
            rebuild_team_history_agg(session, year=year, team_id=team_id, force=True)
            session.commit()
            payload = get_team_history_from_agg(session, year=year, team_id=team_id, categories=categories)

        payload["source"] = "db_team_history_agg"
        return jsonify(payload)

    except Exception as e:
        session.rollback()
        return jsonify(
            {
                "year": year,
                "teamId": team_id,
                "teamName": "",
                "history": [],
                "source": "db_team_history_agg_error",
                "error": "Failed to load team history",
                "details": str(e),
            }
        ), 500
    finally:
        session.close()


# ---------------------------------------------------------------------------
# OPPONENT ENDPOINTS – cached/legacy, but safe bool parsing
# ---------------------------------------------------------------------------

@analysis_bp.route("/opponent-matrix")
def opponent_matrix_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)

    start_year = request.args.get("startYear", type=int)
    end_year = request.args.get("endYear", type=int)
    team_id = request.args.get("teamId", type=int)

    refresh = _bool_arg("refresh", False) or _bool_arg("forceRefresh", False)
    era_only = _bool_arg("currentOwnerEraOnly", False)

    # normalize range
    if start_year is None and end_year is None:
        start_year = year
        end_year = year
    else:
        if start_year is None:
            start_year = year
        if end_year is None:
            end_year = start_year
        if end_year < start_year:
            start_year, end_year = end_year, start_year

    # owner-era clamp (only makes sense when teamId provided)
    if era_only and team_id is not None:
        owner_start = get_owner_start_year(int(team_id))
        if owner_start:
            start_year = max(int(start_year), int(owner_start))

    session = SessionLocal()
    try:
        # If caller asked for refresh, rebuild agg table rows for years in range (optional).
        # I recommend: do NOT auto-rebuild here (keep scripts doing rebuilds), unless you want it.
        # We'll ignore refresh in-route for now.

        q = session.query(OpponentMatrixAggYear).filter(
            OpponentMatrixAggYear.league_id == LEAGUE_ID,
            OpponentMatrixAggYear.year >= int(start_year),
            OpponentMatrixAggYear.year <= int(end_year),
        )
        if team_id is not None:
            q = q.filter(OpponentMatrixAggYear.team_id == int(team_id))

        db_rows = q.all()

        if db_rows:
            ui_rows = [_row_to_ui_shape(r) for r in db_rows]

            # If range spans multiple years, merge rows by opponent
            if int(start_year) != int(end_year):
                ui_rows = _merge_ui_rows(ui_rows)

            return jsonify(
                {
                    "year": int(year),
                    "startYear": int(start_year),
                    "endYear": int(end_year),
                    "teamId": int(team_id) if team_id is not None else None,
                    "rows": ui_rows,
                    "source": "db_opponent_matrix_agg_year",
                }
            )

        # DB empty → fallback to legacy cached compute (optional)
        payload = get_opponent_matrix_multi_cached(
            int(start_year),
            int(end_year),
            current_owner_era_only=era_only,
            force_refresh=refresh,
        )

        rows = payload.get("rows", []) or []
        if team_id is not None:
            rows = [r for r in rows if int(r.get("teamId", 0)) == int(team_id)]

        return jsonify(
            {
                "year": int(year),
                "startYear": int(payload.get("startYear", start_year)),
                "endYear": int(payload.get("endYear", end_year)),
                "teamId": int(team_id) if team_id is not None else None,
                "rows": rows,
                "source": payload.get("source", "espn_cached_fallback"),
            }
        )

    except Exception as e:
        session.rollback()
        return jsonify(
            {
                "year": year,
                "startYear": start_year,
                "endYear": end_year,
                "teamId": team_id,
                "rows": [],
                "source": "opponent_matrix_error",
                "error": "Failed to compute opponent matrix",
                "details": str(e),
            }
        ), 500
    finally:
        session.close()


@analysis_bp.route("/opponent-zdiff")
def opponent_zdiff_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    team_id = request.args.get("teamId", type=int)
    refresh = _bool_arg("refresh", False)

    try:
        payload = get_opponent_zdiff_matrix_cached(year, force_refresh=refresh)
        rows = payload.get("rows", []) or []
        if team_id is not None:
            rows = [r for r in rows if int(r.get("teamId", 0)) == int(team_id)]
        return jsonify({"year": year, "teamId": team_id, "rows": rows})
    except Exception as e:
        return jsonify({"year": year, "teamId": team_id, "rows": [], "error": "Failed to compute opponent z-diff matrix", "details": str(e)}), 500


@analysis_bp.route("/opponent-matrix-multi")
def opponent_matrix_multi_api():
    start_year = request.args.get("startYear", default=2019, type=int)
    end_year = request.args.get("endYear", default=MAX_YEAR, type=int)
    team_id = request.args.get("teamId", type=int)

    owner_era_only = request.args.get("currentOwnerEraOnly", default="false")
    owner_era_only = str(owner_era_only).lower() in ("1", "true", "yes", "y")

    # if you want refresh to trigger a rebuild script later, keep it;
    # for now we ignore it because agg is rebuilt by script
    _ = request.args.get("forceRefresh", default="false")

    if team_id is None:
        return jsonify({"minYear": start_year, "maxYear": end_year, "rows": [], "error": "Missing teamId"}), 400

    session = SessionLocal()
    try:
        payload = get_opponent_matrix_from_agg_year(
            session,
            start_year=int(start_year),
            end_year=int(end_year),
            selected_espn_team_id=int(team_id),
            current_owner_era_only=bool(owner_era_only),
        )
        payload["teamId"] = int(team_id)
        payload["ownerEraOnly"] = bool(owner_era_only)
        payload["source"] = "db_opponent_matrix_agg_year"
        return jsonify(payload)
    finally:
        session.close()