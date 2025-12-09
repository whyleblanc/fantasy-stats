# webapp/config.py

import os
from dotenv import load_dotenv

# Load .env once, here
load_dotenv()


class Config:
    """
    Central place for environment-driven settings.
    Extend this as needed (DB URI, logging, etc.).
    """

    # ESPN / league credentials
    LEAGUE_ID = int(os.getenv("LEAGUE_ID", "0"))
    SWID = os.getenv("SWID") or ""
    ESPN_S2 = os.getenv("ESPN_S2") or ""

    # Year range for your league history
    MIN_YEAR = int(os.getenv("MIN_YEAR", "2014"))
    MAX_YEAR = int(os.getenv("MAX_YEAR", "2026"))

    # Flask / SQLAlchemy / misc options can live here too
    # (Your db.py already handles engine creation, so no need to duplicate.)


# Convenience aliases so old code can still do:
# from webapp.config import MIN_YEAR, MAX_YEAR, LEAGUE_ID, SWID, ESPN_S2
LEAGUE_ID = Config.LEAGUE_ID
SWID = Config.SWID
ESPN_S2 = Config.ESPN_S2
MIN_YEAR = Config.MIN_YEAR
MAX_YEAR = Config.MAX_YEAR