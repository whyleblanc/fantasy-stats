# webapp/routes/league.py

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import and_
from sqlalchemy.orm import Session

from analysis.owners import build_owners_map
from db import SessionLocal, WeekTeamStats
from models_normalized import Matchup, StatWeekly, Team
from webapp.config import LEAGUE_ID, MAX_YEAR, MIN_YEAR
from webapp.legacy_services import build_league_payload  # fallback only
from webapp.services.cache_week_team_stats import rebuild_week_team_stats_cache
from webapp.services.espn_ingest import sync_week
from webapp.services.standings_cache import get as cache_get
from webapp.services.standings_cache import invalidate_season as cache_invalidate_season
from webapp.services.standings_cache import set as cache_set

league_bp = Blueprint("league", __name__)

CATS = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"]


def _cat_values(w: StatWeekly) -> Dict[str, Optional[float]]:
    fga = float(w.fga or 0)
    fta = float(w.fta or 0)

    fg_pct = (
        float(w.fg_pct)
        if w.fg_pct is not None
        else ((float(w.fgm or 0) / fga) if fga > 0 else None)
    )
    ft_pct = (
        float(w.ft_pct)
        if w.ft_pct is not None
        else ((float(w.ftm or 0) / fta) if fta > 0 else None)
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


def _completed_weeks(session: Session, year: int) -> List[int]:
    rows = (
        session.query(Matchup.week)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == year,
            Matchup.winner_team_id.isnot(None),
        )
        .distinct()
        .order_by(Matchup.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _weeks_available(session: Session, year: int) -> List[int]:
    rows = (
        session.query(Matchup.week)
        .filter(Matchup.league_id == LEAGUE_ID, Matchup.season == year)
        .distinct()
        .order_by(Matchup.week)
        .all()
    )
    return [int(w[0]) for w in rows if w[0] is not None]


def _integrity_weekly_stats_missing(
    session: Session, year: int, weeks: List[int]
) -> Dict[str, Any]:
    """
    Integrity check: for each completed matchup week, we expect StatWeekly rows for
    both home_team_id and away_team_id (internal Team.id).

    Returns missing pairs and summary counts.
    """
    if not weeks:
        return {"missing": [], "expectedCount": 0, "presentCount": 0}

    matchup_pairs: Set[Tuple[int, int]] = set()

    matchup_rows = (
        session.query(Matchup.week, Matchup.home_team_id, Matchup.away_team_id)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == year,
            Matchup.week.in_(weeks),
        )
        .all()
    )

    for wk, h, a in matchup_rows:
        if wk is None or h is None or a is None:
            continue
        matchup_pairs.add((int(wk), int(h)))
        matchup_pairs.add((int(wk), int(a)))

    expected_count = len(matchup_pairs)

    sw_rows = (
        session.query(StatWeekly.week, StatWeekly.team_id)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season == year,
            StatWeekly.week.in_(weeks),
        )
        .all()
    )
    present_pairs = {(int(w), int(t)) for w, t in sw_rows if w is not None and t is not None}

    missing = sorted(list(matchup_pairs - present_pairs))
    return {
        "missing": [{"week": w, "teamId": tid} for (w, tid) in missing],
        "expectedCount": expected_count,
        "presentCount": len(present_pairs),
    }


def _standings_from_db(session: Session, year: int, refresh: bool = False) -> Dict[str, Any]:
    completed_weeks = _completed_weeks(session, year)
    if not completed_weeks:
        return {"completedWeeks": [], "teams": []}

    completed_through = int(max(completed_weeks))

    if not refresh:
        cached = cache_get(year, completed_through)
        if cached is not None:
            return cached

    # Owners map (espn_team_id -> name)
    try:
        owners_map = build_owners_map(year) or {}
    except Exception:
        owners_map = {}

    # Internal Team.id -> (espn_team_id, name)
    team_rows = (
        session.query(Team.id, Team.espn_team_id, Team.name)
        .filter(Team.league_id == LEAGUE_ID, Team.season == year)
        .all()
    )

    id_to_espn: Dict[int, int] = {}
    espn_to_name: Dict[int, str] = {}

    for tid, espn_id, nm in team_rows:
        if tid is None or espn_id is None:
            continue
        id_to_espn[int(tid)] = int(espn_id)
        espn_to_name[int(espn_id)] = nm or f"Team {int(espn_id)}"

    # Matchups for completed weeks (internal ids)
    matchups = (
        session.query(Matchup.week, Matchup.home_team_id, Matchup.away_team_id, Matchup.winner_team_id)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season == year,
            Matchup.week.in_(completed_weeks),
        )
        .all()
    )

    # Accumulators by ESPN team id
    rec: Dict[int, Dict[str, int]] = {}
    catrec: Dict[int, Dict[str, int]] = {}

    def ensure(espn_tid: int) -> None:
        espn_tid = int(espn_tid)
        if espn_tid not in rec:
            rec[espn_tid] = {"wins": 0, "losses": 0, "ties": 0}
        if espn_tid not in catrec:
            catrec[espn_tid] = {"wins": 0, "losses": 0, "ties": 0}

    # Small perf win: prefetch StatWeekly rows for all (completed weeks)
    sw_all = (
        session.query(StatWeekly)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season == year,
            StatWeekly.week.in_(completed_weeks),
        )
        .all()
    )
    sw_by_pair: Dict[Tuple[int, int], StatWeekly] = {}
    for r in sw_all:
        if r.week is None or r.team_id is None:
            continue
        sw_by_pair[(int(r.week), int(r.team_id))] = r  # NOTE: team_id is internal Team.id

    for wk, home_tid, away_tid, winner_tid in matchups:
        if wk is None or home_tid is None or away_tid is None:
            continue

        wk = int(wk)
        home_tid = int(home_tid)  # internal Team.id
        away_tid = int(away_tid)

        home_espn = id_to_espn.get(home_tid)
        away_espn = id_to_espn.get(away_tid)
        winner_espn = id_to_espn.get(int(winner_tid)) if winner_tid is not None else None

        if home_espn is None or away_espn is None:
            continue

        home_espn = int(home_espn)
        away_espn = int(away_espn)

        ensure(home_espn)
        ensure(away_espn)

        # Matchup W-L-T
        if winner_espn is None:
            rec[home_espn]["ties"] += 1
            rec[away_espn]["ties"] += 1
        else:
            winner_espn = int(winner_espn)
            if winner_espn == home_espn:
                rec[home_espn]["wins"] += 1
                rec[away_espn]["losses"] += 1
            elif winner_espn == away_espn:
                rec[away_espn]["wins"] += 1
                rec[home_espn]["losses"] += 1
            else:
                rec[home_espn]["ties"] += 1
                rec[away_espn]["ties"] += 1

        # Category CW-CL-CT (from StatWeekly comparisons)
        hrow = sw_by_pair.get((wk, home_tid))
        arow = sw_by_pair.get((wk, away_tid))

        if not hrow or not arow:
            # treat missing as ties for all cats
            catrec[home_espn]["ties"] += len(CATS)
            catrec[away_espn]["ties"] += len(CATS)
            continue

        hvals = _cat_values(hrow)
        avals = _cat_values(arow)

        for cat in CATS:
            hv = hvals.get(cat)
            av = avals.get(cat)

            if hv is None or av is None:
                catrec[home_espn]["ties"] += 1
                catrec[away_espn]["ties"] += 1
                continue

            if hv > av:
                catrec[home_espn]["wins"] += 1
                catrec[away_espn]["losses"] += 1
            elif av > hv:
                catrec[away_espn]["wins"] += 1
                catrec[home_espn]["losses"] += 1
            else:
                catrec[home_espn]["ties"] += 1
                catrec[away_espn]["ties"] += 1

    teams: List[Dict[str, Any]] = []
    for espn_tid, wl in rec.items():
        w = int(wl["wins"])
        l = int(wl["losses"])
        t = int(wl["ties"])
        matchup_record = f"{w}\u2013{l}" + (f"\u2013{t}" if t else "")

        cw = int(catrec[espn_tid]["wins"])
        cl = int(catrec[espn_tid]["losses"])
        ct = int(catrec[espn_tid]["ties"])
        category_record = f"{cw}\u2013{cl}\u2013{ct}"

        teams.append(
            {
                "teamId": int(espn_tid),
                "teamName": espn_to_name.get(int(espn_tid), f"Team {espn_tid}"),
                "owners": owners_map.get(int(espn_tid)),
                "matchupWins": w,
                "matchupLosses": l,
                "matchupTies": t,
                "matchupRecord": matchup_record,
                "categoryWins": cw,
                "categoryLosses": cl,
                "categoryTies": ct,
                "categoryRecord": category_record,
                # legacy keys
                "wins": w,
                "losses": l,
                "ties": t,
                "record": matchup_record,
                "pointsFor": None,
                "pointsAgainst": None,
                "finalRank": None,
            }
        )

    teams.sort(
        key=lambda x: (x["matchupWins"], x["matchupTies"], x["categoryWins"], -x["matchupLosses"]),
        reverse=True,
    )
    for idx, t in enumerate(teams, start=1):
        t["rank"] = idx

    payload = {"completedWeeks": completed_weeks, "teams": teams}
    cache_set(year, completed_through, payload)
    return payload


def _build_league_payload_from_db(year: int, refresh: bool = False) -> Optional[Dict[str, Any]]:
    session = SessionLocal()
    try:
        weeks = _weeks_available(session, year)
        if not weeks:
            return None

        team_count = (
            session.query(Team.id)
            .filter(Team.league_id == LEAGUE_ID, Team.season == year)
            .count()
        )

        has_weekteamstats = (
            session.query(WeekTeamStats.id)
            .filter_by(league_id=LEAGUE_ID, year=year, is_league_average=False)
            .first()
            is not None
        )

        standings = _standings_from_db(session, year, refresh=refresh)
        completed = standings.get("completedWeeks") or []

        current_week = int(max(completed)) if completed else int(max(weeks))
        in_progress_week = int(max(weeks))

        return {
            "leagueId": LEAGUE_ID,
            "leagueName": "H2H Basketball",
            "year": int(year),
            "teamCount": int(team_count),
            "currentWeek": current_week,          # completed-through (standings-safe)
            "inProgressWeek": in_progress_week,   # max week present (may be live)
            "weeksAvailable": weeks,
            "advancedStatsAvailable": bool(has_weekteamstats),
            "source": "db",
            "completedWeeks": standings.get("completedWeeks", []),
            "teams": standings.get("teams", []),
        }
    finally:
        session.close()


@league_bp.route("/api/league")
def league_api():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    year = max(MIN_YEAR, min(MAX_YEAR, year))
    refresh = request.args.get("refresh", default=0, type=int) == 1

    db_payload = _build_league_payload_from_db(year, refresh=refresh)
    if db_payload is not None:
        return jsonify(db_payload)

    # fallback only if DB doesn't have matchups for that year
    try:
        payload = build_league_payload(year)
        payload.setdefault("leagueId", LEAGUE_ID)
        payload.setdefault("leagueName", "H2H Basketball")
        payload.setdefault("year", year)
        payload.setdefault("source", "espn_legacy")
        return jsonify(payload)
    except Exception as e:
        return (
            jsonify(
                {
                    "leagueId": LEAGUE_ID,
                    "leagueName": "H2H Basketball",
                    "year": year,
                    "teamCount": 0,
                    "currentWeek": None,
                    "weeksAvailable": [],
                    "advancedStatsAvailable": False,
                    "source": "stub",
                    "error": "League data not available for this year",
                    "details": str(e),
                }
            ),
            200,
        )


@league_bp.route("/api/league/health")
def league_health():
    year = request.args.get("year", default=MAX_YEAR, type=int)
    year = max(MIN_YEAR, min(MAX_YEAR, year))

    session = SessionLocal()
    try:
        weeks = _weeks_available(session, year)
        completed = _completed_weeks(session, year)
        completed_through = int(max(completed)) if completed else None
        in_progress_week = int(max(weeks)) if weeks else None

        # Integrity check only needs completed weeks (that’s what standings use)
        integrity = _integrity_weekly_stats_missing(session, year, completed)

        return jsonify(
            {
                "ok": True,
                "year": int(year),
                "weeksAvailable": weeks,
                "completedWeeks": completed,
                "completedThroughWeek": completed_through,
                "inProgressWeek": in_progress_week,
                "integrity": integrity,
            }
        )
    finally:
        session.close()


@league_bp.route("/api/league/<int:season>/weeks/<int:week>/refresh", methods=["POST"])
def refresh_week(season: int, week: int):
    league_id = current_app.config["LEAGUE_ID"]
    espn_swid = current_app.config["ESPN_SWID"]
    espn_s2 = current_app.config["ESPN_S2"]

    session = SessionLocal()
    try:
        sync_week(
            session=session,
            league_id=league_id,
            season=season,
            week=week,
            espn_swid=espn_swid,
            espn_s2=espn_s2,
        )

        rebuild_week_team_stats_cache(
            session=session,
            league_id=league_id,
            season=season,
            week=week,
        )

        session.commit()

        # Important: invalidate standings cache for that season (week completion may change)
        cache_invalidate_season(season)

        return jsonify({"ok": True, "season": season, "week": week})
    except Exception as e:
        session.rollback()
        return jsonify({"error": "week_sync_failed", "season": season, "week": week, "details": str(e)}), 500
    finally:
        session.close()