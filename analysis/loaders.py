import os
from functools import lru_cache

from dotenv import load_dotenv
from espn_api.basketball import League

load_dotenv()

# Shared league credentials
LEAGUE_ID = int(os.getenv("LEAGUE_ID"))
SWID = os.getenv("SWID")
ESPN_S2 = os.getenv("ESPN_S2")


@lru_cache(maxsize=64)
def get_league(year: int) -> League:
    """
    Shared League loader with simple in-memory cache.
    Anything that needs ESPN data should call this.
    """
    return League(
        league_id=LEAGUE_ID,
        year=year,
        swid=SWID,
        espn_s2=ESPN_S2,
    )