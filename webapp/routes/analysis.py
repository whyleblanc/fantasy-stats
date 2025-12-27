from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import func, text, tuple_

from analysis import (
    get_opponent_matrix_cached,
    get_opponent_matrix_multi_cached,
    get_opponent_zdiff_matrix_cached,
)
from analysis.constants import CATEGORIES, CAT_TO_DB_COL
from analysis.owners import build_owners_map
from analysis.owners import get_owner_start_year
from models_aggregates import TeamHistoryAgg, OpponentMatrixAggYear

from db import SessionLocal, WeekTeamStats, SeasonTeamMetrics
from models_normalized import StatWeekly, Team, Matchup, StatSeason
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


def _resolve_team_db_id(session, league_id: int, year: int, espn_team_id: int) -> Optional[int]:
    """
    Map (league_id, season/year, espn_team_id) -> teams.id (DB PK).
    """
    return (
        session.query(Team.id)
        .filter(
            Team.league_id == int(league_id),
            Team.season == int(year),
            Team.espn_team_id == int(espn_team_id),
        )
        .scalar()
    )


def _season_raw_from_weekly(session, league_id: int, season: int, team_db_id: int, cat_col: str):
    """
    Returns the raw season value for a category by aggregating stats_weekly.

    cat_col is one of: fg_pct, ft_pct, tpm, reb, ast, stl, blk, dd, pts
    """
    q = session.query(StatWeekly).filter(
        StatWeekly.league_id == int(league_id),
        StatWeekly.season == int(season),
        StatWeekly.team_id == int(team_db_id),
    )

    if cat_col == "fg_pct":
        fgm, fga = q.with_entities(func.sum(StatWeekly.fgm), func.sum(StatWeekly.fga)).one()
        if fga and float(fga) != 0:
            return float(fgm) / float(fga)

        # fallback: average weekly fg_pct if present
        avg_fg = q.with_entities(func.avg(StatWeekly.fg_pct)).scalar()
        return float(avg_fg) if avg_fg is not None else None

    if cat_col == "ft_pct":
        ftm, fta = q.with_entities(func.sum(StatWeekly.ftm), func.sum(StatWeekly.fta)).one()
        if fta and float(fta) != 0:
            return float(ftm) / float(fta)

        # fallback: average weekly ft_pct if present
        avg_ft = q.with_entities(func.avg(StatWeekly.ft_pct)).scalar()
        return float(avg_ft) if avg_ft is not None else None

    # counting stats
    col = getattr(StatWeekly, cat_col, None)
    if col is None:
        return None

    total = q.with_entities(func.sum(col)).scalar()
    return float(total) if total is not None else None


def _weekly_stats_unreliable(session, league_id: int, season: int) -> bool:
    """
    Heuristic: if most teams have identical PTS across weeks, the weekly table is likely duplicated season totals.
    """
    # sample a handful of teams to keep it fast
    team_ids = [
        r[0]
        for r in session.query(StatWeekly.team_id)
        .filter(
            StatWeekly.league_id == int(league_id),
            StatWeekly.season == int(season),
        )
        .distinct()
        .limit(10)
        .all()
    ]
    if not team_ids:
        return False

    constant_count = 0
    for tid in team_ids:
        distinct_pts = (
            session.query(func.count(func.distinct(StatWeekly.pts)))
            .filter(
                StatWeekly.league_id == int(league_id),
                StatWeekly.season == int(season),
                StatWeekly.team_id == int(tid),
            )
            .scalar()
            or 0
        )
        # if it's 1, pts is identical every week for that team
        if distinct_pts <= 1:
            constant_count += 1

    # if most sampled teams are constant => unreliable
    return constant_count >= max(6, int(len(team_ids) * 0.7))


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


def _meta_for_season(session, season: int) -> dict:
    weeks = _completed_weeks_from_matchups(session, int(season))
    return {
        "season": int(season),
        "weeksIncluded": weeks,
        "isPartial": True if weeks else False,
        "latestWeek": max(weeks) if weeks else None,
    }


def _meta_for_range(session, start_year: int, end_year: int) -> dict:
    start_year, end_year = int(start_year), int(end_year)
    years = list(range(start_year, end_year + 1))
    latest_by_year = {y: _meta_for_season(session, y)["latestWeek"] for y in years}
    return {
        "startYear": start_year,
        "endYear": end_year,
        "years": years,
        "latestWeekByYear": latest_by_year,
        "isRange": True,
    }


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
        payload["meta"] = _meta_for_season(session, year)
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
                    "meta": _meta_for_range(session, int(start_year), int(end_year)),
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
                "meta": _meta_for_range(session, int(payload.get("startYear", start_year)),
                               int(payload.get("endYear", end_year))),
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


@analysis_bp.route("/awards")
def awards_api():
    """
    /api/analysis/awards?scope=league|team|owner&year=2026|all_time
      &teamId=1
      &ownerCode=MATTEO
      &currentOwnerEraOnly=true|false
      &mode=summary|year_by_year
    """
    scope = request.args.get("scope", default="league", type=str)
    mode = request.args.get("mode", default="summary", type=str)

    year_raw = request.args.get("year", default=str(MAX_YEAR))
    team_id = request.args.get("teamId", type=int)
    owner_code = request.args.get("ownerCode", type=str)
    owner_era_only = _bool_arg("currentOwnerEraOnly", True)

    # owner options (current owners only)
    from analysis.owners import CURRENT_OWNERS_2025, OWNER_START_YEAR, get_owner_start_year

    owners = [
        {
            "ownerCode": code,
            "teamId": int(tid),
            "startYear": int(OWNER_START_YEAR.get(int(tid), MAX_YEAR)),
        }
        for tid, code in CURRENT_OWNERS_2025.items()
    ]
    owners.sort(key=lambda o: o["ownerCode"])

    session = SessionLocal()
    try:
        # DB-available min/max years driven by week_team_stats
        min_db_year = session.query(func.min(WeekTeamStats.year)).filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.is_league_average == False,
        ).scalar()
        max_db_year = session.query(func.max(WeekTeamStats.year)).filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.is_league_average == False,
        ).scalar()

        min_db_year = int(min_db_year) if min_db_year is not None else int(MAX_YEAR)
        max_db_year = int(max_db_year) if max_db_year is not None else int(MAX_YEAR)

        if str(year_raw).lower() == "all_time":
            year_int = None
            start_year = min_db_year
            end_year = max_db_year
        else:
            year_int = int(year_raw)
            start_year = year_int
            end_year = year_int

        # If scope=owner, resolve teamId from ownerCode
        if scope == "owner":
            if not owner_code:
                return jsonify({"error": "Missing ownerCode for scope=owner"}), 400
            owner_team_ids = [o["teamId"] for o in owners if o["ownerCode"] == owner_code]
            if not owner_team_ids:
                return jsonify({"error": f"Unknown ownerCode={owner_code}"}), 400
            team_id = int(owner_team_ids[0])

        payload = {
            "scope": scope,
            "mode": mode,
            "filters": {
                "year": "all_time" if year_int is None else int(year_int),
                "startYear": int(start_year),
                "endYear": int(end_year),
                "teamId": int(team_id) if team_id is not None else None,
                "ownerCode": owner_code,
                "currentOwnerEraOnly": bool(owner_era_only),
            },
            "owners": owners,
            "awards": {
                "season": [],
                "week": [],
                "category_week": [],
                "category_season": [],
                "opponent": [],
                "luck": [],
            },
            "meta": {
                "yearsAvailable": list(range(min_db_year, max_db_year + 1)),
                "notes": [
                    "Week extremes use week_team_stats.total_z (ties supported).",
                    "Season extremes use season_team_metrics.sum_total_z (ties supported).",
                    "Owner scope uses current owner mapping only; historical owner-team changes are not modeled.",
                ],
            },
            "source": "db_awards_week_and_season_extremes_v1",
        }
        payload["meta"]["weeklyRawReliableByYear"] = {
            str(y): (not _weekly_stats_unreliable(session, LEAGUE_ID, y))
            for y in range(int(start_year), int(end_year) + 1)
        }

        # ----------------------------
        # Build shared filters
        # ----------------------------

        # WEEK BASE (WeekTeamStats)
        week_base = session.query(WeekTeamStats).filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.is_league_average == False,
            WeekTeamStats.year >= int(start_year),
            WeekTeamStats.year <= int(end_year),
        )

        # ----------------------------
        # Restrict WEEK awards to completed matchup weeks only
        # (prevents future/cumulative weeks from polluting e.g. 2026)
        # ----------------------------
        completed_pairs = (
            session.query(Matchup.season, Matchup.week)
            .filter(
                Matchup.league_id == LEAGUE_ID,
                Matchup.season >= int(start_year),
                Matchup.season <= int(end_year),
                Matchup.winner_team_id.isnot(None),
            )
            .distinct()
            .all()
        )

        if completed_pairs:
            week_base = week_base.filter(
                tuple_(WeekTeamStats.year, WeekTeamStats.week).in_(completed_pairs)
            )
        else:
            # Safety: no completed weeks → no weekly awards
            week_base = week_base.filter(text("1=0"))

        # SEASON BASE (SeasonTeamMetrics)
        season_base = session.query(SeasonTeamMetrics).filter(
            SeasonTeamMetrics.league_id == LEAGUE_ID,
            SeasonTeamMetrics.year >= int(start_year),
            SeasonTeamMetrics.year <= int(end_year),
        )

        # After week_base is restricted to completed weeks, also protect season awards
        # by excluding "partial" seasons from SeasonTeamMetrics.
        # Partial = week_team_stats has weeks beyond completed matchup weeks.

        completed_max_by_year = dict(
            session.query(Matchup.season, func.max(Matchup.week))
            .filter(
                Matchup.league_id == LEAGUE_ID,
                Matchup.season >= int(start_year),
                Matchup.season <= int(end_year),
                Matchup.winner_team_id.isnot(None),
            )
            .group_by(Matchup.season)
            .all()
        )

        wts_max_by_year = dict(
            session.query(WeekTeamStats.year, func.max(WeekTeamStats.week))
            .filter(
                WeekTeamStats.league_id == LEAGUE_ID,
                WeekTeamStats.is_league_average == False,
                WeekTeamStats.year >= int(start_year),
                WeekTeamStats.year <= int(end_year),
            )
            .group_by(WeekTeamStats.year)
            .all()
        )

        partial_years = [
            int(y) for y in wts_max_by_year
            if completed_max_by_year.get(int(y)) is not None
            and int(wts_max_by_year[int(y)] or 0) > int(completed_max_by_year[int(y)] or 0)
        ]

        # Only matters for all_time comparisons
        if str(year_raw).lower() == "all_time" and partial_years:
            season_base = season_base.filter(~SeasonTeamMetrics.year.in_(partial_years))

        # Apply team/owner filters (but NOT to league by default)
        if scope in ("team", "owner"):
            if team_id is None:
                return jsonify({"error": "Missing teamId (or ownerCode) for scope=team|owner"}), 400

            week_base = week_base.filter(WeekTeamStats.team_id == int(team_id))
            season_base = season_base.filter(SeasonTeamMetrics.team_id == int(team_id))

            # Apply owner-era-only: drop seasons before start year for that team
            if owner_era_only:
                start = get_owner_start_year(int(team_id))
                if start is not None:
                    week_base = week_base.filter(WeekTeamStats.year >= int(start))
                    season_base = season_base.filter(SeasonTeamMetrics.year >= int(start))

        # ----------------------------
        # Helpers: ties for max/min
        # ----------------------------

        def award_week_extreme(q, kind: str):
            agg = func.max if kind == "max" else func.min
            extreme = q.with_entities(agg(func.round(WeekTeamStats.total_z, 6))).scalar()
            if extreme is None:
                return None

            rows = (
                q.filter(func.round(WeekTeamStats.total_z, 6) == float(extreme))
                .with_entities(
                    WeekTeamStats.year,
                    WeekTeamStats.week,
                    WeekTeamStats.team_id,
                    WeekTeamStats.team_name,
                    WeekTeamStats.total_z,
                )
                .order_by(
                    WeekTeamStats.year.desc(),
                    WeekTeamStats.week.desc(),
                    WeekTeamStats.team_id.asc(),
                )
                .all()
            )
            return (float(extreme), rows)


        def award_season_extreme(q, kind: str):
            agg = func.max if kind == "max" else func.min
            extreme = q.with_entities(agg(func.round(SeasonTeamMetrics.sum_total_z, 6))).scalar()
            if extreme is None:
                return None

            rows = (
                q.filter(func.round(SeasonTeamMetrics.sum_total_z, 6) == float(extreme))
                .with_entities(
                    SeasonTeamMetrics.year,
                    SeasonTeamMetrics.team_id,
                    func.max(SeasonTeamMetrics.team_name).label("team_name"),
                    SeasonTeamMetrics.sum_total_z,
                )
                .group_by(
                    SeasonTeamMetrics.year,
                    SeasonTeamMetrics.team_id,
                    SeasonTeamMetrics.sum_total_z,
                )
                .order_by(
                    SeasonTeamMetrics.year.desc(),
                    SeasonTeamMetrics.team_id.asc(),
                )
                .all()
            )
            return (float(extreme), rows)
        
        def award_season_metric_extreme(q, metric_col, kind: str):
            agg = func.max if kind == "max" else func.min
            extreme = q.with_entities(agg(func.round(metric_col, 6))).scalar()
            if extreme is None:
                return None

            rows = (
                q.filter(func.round(metric_col, 6) == float(extreme))
                .with_entities(
                    SeasonTeamMetrics.year,
                    SeasonTeamMetrics.team_id,
                    func.max(SeasonTeamMetrics.team_name).label("team_name"),
                    SeasonTeamMetrics.actual_win_pct,
                    SeasonTeamMetrics.expected_win_pct,
                    SeasonTeamMetrics.luck_index,
                )
                .group_by(
                    SeasonTeamMetrics.year,
                    SeasonTeamMetrics.team_id,
                    SeasonTeamMetrics.actual_win_pct,
                    SeasonTeamMetrics.expected_win_pct,
                    SeasonTeamMetrics.luck_index,
                )
                .order_by(SeasonTeamMetrics.year.desc(), SeasonTeamMetrics.team_id.asc())
                .all()
            )
            return (float(extreme), rows)


        def build_luck_awards(season_q):
            out = []

            best = award_season_metric_extreme(season_q, SeasonTeamMetrics.luck_index, "max")
            worst = award_season_metric_extreme(season_q, SeasonTeamMetrics.luck_index, "min")

            if best:
                _, rows = best
                out.append({
                    "id": "best_luck_index",
                    "label": "Best Luck (actual − expected)",
                    "winners": [
                        {
                            "year": int(r.year),
                            "teamId": int(r.team_id),
                            "teamName": r.team_name,
                            "value": float(r.luck_index) if r.luck_index is not None else None,
                            "actualWinPct": float(r.actual_win_pct) if r.actual_win_pct is not None else None,
                            "expectedWinPct": float(r.expected_win_pct) if r.expected_win_pct is not None else None,
                        }
                        for r in rows
                    ],
                })

            if worst:
                _, rows = worst
                out.append({
                    "id": "worst_luck_index",
                    "label": "Worst Luck (actual − expected)",
                    "winners": [
                        {
                            "year": int(r.year),
                            "teamId": int(r.team_id),
                            "teamName": r.team_name,
                            "value": float(r.luck_index) if r.luck_index is not None else None,
                            "actualWinPct": float(r.actual_win_pct) if r.actual_win_pct is not None else None,
                            "expectedWinPct": float(r.expected_win_pct) if r.expected_win_pct is not None else None,
                        }
                        for r in rows
                    ],
                })

            return out
        
        # ----------------------------
        # Raw value mapping (for display next to Z)
        # ----------------------------

        CATEGORY_TO_WEEKLY_COL = {
            "fg": "fg_pct",         # StatWeekly.fg_pct
            "ft": "ft_pct",         # StatWeekly.ft_pct
            "three_pm": "tpm",      # StatWeekly.tpm
            "reb": "reb",
            "ast": "ast",
            "stl": "stl",
            "blk": "blk",
            "dd": "dd",
            "pts": "pts",
        }

        CATEGORY_TO_SEASON_COL = {
            "fg": "fg_pct",         # StatSeason.fg_pct
            "ft": "ft_pct",         # StatSeason.ft_pct
            "three_pm": "tpm",      # StatSeason.tpm
            "reb": "reb",
            "ast": "ast",
            "stl": "stl",
            "blk": "blk",
            "dd": "dd",
            "pts": "pts",
        }

        def _extract_cat_key_from_award_id(award_id: str) -> str | None:
            # examples: best_week_fg_z, worst_week_pts_z, best_season_three_pm_z
            if not award_id:
                return None
            parts = award_id.lower().split("_")
            # last token is "z"
            # pattern: best|worst _ week|season _ <cat...> _ z
            if len(parts) < 4:
                return None
            return "_".join(parts[2:-1])  # cat portion (fg / three_pm / pts / etc.)

        def _resolve_team_db_ids(session, league_id: int, year_to_espn_team_ids: dict[int, set[int]]) -> dict[tuple[int, int], int]:
            """
            Bulk map (year, espn_team_id) -> Team.id (DB PK)
            Uses Team.season as the year.
            """
            if not year_to_espn_team_ids:
                return {}

            # flatten for query
            years = sorted(year_to_espn_team_ids.keys())
            espn_ids_all = sorted({tid for s in year_to_espn_team_ids.values() for tid in s})

            rows = (
                session.query(Team.season, Team.espn_team_id, Team.id)
                .filter(
                    Team.league_id == int(league_id),
                    Team.season.in_(years),
                    Team.espn_team_id.in_(espn_ids_all),
                )
                .all()
            )

            out = {}
            for season, espn_team_id, team_db_id in rows:
                out[(int(season), int(espn_team_id))] = int(team_db_id)
            return out


        def enrich_category_week_awards_with_raw(session, league_id: int, category_awards: list):
            """
            category_awards: list of award dicts, each with .id and winners list (year/week/teamId=ESPN)
            Adds winners[*].rawValue and winners[*].teamDbId
            """

            if not isinstance(category_awards, list) or not category_awards:
                return category_awards

            # 1) collect needed (year, week, espn_team_id)
            y_w_t = set()
            year_to_teamids = {}
            for a in category_awards:
                for w in a.get("winners", []) or []:
                    y = w.get("year")
                    wk = w.get("week")
                    tid = w.get("teamId")  # ESPN team id
                    if y is None or wk is None or tid is None:
                        continue
                    y = int(y)
                    tid = int(tid)
                    wk = int(wk)

                    y_w_t.add((y, wk, tid))
                    year_to_teamids.setdefault(y, set()).add(tid)

            if not y_w_t:
                return category_awards

            # 2) bulk resolve teamDbId for those (year, espn_team_id)
            map_year_espn_to_db = _resolve_team_db_ids(session, int(league_id), year_to_teamids)

            # 3) build the DB query keys (year, week, team_db_id)
            db_keys = set()
            for (y, wk, espn_tid) in y_w_t:
                team_db_id = map_year_espn_to_db.get((y, espn_tid))
                if team_db_id is not None:
                    db_keys.add((y, wk, int(team_db_id)))

            if not db_keys:
                # still attach teamDbId=None / rawValue=None so frontend is consistent
                for a in category_awards:
                    for w in a.get("winners", []) or []:
                        w.setdefault("teamDbId", None)
                        w["rawValue"] = None
                return category_awards

            years = {k[0] for k in db_keys}
            weeks = {k[1] for k in db_keys}
            team_db_ids = {k[2] for k in db_keys}

            rows = (
                session.query(StatWeekly)
                .filter(
                    StatWeekly.league_id == int(league_id),
                    StatWeekly.season.in_(list(years)),
                    StatWeekly.week.in_(list(weeks)),
                    StatWeekly.team_id.in_(list(team_db_ids)),
                )
                .all()
            )

            by_key = {(int(r.season), int(r.week), int(r.team_id)): r for r in rows}

            # 4) attach rawValue per winner
            for a in category_awards:
                cat_key = _extract_cat_key_from_award_id(a.get("id", ""))
                col = CATEGORY_TO_WEEKLY_COL.get(cat_key)
                if not col:
                    continue

                for w in a.get("winners", []) or []:
                    y = w.get("year")
                    wk = w.get("week")
                    espn_tid = w.get("teamId")
                    if y is None or wk is None or espn_tid is None:
                        w["rawValue"] = None
                        w.setdefault("teamDbId", None)
                        continue

                    y = int(y)
                    wk = int(wk)
                    espn_tid = int(espn_tid)

                    team_db_id = map_year_espn_to_db.get((y, espn_tid))
                    w["teamDbId"] = int(team_db_id) if team_db_id is not None else None

                    if team_db_id is None:
                        w["rawValue"] = None
                        continue

                    r = by_key.get((y, wk, int(team_db_id)))
                    v = getattr(r, col, None) if r is not None else None
                    w["rawValue"] = float(v) if v is not None else None

            return category_awards


        def enrich_category_season_awards_with_raw(session, league_id: int, category_awards: list):
            """
            category_awards: list of award dicts, each with .id and winners list (year/teamId=ESPN)
            Adds winners[*].rawValue and winners[*].teamDbId
            """

            if not isinstance(category_awards, list) or not category_awards:
                return category_awards

            # 1) collect needed (year, espn_team_id)
            y_t = set()
            year_to_teamids = {}
            for a in category_awards:
                for w in a.get("winners", []) or []:
                    y = w.get("year")
                    tid = w.get("teamId")  # ESPN team id
                    if y is None or tid is None:
                        continue
                    y = int(y)
                    tid = int(tid)
                    y_t.add((y, tid))
                    year_to_teamids.setdefault(y, set()).add(tid)

            if not y_t:
                return category_awards

            # 2) resolve (year, espn_team_id) -> teamDbId
            map_year_espn_to_db = _resolve_team_db_ids(session, int(league_id), year_to_teamids)

            db_keys = set()
            for (y, espn_tid) in y_t:
                team_db_id = map_year_espn_to_db.get((y, espn_tid))
                if team_db_id is not None:
                    db_keys.add((y, int(team_db_id)))

            if not db_keys:
                for a in category_awards:
                    for w in a.get("winners", []) or []:
                        w.setdefault("teamDbId", None)
                        w["rawValue"] = None
                return category_awards

            years = {k[0] for k in db_keys}
            team_db_ids = {k[1] for k in db_keys}

            rows = (
                session.query(StatSeason)
                .filter(
                    StatSeason.league_id == int(league_id),
                    StatSeason.season.in_(list(years)),
                    StatSeason.team_id.in_(list(team_db_ids)),
                )
                .all()
            )

            by_key = {(int(r.season), int(r.team_id)): r for r in rows}

            # 3) attach rawValue
            for a in category_awards:
                cat_key = _extract_cat_key_from_award_id(a.get("id", ""))
                col = CATEGORY_TO_SEASON_COL.get(cat_key)
                if not col:
                    continue

                for w in a.get("winners", []) or []:
                    y = w.get("year")
                    espn_tid = w.get("teamId")
                    if y is None or espn_tid is None:
                        w["rawValue"] = None
                        w.setdefault("teamDbId", None)
                        continue

                    y = int(y)
                    espn_tid = int(espn_tid)

                    team_db_id = map_year_espn_to_db.get((y, espn_tid))
                    w["teamDbId"] = int(team_db_id) if team_db_id is not None else None

                    if team_db_id is None:
                        w["rawValue"] = None
                        continue

                    r = by_key.get((y, int(team_db_id)))

                    v = getattr(r, col, None) if r is not None else None

                    # If stats_season is missing/empty, compute from stats_weekly instead
                    if v is None:
                        v = _season_raw_from_weekly(session, int(league_id), y, int(team_db_id), col)

                    w["rawValue"] = float(v) if v is not None else None

            return category_awards
        
        # ----------------------------
        # Awards V1: Category Week Extremes (z-score) with ties
        # ----------------------------

        CAT_WEEK_DEFS = [
            {"id": "best_week_fg_z", "label": "Best Week (FG% Z)", "col": WeekTeamStats.fg_z},
            {"id": "best_week_ft_z", "label": "Best Week (FT% Z)", "col": WeekTeamStats.ft_z},
            {"id": "best_week_three_pm_z", "label": "Best Week (3PM Z)", "col": WeekTeamStats.three_pm_z},
            {"id": "best_week_reb_z", "label": "Best Week (REB Z)", "col": WeekTeamStats.reb_z},
            {"id": "best_week_ast_z", "label": "Best Week (AST Z)", "col": WeekTeamStats.ast_z},
            {"id": "best_week_stl_z", "label": "Best Week (STL Z)", "col": WeekTeamStats.stl_z},
            {"id": "best_week_blk_z", "label": "Best Week (BLK Z)", "col": WeekTeamStats.blk_z},
            {"id": "best_week_dd_z", "label": "Best Week (DD Z)", "col": WeekTeamStats.dd_z},
            {"id": "best_week_pts_z", "label": "Best Week (PTS Z)", "col": WeekTeamStats.pts_z},
        ]

        CAT_WEEK_DEFS_WORST = [
            {"id": d["id"].replace("best_", "worst_"), "label": d["label"].replace("Best", "Worst"), "col": d["col"]}
            for d in CAT_WEEK_DEFS
        ]

        # Category Z columns in week_team_stats
        CATEGORY_Z_COLS = [
            ("FG%", "fg_z"),
            ("FT%", "ft_z"),
            ("3PM", "three_pm_z"),
            ("REB", "reb_z"),
            ("AST", "ast_z"),
            ("STL", "stl_z"),
            ("BLK", "blk_z"),
            ("DD", "dd_z"),
            ("PTS", "pts_z"),
        ]

        CATEGORY_Z_FIELDS = [
            ("FG%", "fg_z"),
            ("FT%", "ft_z"),
            ("3PM", "three_pm_z"),
            ("REB", "reb_z"),
            ("AST", "ast_z"),
            ("STL", "stl_z"),
            ("BLK", "blk_z"),
            ("DD", "dd_z"),
            ("PTS", "pts_z"),
        ]

        def _score_matchup_by_categories(teamA_row: WeekTeamStats, teamB_row: WeekTeamStats):
            winsA = winsB = ties = 0
            per_cat = {}
            assert hasattr(teamA_row, "fg_z") and hasattr(teamA_row, "three_pm_z"), "WeekTeamStats z fields missing"

            for label, field in CATEGORY_Z_FIELDS:
                a = getattr(teamA_row, field, None)
                b = getattr(teamB_row, field, None)

                if a is None or b is None:
                    ties += 1
                    per_cat[label] = "T"
                    continue

                ar = round(float(a), 6)
                br = round(float(b), 6)

                if ar > br:
                    winsA += 1
                    per_cat[label] = "A"
                elif br > ar:
                    winsB += 1
                    per_cat[label] = "B"
                else:
                    ties += 1
                    per_cat[label] = "T"

            return winsA, winsB, ties, (winsA - winsB), per_cat
        
        def _flip_per_category(per_cat: dict) -> dict:
            # Convert A/B from "teamA/teamB" perspective to winner perspective
            out = {}
            for k, v in (per_cat or {}).items():
                if v == "A":
                    out[k] = "B"
                elif v == "B":
                    out[k] = "A"
                else:
                    out[k] = v  # "T" or anything unexpected
            return out


        # ----------------------------
        # Opponent awards (by category winners using WeekTeamStats z-fields)
        # ----------------------------

        def _pick_matchup_team_cols():
            if hasattr(Matchup, "home_team_id") and hasattr(Matchup, "away_team_id"):
                return Matchup.home_team_id, Matchup.away_team_id
            raise RuntimeError("Expected Matchup.home_team_id and Matchup.away_team_id")

        def build_opponent_awards_for_range(start_y: int, end_y: int, only_team_id: Optional[int] = None):
            team_col_a, team_col_b = _pick_matchup_team_cols()

            mq = (
                session.query(
                    Matchup.season.label("year"),
                    Matchup.week.label("week"),
                    team_col_a.label("teamA_id"),
                    team_col_b.label("teamB_id"),
                    Matchup.winner_team_id.label("winner_id"),
                )
                .filter(
                    Matchup.league_id == LEAGUE_ID,
                    Matchup.season >= int(start_y),
                    Matchup.season <= int(end_y),
                    Matchup.winner_team_id.isnot(None),
                )
            )

            if only_team_id is not None:
                mq = mq.filter((team_col_a == int(only_team_id)) | (team_col_b == int(only_team_id)))

            matchups = mq.all()
            if not matchups:
                return []

            needed = set()
            for m in matchups:
                if m.teamA_id is not None:
                    needed.add((int(m.year), int(m.week), int(m.teamA_id)))
                if m.teamB_id is not None:
                    needed.add((int(m.year), int(m.week), int(m.teamB_id)))

            years = sorted({k[0] for k in needed})
            weeks = sorted({k[1] for k in needed})
            team_ids = sorted({k[2] for k in needed})

            wrows = (
                session.query(WeekTeamStats)
                .filter(
                    WeekTeamStats.league_id == LEAGUE_ID,
                    WeekTeamStats.is_league_average == False,
                    WeekTeamStats.year.in_(years),
                    WeekTeamStats.week.in_(weeks),
                    WeekTeamStats.team_id.in_(team_ids),
                )
                .all()
            )
            wmap = {(int(r.year), int(r.week), int(r.team_id)): r for r in wrows}

            scored = []
            for m in matchups:
                y = int(m.year)
                wk = int(m.week)
                a_id = int(m.teamA_id)
                b_id = int(m.teamB_id)

                a = wmap.get((y, wk, a_id))
                b = wmap.get((y, wk, b_id))
                if a is None or b is None:
                    continue

                winsA, winsB, ties, marginA, per_cat = _score_matchup_by_categories(a, b)

                winner_id = int(m.winner_id)
                if winner_id == a_id:
                    winner, loser = a, b
                    w_wins, l_wins = winsA, winsB
                    w_margin = marginA
                    w_per_cat = per_cat
                else:
                    winner, loser = b, a
                    w_wins, l_wins = winsB, winsA
                    w_margin = -marginA
                    w_per_cat = _flip_per_category(per_cat)

                scored.append(
                    {
                        "year": y,
                        "week": wk,
                        "teamId": int(winner.team_id),
                        "teamName": winner.team_name,
                        "opponentTeamId": int(loser.team_id),
                        "opponentName": loser.team_name,
                        "winnerTotalZ": float(winner.total_z or 0.0),
                        "loserTotalZ": float(loser.total_z or 0.0),
                        "wins": int(w_wins),
                        "losses": int(l_wins),
                        "ties": int(ties),
                        "margin": int(w_margin),
                        "score": f"{int(w_wins)}-{int(l_wins)}-{int(ties)}",
                        "perCategory": w_per_cat,
                    }
                )

            if not scored:
                return []

            def pick_one(key_fn, reverse=False):
                return sorted(scored, key=key_fn, reverse=reverse)[0]

            closest = pick_one(lambda r: (abs(r["margin"]), -r["ties"], -r["year"], -r["week"]), reverse=False)
            blowout = pick_one(lambda r: (abs(r["margin"]), r["year"], r["week"]), reverse=True)
            most_ties = pick_one(lambda r: (r["ties"], -abs(r["margin"]), r["year"], r["week"]), reverse=True)

            upsets = [r for r in scored if (r["winnerTotalZ"] < r["loserTotalZ"])]
            biggest_upset = None
            if upsets:
                biggest_upset = sorted(
                    upsets,
                    key=lambda r: ((r["loserTotalZ"] - r["winnerTotalZ"]), r["year"], r["week"]),
                    reverse=True,
                )[0]

            out = [
                {"id": "closest_matchup", "label": "Closest Matchup (by categories)", "winners": [closest]},
                {"id": "biggest_blowout", "label": "Biggest Blowout (by categories)", "winners": [blowout]},
                {"id": "most_ties", "label": "Most Tied Categories (single matchup)", "winners": [most_ties]},
            ]
            if biggest_upset:
                out.append({"id": "biggest_upset", "label": "Biggest Upset (lower Total Z wins)", "winners": [biggest_upset]})

            return out


        def build_category_season_awards(week_base_q):
            """
            Season-long category extremes using week_team_stats.

            For each category:
            - season_total = SUM(category_z) grouped by (year, team_id)
            - best = max(season_total), worst = min(season_total)
            - ties supported (rounded to 6dp)
            """
            awards = []

            for cat_label, col_name in CATEGORY_Z_COLS:
                col = getattr(WeekTeamStats, col_name)

                # Aggregate to season totals per team
                agg_rows = (
                    week_base_q.with_entities(
                        WeekTeamStats.year.label("year"),
                        WeekTeamStats.team_id.label("team_id"),
                        func.max(WeekTeamStats.team_name).label("team_name"),
                        func.round(func.sum(col), 6).label("season_cat_total"),
                    )
                    .group_by(WeekTeamStats.year, WeekTeamStats.team_id)
                    .all()
                )

                # Filter out None (just in case)
                vals = [r.season_cat_total for r in agg_rows if r.season_cat_total is not None]
                if not vals:
                    continue

                max_val = max(vals)
                min_val = min(vals)

                best_rows = [r for r in agg_rows if r.season_cat_total == max_val]
                worst_rows = [r for r in agg_rows if r.season_cat_total == min_val]

                awards.append({
                    "id": f"best_season_{col_name}",
                    "label": f"Best Season ({cat_label} Z Total)",
                    "winners": [
                        {
                            "year": int(r.year),
                            "teamId": int(r.team_id),
                            "teamDbId": int(r.team_id),
                            "teamName": r.team_name,
                            "value": float(r.season_cat_total),
                        }
                        for r in best_rows
                    ],
                })

                awards.append({
                    "id": f"worst_season_{col_name}",
                    "label": f"Worst Season ({cat_label} Z Total)",
                    "winners": [
                        {
                            "year": int(r.year),
                            "teamId": int(r.team_id),
                            "teamDbId": int(r.team_id),
                            "teamName": r.team_name,
                            "value": float(r.season_cat_total),
                        }
                        for r in worst_rows
                    ],
                })

            return awards

        def award_category_week_extreme(q, col, kind: str):
            agg = func.max if kind == "max" else func.min
            extreme = q.with_entities(agg(func.round(col, 6))).scalar()
            if extreme is None:
                return None

            rows = (
                q.filter(func.round(col, 6) == float(extreme))
                .with_entities(
                    WeekTeamStats.year,
                    WeekTeamStats.week,
                    WeekTeamStats.team_id,
                    WeekTeamStats.team_name,
                    col.label("value"),
                )
                .order_by(WeekTeamStats.year.desc(), WeekTeamStats.week.desc(), WeekTeamStats.team_id.asc())
                .all()
            )
            return (float(extreme), rows)

        def build_category_week_awards(q):
            out = []

            # best for each category
            for d in CAT_WEEK_DEFS:
                res = award_category_week_extreme(q, d["col"], "max")
                if not res:
                    continue
                _, rows = res
                out.append({
                    "id": d["id"],
                    "label": d["label"],
                    "winners": [
                        {
                            "year": int(r.year),
                            "week": int(r.week),
                            "teamId": int(r.team_id),
                            "teamDbId": int(r.team_id),
                            "teamName": r.team_name,
                            "value": float(r.value),
                        }
                        for r in rows
                    ],
                })

            # worst for each category
            for d in CAT_WEEK_DEFS_WORST:
                res = award_category_week_extreme(q, d["col"], "min")
                if not res:
                    continue
                _, rows = res
                out.append({
                    "id": d["id"],
                    "label": d["label"],
                    "winners": [
                        {
                            "year": int(r.year),
                            "week": int(r.week),
                            "teamId": int(r.team_id),
                            "teamDbId": int(r.team_id),
                            "teamName": r.team_name,
                            "value": float(r.value),
                        }
                        for r in rows
                    ],
                })

            return out

        # ----------------------------
        # mode=summary
        # ----------------------------
        if mode == "summary":
            week_awards = []
            best = award_week_extreme(week_base, "max")
            worst = award_week_extreme(week_base, "min")

            if best:
                _, rows = best
                week_awards.append({
                    "id": "best_week_total_z",
                    "label": "Best Week (Total Z)",
                    "winners": [
                        {"year": int(r.year), "week": int(r.week), "teamId": int(r.team_id), "teamName": r.team_name, "value": float(r.total_z)}
                        for r in rows
                    ],
                })

            if worst:
                _, rows = worst
                week_awards.append({
                    "id": "worst_week_total_z",
                    "label": "Worst Week (Total Z)",
                    "winners": [
                        {"year": int(r.year), "week": int(r.week), "teamId": int(r.team_id), "teamName": r.team_name, "value": float(r.total_z)}
                        for r in rows
                    ],
                })

            season_awards = []
            best_s = award_season_extreme(season_base, "max")
            worst_s = award_season_extreme(season_base, "min")

            if best_s:
                _, rows = best_s
                season_awards.append({
                    "id": "best_season_total_z",
                    "label": "Best Season (Total Z)",
                    "winners": [
                        {"year": int(r.year), "teamId": int(r.team_id), "teamName": r.team_name, "value": float(r.sum_total_z)}
                        for r in rows
                    ],
                })

            if worst_s:
                _, rows = worst_s
                season_awards.append({
                    "id": "worst_season_total_z",
                    "label": "Worst Season (Total Z)",
                    "winners": [
                        {"year": int(r.year), "teamId": int(r.team_id), "teamName": r.team_name, "value": float(r.sum_total_z)}
                        for r in rows
                    ],
                })

            payload["awards"]["week"] = week_awards
            payload["awards"]["season"] = season_awards
            payload["awards"]["category_week"] = build_category_week_awards(week_base)
            payload["awards"]["category_season"] = build_category_season_awards(week_base)
            payload["awards"]["category_season"] = enrich_category_season_awards_with_raw(
                session, LEAGUE_ID, payload["awards"]["category_season"]
            )
            payload["awards"]["luck"] = build_luck_awards(season_base)

            # Opponent awards (fail-soft)
            try:
                payload["awards"]["opponent"] = build_opponent_awards_for_range(
                    int(start_year),
                    int(end_year),
                    only_team_id=int(team_id) if scope in ("team", "owner") else None,
                )
            except Exception as e:
                payload["awards"]["opponent"] = []
                payload["meta"]["notes"].append(f"Opponent awards disabled: {type(e).__name__}: {e}")

            return jsonify(payload)

        # ----------------------------
        # mode=year_by_year
        # ----------------------------
        if mode == "year_by_year":
            week_out = {}
            season_out = {}
            category_week_out = {}
            category_season_out = {}
            luck_out = {}
            opponent_out = {}

            for y in range(int(start_year), int(end_year) + 1):
                y_week = week_base.filter(WeekTeamStats.year == int(y))
                y_season = season_base.filter(SeasonTeamMetrics.year == int(y))

                category_week_out[str(y)] = build_category_week_awards(y_week)
                luck_out[str(y)] = build_luck_awards(y_season)

                try:
                    opponent_out[str(y)] = build_opponent_awards_for_range(
                        int(y), int(y),
                        only_team_id=int(team_id) if scope in ("team", "owner") else None,
                    )
                except Exception:
                    opponent_out[str(y)] = []

                if not _weekly_stats_unreliable(session, LEAGUE_ID, y):
                    category_week_out[str(y)] = enrich_category_week_awards_with_raw(
                        session, LEAGUE_ID, category_week_out[str(y)]
                    )

                category_season_out[str(y)] = build_category_season_awards(y_week)
                category_season_out[str(y)] = enrich_category_season_awards_with_raw(
                    session, LEAGUE_ID, category_season_out[str(y)]
                )

                # extremes
                week_out[str(y)] = (lambda q: [
                    *([] if not (b := award_week_extreme(q, "max")) else [{
                        "id":"best_week_total_z","label":"Best Week (Total Z)",
                        "winners":[{"year":int(r.year),"week":int(r.week),"teamId":int(r.team_id),"teamName":r.team_name,"value":float(r.total_z)} for r in b[1]]
                    }]),
                    *([] if not (w := award_week_extreme(q, "min")) else [{
                        "id":"worst_week_total_z","label":"Worst Week (Total Z)",
                        "winners":[{"year":int(r.year),"week":int(r.week),"teamId":int(r.team_id),"teamName":r.team_name,"value":float(r.total_z)} for r in w[1]]
                    }]),
                ])(y_week)

                season_out[str(y)] = (lambda q: [
                    *([] if not (b := award_season_extreme(q, "max")) else [{
                        "id":"best_season_total_z","label":"Best Season (Total Z)",
                        "winners":[{"year":int(r.year),"teamId":int(r.team_id),"teamName":r.team_name,"value":float(r.sum_total_z)} for r in b[1]]
                    }]),
                    *([] if not (w := award_season_extreme(q, "min")) else [{
                        "id":"worst_season_total_z","label":"Worst Season (Total Z)",
                        "winners":[{"year":int(r.year),"teamId":int(r.team_id),"teamName":r.team_name,"value":float(r.sum_total_z)} for r in w[1]]
                    }]),
                ])(y_season)

            payload["awards"]["week"] = week_out
            payload["awards"]["season"] = season_out
            payload["awards"]["category_week"] = category_week_out
            payload["awards"]["category_season"] = category_season_out
            payload["awards"]["luck"] = luck_out
            payload["awards"]["opponent"] = opponent_out
            return jsonify(payload)

        return jsonify({"error": f"Unsupported mode={mode}"}), 400

    finally:
        session.close()


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
        payload["meta"] = _meta_for_range(session, int(start_year), int(end_year))
        return jsonify(payload)
    finally:
        session.close()

@analysis_bp.route("/health")
def analysis_health_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)

    session = SessionLocal()
    try:
        completed_weeks = _completed_weeks_from_matchups(session, year)
        latest_week = max(completed_weeks) if completed_weeks else None

        week_team_stats_rows = session.query(func.count(WeekTeamStats.id)).filter(
            WeekTeamStats.league_id == LEAGUE_ID,
            WeekTeamStats.year == year,
        ).scalar() or 0

        team_history_rows = session.query(func.count(TeamHistoryAgg.id)).filter(
            TeamHistoryAgg.league_id == LEAGUE_ID,
            TeamHistoryAgg.year == year,
        ).scalar() or 0

        opponent_rows = session.query(func.count(OpponentMatrixAggYear.id)).filter(
            OpponentMatrixAggYear.league_id == LEAGUE_ID,
            OpponentMatrixAggYear.year == year,
        ).scalar() or 0

        return jsonify({
            "year": int(year),
            "completedWeeks": completed_weeks,
            "latestWeek": latest_week,
            "counts": {
                "weekTeamStats": int(week_team_stats_rows),
                "teamHistoryAgg": int(team_history_rows),
                "opponentMatrixAggYear": int(opponent_rows),
            },
            "status": "OK",
            "source": "db_health",
        })
    finally:
        session.close()