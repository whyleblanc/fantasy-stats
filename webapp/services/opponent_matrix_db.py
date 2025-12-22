# webapp/services/opponent_matrix_db.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from webapp.config import LEAGUE_ID
from models_normalized import Matchup, Team, StatWeekly
from analysis.owners import get_owner_start_year

CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"]


def _pct(made: int, att: int) -> Optional[float]:
    if att is None or att == 0:
        return None
    return float(made or 0) / float(att)


def _weekly_values(w: StatWeekly) -> Dict[str, Optional[float]]:
    fg = float(w.fg_pct) if w.fg_pct is not None else _pct(int(w.fgm or 0), int(w.fga or 0))
    ft = float(w.ft_pct) if w.ft_pct is not None else _pct(int(w.ftm or 0), int(w.fta or 0))

    return {
        "FG%": fg,
        "FT%": ft,
        "3PM": float(w.tpm or 0),
        "REB": float(w.reb or 0),
        "AST": float(w.ast or 0),
        "STL": float(w.stl or 0),
        "BLK": float(w.blk or 0),
        "DD": float(w.dd or 0),
        "PTS": float(w.pts or 0),
    }


def _compare(a: Optional[float], b: Optional[float]) -> Tuple[str, float]:
    """
    Returns (result, diff) from perspective of 'a' vs 'b':
      result in {"W","L","T"} and diff = a - b (0 if missing)
    """
    if a is None or b is None:
        return ("T", 0.0)
    diff = float(a) - float(b)
    if diff > 0:
        return ("W", diff)
    if diff < 0:
        return ("L", diff)
    return ("T", 0.0)


def _init_cat_bucket() -> Dict[str, Any]:
    return {"wins": 0, "losses": 0, "ties": 0, "winPct": 0.5, "avgDiff": 0.0, "_diffSum": 0.0, "_diffN": 0}


def _finalize_bucket(b: Dict[str, Any]) -> None:
    w, l, t = b["wins"], b["losses"], b["ties"]
    total = w + l + t
    b["winPct"] = (w + 0.5 * t) / total if total else 0.5

    n = b.get("_diffN", 0) or 0
    b["avgDiff"] = (b.get("_diffSum", 0.0) / n) if n else 0.0

    b.pop("_diffSum", None)
    b.pop("_diffN", None)


def get_opponent_matrix_multi_db(
    session: Session,
    *,
    start_year: int,
    end_year: int,
    selected_espn_team_id: int,
    current_owner_era_only: bool,
) -> Dict[str, Any]:
    """
    DB-backed opponent matrix over a year range.

    Output shape matches what your OpponentAnalysisTab expects:
      { minYear, maxYear, rows: [ { opponentName, overall, categories, matchups } ... ] }
    where each row is from perspective of selected_espn_team_id vs that opponent.
    """

    if end_year < start_year:
        start_year, end_year = end_year, start_year

    # Owner-era filter applies to selected team only (simple + matches UI intent)
    if current_owner_era_only:
        start = get_owner_start_year(int(selected_espn_team_id))
        if start is not None:
            start_year = max(int(start_year), int(start))

    # Pull matchups in-range that have a winner (completed)
    matchups: List[Matchup] = (
        session.query(Matchup)
        .filter(
            Matchup.league_id == LEAGUE_ID,
            Matchup.season >= int(start_year),
            Matchup.season <= int(end_year),
            Matchup.winner_team_id.isnot(None),
        )
        .all()
    )
    if not matchups:
        return {"minYear": start_year, "maxYear": end_year, "rows": []}

    # Build lookup: (season, week, team_db_id) -> StatWeekly
    # We only need weeks/teams that appear in matchups involving the selected team.
    # First identify relevant matchup sides (db team ids).
    relevant_pairs: List[Tuple[int, int, int, int]] = []  # (season, week, home_db_id, away_db_id)
    relevant_team_db_ids_by_seasonweek: Dict[Tuple[int, int], set] = {}

    # We also need ESPN team id mapping for each db team id
    # Team table is per season, so db team id uniquely identifies season-team row.
    # We'll fetch teams for all matchup home/away ids.
    team_db_ids = set()
    for m in matchups:
        team_db_ids.add(int(m.home_team_id))
        team_db_ids.add(int(m.away_team_id))

    teams: List[Team] = session.query(Team).filter(Team.id.in_(team_db_ids)).all()
    team_by_id: Dict[int, Team] = {int(t.id): t for t in teams}

    # Determine which DB team rows correspond to the selected ESPN team id, per season
    # (since Team rows are season-specific)
    selected_team_db_ids = {tid for tid, t in team_by_id.items() if int(t.espn_team_id) == int(selected_espn_team_id)}
    if not selected_team_db_ids:
        return {"minYear": start_year, "maxYear": end_year, "rows": []}

    # Keep only matchups where selected team participated
    for m in matchups:
        h = int(m.home_team_id)
        a = int(m.away_team_id)
        if h not in selected_team_db_ids and a not in selected_team_db_ids:
            continue
        season = int(m.season)
        week = int(m.week)
        relevant_pairs.append((season, week, h, a))
        key = (season, week)
        relevant_team_db_ids_by_seasonweek.setdefault(key, set()).update([h, a])

    if not relevant_pairs:
        return {"minYear": start_year, "maxYear": end_year, "rows": []}

    # Fetch StatWeekly for just the needed (season, week, team_id)
    # StatWeekly.team_id is FK to Team.id
    stat_rows: List[StatWeekly] = []
    for (season, week), ids in relevant_team_db_ids_by_seasonweek.items():
        chunk = (
            session.query(StatWeekly)
            .filter(
                StatWeekly.league_id == LEAGUE_ID,
                StatWeekly.season == season,
                StatWeekly.week == week,
                StatWeekly.team_id.in_(list(ids)),
            )
            .all()
        )
        stat_rows.extend(chunk)

    stat_map: Dict[Tuple[int, int, int], StatWeekly] = {}
    for s in stat_rows:
        stat_map[(int(s.season), int(s.week), int(s.team_id))] = s

    # Accumulate by opponent ESPN team id
    acc: Dict[int, Dict[str, Any]] = {}

    def ensure_opp(opp_espn_id: int, opp_name: str) -> Dict[str, Any]:
        if opp_espn_id not in acc:
            acc[opp_espn_id] = {
                "opponentName": opp_name,
                "matchups": 0,
                "overall": {"wins": 0, "losses": 0, "ties": 0, "winPct": 0.5},
                "categories": {cat: _init_cat_bucket() for cat in CATEGORIES},
            }
        return acc[opp_espn_id]

    # Iterate relevant matchups and score categories
    for season, week, home_id, away_id in relevant_pairs:
        home_team = team_by_id.get(home_id)
        away_team = team_by_id.get(away_id)
        if not home_team or not away_team:
            continue

        home_espn = int(home_team.espn_team_id)
        away_espn = int(away_team.espn_team_id)

        s_home = stat_map.get((season, week, home_id))
        s_away = stat_map.get((season, week, away_id))
        if not s_home or not s_away:
            # no weekly stats -> skip this matchup
            continue

        v_home = _weekly_values(s_home)
        v_away = _weekly_values(s_away)

        # Determine perspective: selected vs opponent
        if home_espn == int(selected_espn_team_id):
            sel_vals, opp_vals = v_home, v_away
            opp_espn, opp_name = away_espn, (away_team.name or f"Team {away_espn}")
        else:
            sel_vals, opp_vals = v_away, v_home
            opp_espn, opp_name = home_espn, (home_team.name or f"Team {home_espn}")

        row = ensure_opp(opp_espn, opp_name)
        row["matchups"] += 1

        # Per-category
        cat_w = cat_l = cat_t = 0
        for cat in CATEGORIES:
            res, diff = _compare(sel_vals.get(cat), opp_vals.get(cat))
            bucket = row["categories"][cat]

            if res == "W":
                bucket["wins"] += 1
                cat_w += 1
            elif res == "L":
                bucket["losses"] += 1
                cat_l += 1
            else:
                bucket["ties"] += 1
                cat_t += 1

            # avgDiff tracking
            bucket["_diffSum"] += float(diff)
            bucket["_diffN"] += 1

        # Overall "category matchup result" for that week (9-cat style)
        if cat_w > cat_l:
            row["overall"]["wins"] += 1
        elif cat_l > cat_w:
            row["overall"]["losses"] += 1
        else:
            row["overall"]["ties"] += 1

    # Finalize winPct/avgDiff
    out_rows: List[Dict[str, Any]] = []
    for opp_espn, row in acc.items():
        ow, ol, ot = row["overall"]["wins"], row["overall"]["losses"], row["overall"]["ties"]
        total = ow + ol + ot
        row["overall"]["winPct"] = (ow + 0.5 * ot) / total if total else 0.5
        row["overall"]["matchups"] = int(row["matchups"])

        for cat in CATEGORIES:
            _finalize_bucket(row["categories"][cat])

        out_rows.append(row)

    out_rows.sort(key=lambda r: (-(r["overall"]["winPct"] or 0.0), r["opponentName"]))
    return {"minYear": int(start_year), "maxYear": int(end_year), "rows": out_rows}