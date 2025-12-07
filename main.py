from espn_api.basketball import League
from dotenv import load_dotenv
import os


# Load values from .env in the project root
load_dotenv()

# Read secrets from environment
LEAGUE_ID = int(os.getenv("LEAGUE_ID"))
SWID = os.getenv("SWID")
ESPN_S2 = os.getenv("ESPN_S2")


def format_owners(team) -> str:
    """
    Safely format owners from whatever espn_api gives us:
    - list of strings
    - list of dicts
    - single string
    - None
    """
    owners_raw = getattr(team, "owners", None)

    if owners_raw is None:
        return "Unknown"

    # If it's a single string, just return it
    if isinstance(owners_raw, str):
        return owners_raw

    # If it's a list, convert each element to a readable string
    if isinstance(owners_raw, list):
        formatted = []
        for o in owners_raw:
            # If dict, try to pull a useful field, otherwise str() it
            if isinstance(o, dict):
                # Try a couple of likely keys; fall back to full dict repr
                name = o.get("owner") or o.get("nickname") or o.get("firstName") or None
                formatted.append(name if name is not None else str(o))
            else:
                formatted.append(str(o))
        return ", ".join(formatted)

    # Fallback: just stringify whatever it is
    return str(owners_raw)


def main():
    year = 2025

    league = League(
        league_id=LEAGUE_ID,
        year=year,
        swid=SWID,
        espn_s2=ESPN_S2,
    )

    print(f"League: {league.settings.name} ({year})\n")

    print("Teams:")
    for team in league.teams:
        owners = format_owners(team)
        print(f"- {team.team_name} ({owners}) | {team.wins}-{team.losses}")


if __name__ == "__main__":
    main()