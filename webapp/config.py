# webapp/config.py

import os
from dotenv import load_dotenv

# Load .env into environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Module-level constants (for legacy imports)
# ---------------------------------------------------------------------------

LEAGUE_ID = int(os.getenv("LEAGUE_ID", "70600"))

# Historical bounds – safe defaults if not in .env
MIN_YEAR = int(os.getenv("MIN_YEAR", "2014"))
MAX_YEAR = int(os.getenv("MAX_YEAR", "2026"))

ESPN_SWID = os.getenv("ESPN_SWID")
ESPN_S2 = os.getenv("ESPN_S2")

# ---------------------------------------------------------------------------
# Flask Config object (used by create_app)
# ---------------------------------------------------------------------------

class Config:
    LEAGUE_ID = LEAGUE_ID
    MIN_YEAR = MIN_YEAR
    MAX_YEAR = MAX_YEAR

    ESPN_SWID = ESPN_SWID
    ESPN_S2 = ESPN_S2