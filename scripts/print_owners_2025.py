# scripts/print_owners_2025.py

import os
import sys

# Ensure project root is on sys.path so `analysis` is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analysis.loaders import get_league  # noqa: E402

TARGET_YEAR = 2025  # change this if you want another season


def main():
    league = get_league(TARGET_YEAR)

    print(f"League: {league.settings.name} ({TARGET_YEAR})")
    print("-" * 60)
    print("team_id\tteam_name\towner")

    for team in league.teams:
        # espn_api.basketball.Team usually has .owner; fall back to abbrev
        owner = getattr(team, "owner", None) or getattr(team, "team_abbrev", "")
        print(f"{team.team_id}\t{team.team_name}\t{owner}")


if __name__ == "__main__":
    main()