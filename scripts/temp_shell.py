from db import SessionLocal
from models_normalized import Team, StatWeekly

s = SessionLocal()
print("teams", s.query(Team).filter(Team.season==2026).count())
print("weekly", s.query(StatWeekly).filter(StatWeekly.season==2026).count())
s.close()