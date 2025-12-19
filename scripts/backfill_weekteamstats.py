from __future__ import annotations

from collections import defaultdict
from typing import Dict, Any, List, Tuple

from sqlalchemy.orm import Session

from db import SessionLocal, WeekTeamStats
from models_normalized import StatWeekly, Team
from analysis.constants import CATEGORIES, CAT_TO_DB_COL
from webapp.config import LEAGUE_ID

def _z(val: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return (val - mean) / std

def _raw_from_weekly(w: StatWeekly) -> Dict[str, float | None]:
    fg = float(w.fg_pct) if w.fg_pct is not None else None
    ft = float(w.ft_pct) if w.ft_pct is not None else None
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

def rebuild_weekteamstats(session: Session, start_year: int = 2014, end_year: int = 2026) -> None:
    # wipe existing computed cache
    session.query(WeekTeamStats).filter(WeekTeamStats.league_id == LEAGUE_ID).delete(synchronize_session=False)
    session.commit()

    # pull all weekly rows joined to team (for espn id + name)
    rows: List[Tuple[StatWeekly, Team]] = (
        session.query(StatWeekly, Team)
        .join(Team, StatWeekly.team_id == Team.id)
        .filter(
            StatWeekly.league_id == LEAGUE_ID,
            StatWeekly.season >= start_year,
            StatWeekly.season <= end_year,
        )
        .all()
    )

    # group by (season, week)
    buckets: Dict[Tuple[int, int], List[Tuple[StatWeekly, Team]]] = defaultdict(list)
    for w, t in rows:
        buckets[(int(w.season), int(w.week))].append((w, t))

    for (season, week), group in sorted(buckets.items()):
        # compute per-category means/stds across teams that have values
        team_raw: Dict[int, Dict[str, float | None]] = {}
        team_name: Dict[int, str] = {}

        for w, t in group:
            espn_tid = int(t.espn_team_id)
            team_raw[espn_tid] = _raw_from_weekly(w)
            team_name[espn_tid] = t.name

        means: Dict[str, float] = {}
        stds: Dict[str, float] = {}

        for cat in CATEGORIES:
            vals = [v[cat] for v in team_raw.values() if v.get(cat) is not None]
            if not vals:
                means[cat] = 0.0
                stds[cat] = 0.0
                continue
            n = len(vals)
            mean = sum(vals) / n
            var = sum((x - mean) ** 2 for x in vals) / n
            means[cat] = mean
            stds[cat] = var ** 0.5

        # insert per-team rows
        for tid, raw in team_raw.items():
            total_z = 0.0
            row = WeekTeamStats(
                league_id=LEAGUE_ID,
                year=season,
                week=week,
                team_id=int(tid),
                team_name=team_name.get(tid, f"Team {tid}"),
                is_league_average=False,
            )

            for cat in CATEGORIES:
                val = raw.get(cat)
                z = _z(float(val), means[cat], stds[cat]) if val is not None else 0.0
                total_z += z
                db_col = CAT_TO_DB_COL[cat]  # e.g. "three_pm_z"
                setattr(row, db_col, float(z))

            row.total_z = float(total_z)
            session.add(row)

        session.commit()
        print(f"WeekTeamStats: built {season} week {week} ({len(team_raw)} teams)")

def main():
    session = SessionLocal()
    try:
        rebuild_weekteamstats(session, 2014, 2026)
    finally:
        session.close()

if __name__ == "__main__":
    main()