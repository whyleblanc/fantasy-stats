# webapp/services/espn_ingest.py
"""
ESPN ingestion pipeline.

This module defines a single public entrypoint:

    sync_week(session, league_id, season, week, espn_swid, espn_s2)

It:
- Pulls weekly boxscores from ESPN via espn_api.
- Ensures Team and Player rows exist.
- Writes/updates Matchup + StatRaw rows.
- Aggregates into StatWeekly and StatSeason.

It **does not**:
- Do any advanced analytics (z-scores, power, luck, etc.).
- Talk to Flask or deal with HTTP directly.

Routes, CLI scripts, or background jobs should import and call `sync_week`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Dict, Iterable, Tuple

from espn_api.basketball import League
from sqlalchemy.orm import Session

from models_normalized import (
    Player,
    Team,
    Matchup,
    StatRaw,
    StatWeekly,
    StatSeason,
)


# ---------- Public API ----------


def sync_week(
    session: Session,
    league_id: int,
    season: int,
    week: int,
    espn_swid: str,
    espn_s2: str,
) -> None:
    """
    Ingest one scoring period (week) from ESPN into normalized tables.

    This function is intentionally "dumb" and deterministic:
    - No retries, no async, no Flask coupling.
    - All write operations are done via the supplied SQLAlchemy Session.
    - It does NOT commit; the caller is responsible for commit/rollback.

    Parameters
    ----------
    session : Session
        SQLAlchemy session to use for all DB operations.
    league_id : int
        ESPN league id (e.g. 70600).
    season : int
        Fantasy season year (e.g. 2025).
    week : int
        Scoring period id (ESPN uses 1-based week index).
    espn_swid : str
        ESPN SWID cookie value.
    espn_s2 : str
        ESPN espn_s2 cookie value.
    """
    # 1. Load league from ESPN
    league = League(
        league_id=league_id,
        year=season,
        swid=espn_swid,
        espn_s2=espn_s2,
    )

    # 2. Ensure Team rows exist / are updated
    teams_by_espn_id: Dict[int, Team] = _ensure_teams(session, league, league_id, season)

    session.flush()  # ensure Team.id is available

    # 3. Pull weekly boxscores (handle espn_api version differences)
    boxscores = _get_boxscores_for_week(league, week)

    # accumulator for per-team-per-week totals
    team_week_totals: DefaultDict[Tuple[int, int], Dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # 4. Process each matchup
    for matchup_index, bs in enumerate(boxscores, start=1):
        _sync_matchup_and_sides(
            session=session,
            league_id=league_id,
            season=season,
            week=week,
            matchup_index=matchup_index,
            boxscore=bs,
            teams_by_espn_id=teams_by_espn_id,
            team_week_totals=team_week_totals,
        )

    # 5. Write per-team-per-week totals
    _write_weekly_totals(
        session=session,
        league_id=league_id,
        season=season,
        week=week,
        team_week_totals=team_week_totals,
    )

    # 6. Recompute per-team-per-season aggregates for this league+season
    _refresh_season_totals(
        session=session,
        league_id=league_id,
        season=season,
    )

    # NOTE: no commit here. Caller decides when to commit.


# ---------- Internal helpers ----------


def _get_boxscores_for_week(league, week):
    """
    Compatibility wrapper around espn_api's boxscore APIs.

    Different versions expose different methods:
      - league.boxscore(week)
      - league.box_scores(week)
      - league.boxscores(week)

    We try them in a sensible order and raise a clear error if none exist.
    """
    # Newer espn_api versions often use box_scores
    if hasattr(league, "box_scores"):
        return league.box_scores(week)

    # Older versions
    if hasattr(league, "boxscore"):
        return league.boxscore(week)

    if hasattr(league, "boxscores"):
        return league.boxscores(week)

    raise AttributeError(
        "League object has no boxscore/box_scores method; "
        "check espn_api version and update _get_boxscores_for_week."
    )

def _ensure_teams(session: Session, league: League, league_id: int, season: int) -> Dict[int, Team]:
    """
    Ensure Team rows exist for all ESPN teams in this league+season.

    Returns a dict mapping espn_team_id -> Team ORM instance.
    """
    teams_by_espn_id: Dict[int, Team] = {}

    for espn_team in league.teams:
        team = (
            session.query(Team)
            .filter_by(
                league_id=league_id,
                season=season,
                espn_team_id=espn_team.team_id,
            )
            .one_or_none()
        )

        if team is None:
            team = Team(
                league_id=league_id,
                season=season,
                espn_team_id=espn_team.team_id,
                name=espn_team.team_name,
                abbrev=espn_team.team_abbrev,
                owner=getattr(espn_team, "owner", None),
            )
            session.add(team)
        else:
            # keep metadata reasonably fresh
            team.name = espn_team.team_name
            team.abbrev = espn_team.team_abbrev
            team.owner = getattr(espn_team, "owner", team.owner)

        teams_by_espn_id[espn_team.team_id] = team

    return teams_by_espn_id


def _sync_matchup_and_sides(
    session: Session,
    league_id: int,
    season: int,
    week: int,
    matchup_index: int,
    boxscore,
    teams_by_espn_id: Dict[int, Team],
    team_week_totals: DefaultDict[Tuple[int, int], Dict[str, int]],
) -> None:
    """
    Create/update Matchup row and sync both home and away sides.
    """
    # ESPN objects: adjust attributes if your espn_api version differs.
    home_espn_team_id = boxscore.home_team.team_id
    away_espn_team_id = boxscore.away_team.team_id

    home_team = teams_by_espn_id[home_espn_team_id]
    away_team = teams_by_espn_id[away_espn_team_id]

    matchup = (
        session.query(Matchup)
        .filter_by(
            league_id=league_id,
            season=season,
            week=week,
            matchup_id=matchup_index,
        )
        .one_or_none()
    )

    if matchup is None:
        matchup = Matchup(
            league_id=league_id,
            season=season,
            week=week,
            matchup_id=matchup_index,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            is_playoffs=bool(getattr(boxscore, "is_playoff", False)),
            is_consolation=bool(getattr(boxscore, "is_consolation", False)),
        )
        session.add(matchup)
    else:
        # if teams were changed somehow, keep in sync
        matchup.home_team_id = home_team.id
        matchup.away_team_id = away_team.id
        matchup.is_playoffs = bool(getattr(boxscore, "is_playoff", matchup.is_playoffs))
        matchup.is_consolation = bool(
            getattr(boxscore, "is_consolation", matchup.is_consolation)
        )

    # winner_team_id
    winner = getattr(boxscore, "winner", None)
    if winner == "HOME":
        matchup.winner_team_id = home_team.id
    elif winner == "AWAY":
        matchup.winner_team_id = away_team.id
    else:
        matchup.winner_team_id = None

    # Sync stats for home and away sides
    _sync_side_stats(
        session=session,
        league_id=league_id,
        season=season,
        week=week,
        team=home_team,
        players_stats=boxscore.home_lineup,
        team_week_totals=team_week_totals,
    )

    _sync_side_stats(
        session=session,
        league_id=league_id,
        season=season,
        week=week,
        team=away_team,
        players_stats=boxscore.away_lineup,
        team_week_totals=team_week_totals,
    )


def _sync_side_stats(
    session: Session,
    league_id: int,
    season: int,
    week: int,
    team: Team,
    players_stats: Iterable,
    team_week_totals: DefaultDict[Tuple[int, int], Dict[str, int]],
) -> None:
    """
    Sync StatRaw rows for one fantasy team side (home or away) in a matchup.

    `players_stats` is an iterable of BoxScorePlayer objects from espn_api.

    IMPORTANT:
    The exact way to pull stats out of the espn_api objects may vary by version.
    You must inspect one BoxScorePlayer in a Python shell and adapt the
    `ADAPT ME` section below accordingly.
    """
    for p in players_stats:
        # --- 1. Ensure Player row exists ---
        espn_player_id = getattr(p, "playerId", None)
        if espn_player_id is None:
            # Failsafe – if espn_api changes attribute names, we want a loud error.
            raise RuntimeError(f"BoxScorePlayer missing playerId attribute: {p!r}")

        full_name = getattr(p, "name", None) or getattr(p, "fullName", "Unknown")

        player = (
            session.query(Player)
            .filter_by(espn_player_id=espn_player_id)
            .one_or_none()
        )

        if player is None:
            positions = getattr(p, "eligibleSlots", None)
            if isinstance(positions, (list, tuple)):
                positions_str = ",".join(str(pos) for pos in positions)
            else:
                positions_str = None

            pro_team = getattr(p, "proTeam", None)

            player = Player(
                espn_player_id=espn_player_id,
                full_name=full_name,
                positions=positions_str,
                pro_team=pro_team,
                active=True,
            )
            session.add(player)
            session.flush()  # ensure player.id is set

        # --- 2. Pull raw stat values (ADAPT ME) ---

        # Many espn_api versions expose stats as a dict on .stats
        # and/or a "total" entry for the week. You must confirm in your
        # environment. Example structure (pseudo):
        #
        #   p.stats = {
        #       season: {
        #           'total': { 'FGM': 30, 'FGA': 60, ... }
        #       }
        #   }
        #
        # For now, we look for the most common patterns and fall back to 0.

        stats_raw = {}

        # try common "stats" -> "total" pattern first
        raw_stats_attr = getattr(p, "stats", None)
        if isinstance(raw_stats_attr, dict):
            # try to find a "total" dict somewhere
            if "total" in raw_stats_attr and isinstance(raw_stats_attr["total"], dict):
                stats_raw = raw_stats_attr["total"]
            else:
                # sometimes stats are keyed by scoring period or season
                # we naively take the first dict value that looks like stats
                for val in raw_stats_attr.values():
                    if isinstance(val, dict):
                        if "total" in val and isinstance(val["total"], dict):
                            stats_raw = val["total"]
                            break
                        stats_raw = val
                        break

        # Pull individual stats with safe defaults
        def _get_int(key: str) -> int:
            val = stats_raw.get(key, 0) if isinstance(stats_raw, dict) else 0
            try:
                return int(val)
            except (TypeError, ValueError):
                return 0

        fgm = _get_int("FGM")
        fga = _get_int("FGA")
        ftm = _get_int("FTM")
        fta = _get_int("FTA")
        tpm = _get_int("3PM")
        reb = _get_int("REB")
        ast = _get_int("AST")
        stl = _get_int("STL")
        blk = _get_int("BLK")
        pts = _get_int("PTS")
        dd = _get_int("DD")
        gp = _get_int("GP")

        # If your league/provider doesn't track DD at player level,
        # you can leave dd=0 and derive team-level DD later.

        # --- 3. Upsert StatRaw row ---

        raw = (
            session.query(StatRaw)
            .filter_by(
                league_id=league_id,
                season=season,
                week=week,
                team_id=team.id,
                player_id=player.id,
            )
            .one_or_none()
        )

        if raw is None:
            raw = StatRaw(
                league_id=league_id,
                season=season,
                week=week,
                team_id=team.id,
                player_id=player.id,
            )
            session.add(raw)

        raw.games_played = gp
        raw.fgm = fgm
        raw.fga = fga
        raw.ftm = ftm
        raw.fta = fta
        raw.tpm = tpm
        raw.reb = reb
        raw.ast = ast
        raw.stl = stl
        raw.blk = blk
        raw.pts = pts
        raw.dd = dd

        # --- 4. Accumulate into team-week totals ---

        key = (league_id, team.id)
        agg = team_week_totals[key]

        agg["games_played"] += gp
        agg["fgm"] += fgm
        agg["fga"] += fga
        agg["ftm"] += ftm
        agg["fta"] += fta
        agg["tpm"] += tpm
        agg["reb"] += reb
        agg["ast"] += ast
        agg["stl"] += stl
        agg["blk"] += blk
        agg["pts"] += pts
        agg["dd"] += dd


def _write_weekly_totals(
    session: Session,
    league_id: int,
    season: int,
    week: int,
    team_week_totals: DefaultDict[Tuple[int, int], Dict[str, int]],
) -> None:
    """
    Persist StatWeekly entries from accumulated team_week_totals.
    """
    for (lg_id, team_id), stats in team_week_totals.items():
        if lg_id != league_id:
            # Sanity check: we don't expect mismatched league ids
            raise RuntimeError(
                f"team_week_totals contains mismatched league_id={lg_id}, expected {league_id}"
            )

        weekly = (
            session.query(StatWeekly)
            .filter_by(
                league_id=league_id,
                season=season,
                week=week,
                team_id=team_id,
            )
            .one_or_none()
        )

        if weekly is None:
            weekly = StatWeekly(
                league_id=league_id,
                season=season,
                week=week,
                team_id=team_id,
            )
            session.add(weekly)

        weekly.games_played = stats.get("games_played", 0)

        weekly.fgm = stats.get("fgm", 0)
        weekly.fga = stats.get("fga", 0)
        weekly.ftm = stats.get("ftm", 0)
        weekly.fta = stats.get("fta", 0)
        weekly.tpm = stats.get("tpm", 0)
        weekly.reb = stats.get("reb", 0)
        weekly.ast = stats.get("ast", 0)
        weekly.stl = stats.get("stl", 0)
        weekly.blk = stats.get("blk", 0)
        weekly.pts = stats.get("pts", 0)
        weekly.dd = stats.get("dd", 0)

        # derived percentages
        weekly.fg_pct = (
            weekly.fgm / weekly.fga if weekly.fga and weekly.fga > 0 else None
        )
        weekly.ft_pct = (
            weekly.ftm / weekly.fta if weekly.fta and weekly.fta > 0 else None
        )


def _refresh_season_totals(
    session: Session,
    league_id: int,
    season: int,
) -> None:
    """
    Recompute StatSeason for all teams in this league+season based on StatWeekly.

    Simple approach:
    - Delete existing StatSeason rows for (league_id, season)
    - Re-aggregate from StatWeekly
    """
    session.query(StatSeason).filter_by(
        league_id=league_id,
        season=season,
    ).delete(synchronize_session=False)

    # Get distinct team_ids that have weekly stats
    team_ids = [
        row[0]
        for row in (
            session.query(StatWeekly.team_id)
            .filter_by(league_id=league_id, season=season)
            .distinct()
            .all()
        )
    ]

    for team_id in team_ids:
        weekly_rows = (
            session.query(StatWeekly)
            .filter_by(
                league_id=league_id,
                season=season,
                team_id=team_id,
            )
            .all()
        )

        if not weekly_rows:
            continue

        season_row = StatSeason(
            league_id=league_id,
            season=season,
            team_id=team_id,
        )

        # ensure all numeric fields start from 0, not None
        season_row.games_played = 0
        season_row.fgm = 0
        season_row.fga = 0
        season_row.ftm = 0
        season_row.fta = 0
        season_row.tpm = 0
        season_row.reb = 0
        season_row.ast = 0
        season_row.stl = 0
        season_row.blk = 0
        season_row.pts = 0
        season_row.dd = 0

        for w in weekly_rows:
            season_row.games_played += w.games_played or 0
            season_row.fgm += w.fgm or 0
            season_row.fga += w.fga or 0
            season_row.ftm += w.ftm or 0
            season_row.fta += w.fta or 0
            season_row.tpm += w.tpm or 0
            season_row.reb += w.reb or 0
            season_row.ast += w.ast or 0
            season_row.stl += w.stl or 0
            season_row.blk += w.blk or 0
            season_row.pts += w.pts or 0
            season_row.dd += w.dd or 0

        season_row.fg_pct = (
            season_row.fgm / season_row.fga if season_row.fga > 0 else None
        )
        season_row.ft_pct = (
            season_row.ftm / season_row.fta if season_row.fta > 0 else None
        )

        session.add(season_row)