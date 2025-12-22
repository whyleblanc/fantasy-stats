from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

import argparse
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional

from sqlalchemy import text
from sqlalchemy.orm import aliased

from db import SessionLocal
from webapp.config import LEAGUE_ID, MAX_YEAR
from models_normalized import Matchup, Team, StatWeekly


# ----------------------------
# Config
# ----------------------------

# Your canonical categories → column prefixes in opponent_matrix_agg_year
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


@dataclass
class AggRow:
    league_id: int
    year: int
    team_id: int                # ESPN team id
    opponent_team_id: int       # ESPN team id
    opponent_name: str = ""

    matchups: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0

    # per-category stats dynamically stored
    cat_w: Dict[str, int] = field(default_factory=dict)
    cat_l: Dict[str, int] = field(default_factory=dict)
    cat_t: Dict[str, int] = field(default_factory=dict)
    diff_sum: Dict[str, float] = field(default_factory=dict)
    diff_n: Dict[str, int] = field(default_factory=dict)

    def ensure_cat(self, prefix: str) -> None:
        self.cat_w.setdefault(prefix, 0)
        self.cat_l.setdefault(prefix, 0)
        self.cat_t.setdefault(prefix, 0)
        self.diff_sum.setdefault(prefix, 0.0)
        self.diff_n.setdefault(prefix, 0)

    def apply_cat(self, prefix: str, result: str, team_score: Optional[float], opp_score: Optional[float]) -> None:
        self.ensure_cat(prefix)

        r = (result or "").upper()
        if r == "W":
            self.cat_w[prefix] += 1
        elif r == "L":
            self.cat_l[prefix] += 1
        else:
            # treat anything else as tie for safety
            self.cat_t[prefix] += 1

        if team_score is not None and opp_score is not None:
            self.diff_sum[prefix] += float(team_score) - float(opp_score)
            self.diff_n[prefix] += 1


def delete_year(session, year: int) -> None:
    session.execute(
        text(
            """
            DELETE FROM opponent_matrix_agg_year
            WHERE league_id = :league_id AND year = :year
            """
        ),
        {"league_id": LEAGUE_ID, "year": int(year)},
    )


def upsert_agg_row(session, row: AggRow) -> None:
    """
    SQLite UPSERT into opponent_matrix_agg_year.

    Table columns (from your PRAGMA):
      league_id, year, team_id, opponent_team_id, opponent_name,
      matchups, wins, losses, ties,
      fg_w, fg_l, fg_t, fg_diff_sum, fg_diff_n,
      ...
      pts_w, pts_l, pts_t, pts_diff_sum, pts_diff_n
    """
    # flatten dynamic per-cat stats into fixed cols
    payload = {
        "league_id": row.league_id,
        "year": row.year,
        "team_id": row.team_id,
        "opponent_team_id": row.opponent_team_id,
        "opponent_name": row.opponent_name,
        "matchups": row.matchups,
        "wins": row.wins,
        "losses": row.losses,
        "ties": row.ties,
    }

    for cat, prefix in CAT_PREFIX.items():
        row.ensure_cat(prefix)
        payload[f"{prefix}_w"] = row.cat_w[prefix]
        payload[f"{prefix}_l"] = row.cat_l[prefix]
        payload[f"{prefix}_t"] = row.cat_t[prefix]
        payload[f"{prefix}_diff_sum"] = row.diff_sum[prefix]
        payload[f"{prefix}_diff_n"] = row.diff_n[prefix]

    cols = ", ".join(payload.keys())
    params = ", ".join(f":{k}" for k in payload.keys())

    # on conflict (league_id, year, team_id, opponent_team_id) → update all metrics
    update_sets = ", ".join(
        [f"{k}=excluded.{k}" for k in payload.keys() if k not in ("league_id", "year", "team_id", "opponent_team_id")]
    )

    sql = f"""
    INSERT INTO opponent_matrix_agg_year ({cols})
    VALUES ({params})
    ON CONFLICT(league_id, year, team_id, opponent_team_id)
    DO UPDATE SET {update_sets}
    """

    session.execute(text(sql), payload)


def rebuild_year(session, year: int, force: bool = False) -> int:
    year = int(year)

    if force:
        delete_year(session, year)

    # Build a quick lookup: internal Team.id -> (espn_team_id, name)
    teams = (
        session.query(Team.id, Team.espn_team_id, Team.name)
        .filter(Team.league_id == LEAGUE_ID, Team.season == year)
        .all()
    )
    team_map = {int(tid): (int(espn_id), (name or "")) for tid, espn_id, name in teams}

    def pct(made: float, att: float) -> Optional[float]:
        if att is None or float(att) == 0:
            return None
        return float(made or 0) / float(att)

    # Pull matchups for the year
    matchups = (
        session.query(Matchup)
        .filter(Matchup.league_id == LEAGUE_ID, Matchup.season == year)
        .all()
    )

    if not matchups:
        return 0

    # Pull stats_weekly for the year, index by (week, internal_team_id)
    sw_rows = (
        session.query(StatWeekly)
        .filter(StatWeekly.league_id == LEAGUE_ID, StatWeekly.season == year)
        .all()
    )
    sw_map = {(int(r.week), int(r.team_id)): r for r in sw_rows if r.week is not None and r.team_id is not None}

    agg: Dict[Tuple[int, int], AggRow] = {}

    for m in matchups:
        if m.week is None:
            continue

        wk = int(m.week)
        home_internal = int(m.home_team_id)
        away_internal = int(m.away_team_id)

        home_sw = sw_map.get((wk, home_internal))
        away_sw = sw_map.get((wk, away_internal))

        # "completed" == we have both stats_weekly rows
        if not home_sw or not away_sw:
            continue

        # Map internal -> ESPN ids
        if home_internal not in team_map or away_internal not in team_map:
            continue

        home_espn, home_name = team_map[home_internal]
        away_espn, away_name = team_map[away_internal]

        # helper to get/create agg rows for both directions
        def get_row(team_espn: int, opp_espn: int, opp_name: str) -> AggRow:
            key = (team_espn, opp_espn)
            if key not in agg:
                agg[key] = AggRow(
                    league_id=LEAGUE_ID,
                    year=year,
                    team_id=team_espn,
                    opponent_team_id=opp_espn,
                    opponent_name=opp_name,
                )
            return agg[key]

        a_home = get_row(home_espn, away_espn, away_name)
        a_away = get_row(away_espn, home_espn, home_name)

        # overall matchup count (once per matchup)
        a_home.matchups += 1
        a_away.matchups += 1

        # compute category values
        def values(sw: StatWeekly) -> Dict[str, Optional[float]]:
            fg = float(sw.fg_pct) if sw.fg_pct is not None else pct(sw.fgm, sw.fga)
            ft = float(sw.ft_pct) if sw.ft_pct is not None else pct(sw.ftm, sw.fta)
            return {
                "FG%": fg,
                "FT%": ft,
                "3PM": float(sw.tpm or 0),
                "REB": float(sw.reb or 0),
                "AST": float(sw.ast or 0),
                "STL": float(sw.stl or 0),
                "BLK": float(sw.blk or 0),
                "DD": float(sw.dd or 0),
                "PTS": float(sw.pts or 0),
            }

        hv = values(home_sw)
        av = values(away_sw)

        # category results + diffs
        home_cat_wins = 0
        away_cat_wins = 0

        for cat, prefix in CAT_PREFIX.items():
            h = hv.get(cat)
            o = av.get(cat)

            # if either missing, treat as tie (still counts as a category event)
            if h is None or o is None:
                a_home.apply_cat(prefix, "T", h, o)
                a_away.apply_cat(prefix, "T", o, h)
                continue

            if h > o:
                a_home.apply_cat(prefix, "W", h, o)
                a_away.apply_cat(prefix, "L", o, h)
                home_cat_wins += 1
            elif h < o:
                a_home.apply_cat(prefix, "L", h, o)
                a_away.apply_cat(prefix, "W", o, h)
                away_cat_wins += 1
            else:
                a_home.apply_cat(prefix, "T", h, o)
                a_away.apply_cat(prefix, "T", o, h)

        # overall W/L/T (by categories won)
        if home_cat_wins > away_cat_wins:
            a_home.wins += 1
            a_away.losses += 1
        elif away_cat_wins > home_cat_wins:
            a_home.losses += 1
            a_away.wins += 1
        else:
            a_home.ties += 1
            a_away.ties += 1

    # write out
    written = 0
    for a in agg.values():
        upsert_agg_row(session, a)
        written += 1

    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None, help="Single season to rebuild (e.g. 2026)")
    parser.add_argument("--all", action="store_true", help="Rebuild all years 2014..MAX_YEAR")
    parser.add_argument("--force", action="store_true", help="Delete existing rows for the year(s) before rebuilding")

    args = parser.parse_args()

    years = []
    if args.all:
        years = list(range(2014, int(MAX_YEAR) + 1))
    else:
        years = [int(args.year or MAX_YEAR)]

    session = SessionLocal()
    try:
        total_rows = 0
        for y in years:
            n = rebuild_year(session, y, force=args.force)
            session.commit()
            print(f"[OK] {y}: upserted {n} opponent agg rows")
            total_rows += n
        print(f"[DONE] total upserted rows: {total_rows}")
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()