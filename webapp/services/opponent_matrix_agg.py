# webapp/services/opponent_matrix_agg.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from webapp.config import LEAGUE_ID
from models_normalized import Team, MatchupCategoryResult, Matchup
from models_aggregates import OpponentMatrixAggYear
from analysis.owners import get_owner_start_year

CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"]

CAT_KEY = {
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

def _apply_owner_era_filter(team_espn_id: int, opponent_espn_id: int, year: int, owner_era_only: bool) -> bool:
    if not owner_era_only:
        return True
    a = get_owner_start_year(team_espn_id)
    b = get_owner_start_year(opponent_espn_id)
    if a is None or b is None:
        return False
    return year >= a and year >= b

def rebuild_opponent_matrix_agg_year(
    session: Session,
    year: int,
    team_espn_id: Optional[int] = None,
    force: bool = False,
) -> int:
    """
    Build per-year opponent aggregates using MatchupCategoryResult (true H2H category outcomes)
    + Matchup winner to compute matchup W/L/T.

    team_espn_id is ESPN team id (1..12).
    """
    year = int(year)

    # if force, wipe scope
    del_q = session.query(OpponentMatrixAggYear).filter(
        OpponentMatrixAggYear.league_id == LEAGUE_ID,
        OpponentMatrixAggYear.year == year,
    )
    if team_espn_id is not None:
        del_q = del_q.filter(OpponentMatrixAggYear.team_id == int(team_espn_id))
    if force:
        del_q.delete(synchronize_session=False)
        session.flush()

    # Map internal Team.id -> espn_team_id for this season
    team_rows = session.query(Team.id, Team.espn_team_id, Team.name).filter(
        Team.league_id == LEAGUE_ID,
        Team.season == year,
    ).all()
    if not team_rows:
        return 0

    id_to_espn: Dict[int, int] = {int(tid): int(espn) for tid, espn, _name in team_rows}
    espn_to_name: Dict[int, str] = {int(espn): str(name or "") for _tid, espn, name in team_rows}

    # Pull category results for this season (completed matchups only; if these rows exist, the matchup is “done”)
    q = session.query(
        MatchupCategoryResult.week,
        MatchupCategoryResult.matchup_id,
        MatchupCategoryResult.team_id,
        MatchupCategoryResult.opponent_team_id,
        MatchupCategoryResult.category,
        MatchupCategoryResult.result,
        MatchupCategoryResult.team_score,
        MatchupCategoryResult.opp_score,
    ).filter(
        MatchupCategoryResult.league_id == LEAGUE_ID,
        MatchupCategoryResult.season == year,
    )

    # optional team filter by espn id → translate to internal Team.id(s)
    team_internal_ids: Optional[List[int]] = None
    if team_espn_id is not None:
        team_internal_ids = [tid for tid, espn, _n in team_rows if int(espn) == int(team_espn_id)]
        if not team_internal_ids:
            return 0
        q = q.filter(MatchupCategoryResult.team_id.in_(team_internal_ids))

    cat_rows = q.all()
    if not cat_rows:
        return 0

    # We also need Matchup winners to compute matchup record W/L/T.
    # Build lookup: (week, matchup_id) -> winner_internal_team_id
    matchup_rows = session.query(
        Matchup.week, Matchup.matchup_id, Matchup.winner_team_id, Matchup.home_team_id, Matchup.away_team_id
    ).filter(
        Matchup.league_id == LEAGUE_ID,
        Matchup.season == year,
    ).all()

    winner_by_key: Dict[Tuple[int,int], Optional[int]] = {
        (int(wk), int(mid)): (int(winner) if winner is not None else None)
        for wk, mid, winner, _h, _a in matchup_rows
        if wk is not None and mid is not None
    }

    # Aggregate in python (small league, simple, fast)
    # Keyed by (team_espn, opp_espn)
    agg: Dict[Tuple[int,int], Dict[str, Any]] = {}

    # Track matchups seen per pair so we only count matchup record once per matchup
    seen_matchups: Dict[Tuple[int,int], set] = {}

    for wk, mid, team_id, opp_id, cat, res, team_score, opp_score in cat_rows:
        if team_id is None or opp_id is None:
            continue

        team_espn = id_to_espn.get(int(team_id))
        opp_espn = id_to_espn.get(int(opp_id))
        if team_espn is None or opp_espn is None:
            continue

        # if caller requested one team, skip others
        if team_espn_id is not None and int(team_espn) != int(team_espn_id):
            continue

        k = (int(team_espn), int(opp_espn))
        rec = agg.setdefault(k, {
            "wins": 0, "losses": 0, "ties": 0, "matchups": 0,
            "cats": {ck: {"w":0,"l":0,"t":0,"diff_sum":0.0,"diff_n":0} for ck in CAT_KEY.values()},
        })

        ck = CAT_KEY.get(cat)
        if not ck:
            continue

        # category result
        if res == "W":
            rec["cats"][ck]["w"] += 1
        elif res == "L":
            rec["cats"][ck]["l"] += 1
        else:
            rec["cats"][ck]["t"] += 1

        # avgDiff (only if you actually stored scores)
        if team_score is not None and opp_score is not None:
            rec["cats"][ck]["diff_sum"] += float(team_score) - float(opp_score)
            rec["cats"][ck]["diff_n"] += 1

        # matchup record count once per matchup
        wk_i = int(wk)
        mid_i = int(mid)
        smk = (k[0], k[1])
        seen = seen_matchups.setdefault(smk, set())
        if (wk_i, mid_i) not in seen:
            seen.add((wk_i, mid_i))
            rec["matchups"] += 1

            winner_internal = winner_by_key.get((wk_i, mid_i))
            if winner_internal is None:
                # cannot distinguish tie vs “not completed” from Matchup alone,
                # but since we have category rows, we treat this as a tie.
                rec["ties"] += 1
            else:
                winner_espn = id_to_espn.get(int(winner_internal))
                if winner_espn is None:
                    rec["ties"] += 1
                elif int(winner_espn) == int(team_espn):
                    rec["wins"] += 1
                else:
                    rec["losses"] += 1

    # Write rows
    written = 0
    for (team_espn, opp_espn), rec in agg.items():
        row = OpponentMatrixAggYear(
            league_id=LEAGUE_ID,
            year=year,
            team_id=int(team_espn),
            opponent_team_id=int(opp_espn),
            opponent_name=espn_to_name.get(int(opp_espn)),
            matchups=int(rec["matchups"]),
            wins=int(rec["wins"]),
            losses=int(rec["losses"]),
            ties=int(rec["ties"]),
        )

        for cat, ck in CAT_KEY.items():
            data = rec["cats"][ck]
            setattr(row, f"{ck}_w", int(data["w"]))
            setattr(row, f"{ck}_l", int(data["l"]))
            setattr(row, f"{ck}_t", int(data["t"]))
            setattr(row, f"{ck}_diff_sum", float(data["diff_sum"]))
            setattr(row, f"{ck}_diff_n", int(data["diff_n"]))

        session.add(row)
        written += 1

    return written


def get_opponent_matrix_range_from_agg(
    session: Session,
    start_year: int,
    end_year: int,
    team_espn_id: int,
    owner_era_only: bool,
) -> Dict[str, Any]:
    start_year = int(start_year)
    end_year = int(end_year)
    team_espn_id = int(team_espn_id)

    # load rows in range for this team
    rows = session.query(OpponentMatrixAggYear).filter(
        OpponentMatrixAggYear.league_id == LEAGUE_ID,
        OpponentMatrixAggYear.year >= start_year,
        OpponentMatrixAggYear.year <= end_year,
        OpponentMatrixAggYear.team_id == team_espn_id,
    ).all()

    # apply owner era filter (drops seasons outside era per team/opponent)
    filtered = []
    for r in rows:
        if _apply_owner_era_filter(team_espn_id, int(r.opponent_team_id), int(r.year), owner_era_only):
            filtered.append(r)

    # sum per opponent across years
    by_opp: Dict[int, Dict[str, Any]] = {}
    for r in filtered:
        opp = int(r.opponent_team_id)
        rec = by_opp.setdefault(opp, {
            "opponentName": r.opponent_name or f"Team {opp}",
            "overall": {"wins":0,"losses":0,"ties":0,"matchups":0},
            "cats": {cat: {"w":0,"l":0,"t":0,"diff_sum":0.0,"diff_n":0} for cat in CATEGORIES},
        })

        rec["overall"]["wins"] += int(r.wins or 0)
        rec["overall"]["losses"] += int(r.losses or 0)
        rec["overall"]["ties"] += int(r.ties or 0)
        rec["overall"]["matchups"] += int(r.matchups or 0)

        for cat in CATEGORIES:
            ck = CAT_KEY[cat]
            rec["cats"][cat]["w"] += int(getattr(r, f"{ck}_w") or 0)
            rec["cats"][cat]["l"] += int(getattr(r, f"{ck}_l") or 0)
            rec["cats"][cat]["t"] += int(getattr(r, f"{ck}_t") or 0)
            rec["cats"][cat]["diff_sum"] += float(getattr(r, f"{ck}_diff_sum") or 0.0)
            rec["cats"][cat]["diff_n"] += int(getattr(r, f"{ck}_diff_n") or 0)

    out_rows = []
    for opp, rec in by_opp.items():
        o = rec["overall"]
        total = (o["wins"] + o["losses"] + o["ties"]) or 0
        win_pct = (o["wins"] + 0.5 * o["ties"]) / total if total else 0.0

        cats_out = {}
        for cat, c in rec["cats"].items():
            ct = (c["w"] + c["l"] + c["t"]) or 0
            cwp = (c["w"] + 0.5 * c["t"]) / ct if ct else 0.5
            avg_diff = (c["diff_sum"] / c["diff_n"]) if c["diff_n"] else 0.0
            cats_out[cat] = {"wins": c["w"], "losses": c["l"], "ties": c["t"], "winPct": cwp, "avgDiff": avg_diff}

        out_rows.append({
            "teamId": team_espn_id,
            "opponentTeamId": opp,
            "opponentName": rec["opponentName"],
            "matchups": o["matchups"],
            "overall": {"wins": o["wins"], "losses": o["losses"], "ties": o["ties"], "matchups": o["matchups"], "winPct": win_pct},
            "categories": cats_out,
        })

    # stable ordering by opponent name
    out_rows.sort(key=lambda r: (r.get("opponentName") or ""))

    return {
        "startYear": start_year,
        "endYear": end_year,
        "teamId": team_espn_id,
        "ownerEraOnly": bool(owner_era_only),
        "rows": out_rows,
        "source": "db_opponent_matrix_agg",
    }