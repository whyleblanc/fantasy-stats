import os
from espn_api.basketball import League


def get_env_int(name, default=None):
  val = os.environ.get(name)
  if val is None:
    return default
  try:
    return int(val)
  except ValueError:
    return default


def build_league(year: int):
  """
  Build an espn_api League instance for a given year.
  Assumes ESPN_LEAGUE_ID, ESPN_S2, ESPN_SWID are in the environment.
  """
  league_id = get_env_int("ESPN_LEAGUE_ID")
  espn_s2 = os.environ.get("ESPN_S2")
  swid = os.environ.get("ESPN_SWID")

  if not league_id or not espn_s2 or not swid:
    raise RuntimeError(
      "Missing ESPN credentials. Set ESPN_LEAGUE_ID, ESPN_S2, ESPN_SWID in env."
    )

  return League(
    league_id=league_id,
    year=year,
    espn_s2=espn_s2,
    swid=swid,
  )


def get_league_info(year: int) -> dict:
  """
  Returns a dict matching what the frontend expects:

  {
    "leagueName": str,
    "teamCount": int,
    "currentWeek": int,
    "teams": [
      {
        "teamId": int,
        "teamName": str,
        "owners": str,
        "wins": int,
        "losses": int,
        "ties": int or None,
        "pointsFor": float or None,
        "pointsAgainst": float or None,
        "finalStanding": int or None,
      },
      ...
    ]
  }
  """
  league = build_league(year)

  teams_payload = []
  for t in league.teams:
    # espn_api versions vary a bit, be defensive
    owners_raw = getattr(t, "owners", None) or getattr(t, "owner", None)
    if isinstance(owners_raw, (list, tuple)):
      owners = ", ".join(map(str, owners_raw))
    else:
      owners = str(owners_raw) if owners_raw else ""

    wins = getattr(t, "wins", None)
    losses = getattr(t, "losses", None)
    ties = getattr(t, "ties", None)

    points_for = getattr(t, "points_for", None)
    points_against = getattr(t, "points_against", None)

    final_standing = getattr(t, "final_standing", None)

    teams_payload.append(
      {
        "teamId": getattr(t, "team_id", None),
        "teamName": getattr(t, "team_name", ""),
        "owners": owners,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "pointsFor": points_for,
        "pointsAgainst": points_against,
        "finalStanding": final_standing,
      }
    )

  payload = {
    "leagueName": getattr(league, "league_name", "") or "",
    "teamCount": len(teams_payload),
    "currentWeek": getattr(league, "currentMatchupPeriod", None),
    "teams": teams_payload,
  }
  return payload