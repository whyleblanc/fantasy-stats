from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from webapp.config import LEAGUE_ID
from models_aggregates import OpponentMatrixAggYear
from analysis.owners import get_owner_start_year

CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"]

# UI category -> DB prefix
CAT_PREFIX = {
    "FG%": "fg",
    "FT%": "ft",
    "3PM": "three_pm",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "DD": "dd",
    "PTS": "pts",
}


def _cat_block_from_row(r: OpponentMatrixAggYear, prefix: str) -> Dict[str, Any]:
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
        # keep for exact merges across years
        "_diffSum": s,
        "_diffN": n,
    }


def _ui_row_from_db(r: OpponentMatrixAggYear) -> Dict[str, Any]:
    wins = int(r.wins or 0)
    losses = int(r.losses or 0)
    ties = int(r.ties or 0)
    matchups = int(r.matchups or 0)

    total = wins + losses + ties
    overall = {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "matchups": matchups,
        "winPct": (wins / total) if total else 0.0,
    }

    cats = {}
    for cat, prefix in CAT_PREFIX.items():
        cats[cat] = _cat_block_from_row(r, prefix)

    return {
        "opponentTeamId": int(r.opponent_team_id),
        "opponentName": r.opponent_name or "",
        "matchups": matchups,
        "overall": overall,
        "categories": cats,
    }


def _merge_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[int, Dict[str, Any]] = {}

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
                "categories": {cat: {"wins": 0, "losses": 0, "ties": 0, "_diffSum": 0.0, "_diffN": 0} for cat in CATEGORIES},
            },
        )

        m["matchups"] += int(row.get("matchups") or 0)

        o = row.get("overall") or {}
        m["overall"]["wins"] += int(o.get("wins") or 0)
        m["overall"]["losses"] += int(o.get("losses") or 0)
        m["overall"]["ties"] += int(o.get("ties") or 0)
        m["overall"]["matchups"] += int(o.get("matchups") or 0)

        cats = row.get("categories") or {}
        for cat in CATEGORIES:
            blk = cats.get(cat) or {}
            cur = m["categories"][cat]
            cur["wins"] += int(blk.get("wins") or 0)
            cur["losses"] += int(blk.get("losses") or 0)
            cur["ties"] += int(blk.get("ties") or 0)
            cur["_diffSum"] += float(blk.get("_diffSum") or 0.0)
            cur["_diffN"] += int(blk.get("_diffN") or 0)

    out: List[Dict[str, Any]] = []
    for oid, m in merged.items():
        total = m["overall"]["wins"] + m["overall"]["losses"] + m["overall"]["ties"]
        m["overall"]["winPct"] = (m["overall"]["wins"] / total) if total else 0.0

        # finalize categories: compute winPct + avgDiff, then drop internal keys
        finalized = {}
        for cat in CATEGORIES:
            c = m["categories"][cat]
            total_cat = c["wins"] + c["losses"] + c["ties"]
            finalized[cat] = {
                "wins": c["wins"],
                "losses": c["losses"],
                "ties": c["ties"],
                "winPct": (c["wins"] / total_cat) if total_cat else 0.0,
                "avgDiff": (c["_diffSum"] / c["_diffN"]) if c["_diffN"] else 0.0,
            }
        m["categories"] = finalized

        out.append(m)

    out.sort(key=lambda r: (r["overall"]["winPct"], r["matchups"]), reverse=True)
    return out


def get_opponent_matrix_from_agg_year(
    session: Session,
    *,
    start_year: int,
    end_year: int,
    selected_espn_team_id: int,
    current_owner_era_only: bool,
) -> Dict[str, Any]:
    if end_year < start_year:
        start_year, end_year = end_year, start_year

    if current_owner_era_only:
        start = get_owner_start_year(int(selected_espn_team_id))
        if start is not None:
            start_year = max(int(start_year), int(start))

    q = (
        session.query(OpponentMatrixAggYear)
        .filter(
            OpponentMatrixAggYear.league_id == LEAGUE_ID,
            OpponentMatrixAggYear.team_id == int(selected_espn_team_id),
            OpponentMatrixAggYear.year >= int(start_year),
            OpponentMatrixAggYear.year <= int(end_year),
        )
    )

    db_rows = q.all()
    if not db_rows:
        return {"minYear": int(start_year), "maxYear": int(end_year), "rows": []}

    ui_rows = [_ui_row_from_db(r) for r in db_rows]

    # If multiple years, merge per opponent across years
    if int(start_year) != int(end_year):
        ui_rows = _merge_rows(ui_rows)
    else:
        # single year: drop internal diff keys
        for row in ui_rows:
            for cat in CATEGORIES:
                row["categories"][cat].pop("_diffSum", None)
                row["categories"][cat].pop("_diffN", None)

    return {"minYear": int(start_year), "maxYear": int(end_year), "rows": ui_rows}