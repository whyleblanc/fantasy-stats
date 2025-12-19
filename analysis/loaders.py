import os
from functools import lru_cache

from dotenv import load_dotenv
from espn_api.basketball import League

load_dotenv()

LEAGUE_ID = int(os.getenv("LEAGUE_ID", "0"))

# Accept either naming convention
SWID = os.getenv("ESPN_SWID") or os.getenv("SWID")
ESPN_S2 = os.getenv("ESPN_S2")

def _require_env():
    missing = []
    if not LEAGUE_ID:
        missing.append("LEAGUE_ID")
    if not SWID:
        missing.append("ESPN_SWID (or SWID)")
    if not ESPN_S2:
        missing.append("ESPN_S2")
    if missing:
        raise RuntimeError(
            "Missing ESPN env vars: " + ", ".join(missing) +
            ". Check your .env and restart the terminal/server."
        )

@lru_cache(maxsize=64)
def get_league(year: int) -> League:
    _require_env()
    return League(
        league_id=LEAGUE_ID,
        year=year,
        swid=SWID,
        espn_s2=ESPN_S2,
    )