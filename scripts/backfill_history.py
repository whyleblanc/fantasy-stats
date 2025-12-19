from db import SessionLocal
from webapp.services.espn_ingest import sync_week
from webapp.config import LEAGUE_ID
from dotenv import load_dotenv
import os

load_dotenv()

ESPN_SWID = os.getenv("ESPN_SWID")
ESPN_S2 = os.getenv("ESPN_S2")

YEARS = range(2014, 2026)
MAX_WEEKS = 22

for year in YEARS:
    for week in range(1, MAX_WEEKS + 1):
        session = SessionLocal()
        try:
            print(f"Ingesting {year} week {week}...")
            sync_week(
                session=session,
                league_id=LEAGUE_ID,
                season=year,
                week=week,
                espn_swid=ESPN_SWID,
                espn_s2=ESPN_S2,
            )
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"Stopping {year} at week {week}: {e}")
            break
        finally:
            session.close()