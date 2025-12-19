import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

LEAGUE_ID = int(os.getenv("LEAGUE_ID", "70600"))
ESPN_S2 = os.getenv("ESPN_S2")
ESPN_SWID = os.getenv("ESPN_SWID")

if not ESPN_S2 or not ESPN_SWID:
    raise SystemExit("Missing ESPN_S2 or ESPN_SWID in env/.env")


def fetch_week(season: int, week: int):
    url = f"https://fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{LEAGUE_ID}"

    params = {
        "scoringPeriodId": week,
        "view": ["mMatchupScore", "mScoreboard", "mTeam", "mSettings"],
    }

    s = requests.Session()

    # Force cookies onto the right domain
    s.cookies.set("espn_s2", ESPN_S2, domain=".espn.com")
    s.cookies.set("SWID", ESPN_SWID, domain=".espn.com")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://fantasy.espn.com/basketball/league?leagueId={LEAGUE_ID}",
        "Origin": "https://fantasy.espn.com",
        "Connection": "keep-alive",
    }

    r = s.get(url, params=params, headers=headers, timeout=30, allow_redirects=True)

    print("HTTP", r.status_code)
    print("Final URL:", r.url)
    if r.history:
        print("Redirect chain:")
        for h in r.history:
            print(" ", h.status_code, "->", h.headers.get("Location"))

    ct = r.headers.get("Content-Type")
    print("Content-Type:", ct)
    print("First 120 chars:", repr(r.text[:120]))

    r.raise_for_status()

    # If ESPN gives us HTML, save it so we can see what it is (login/consent/etc.)
    if ct and "text/html" in ct.lower():
        out = f"/tmp/espn_html_{season}_{week}.html"
        with open(out, "w") as f:
            f.write(r.text)
        raise RuntimeError(f"Got HTML instead of JSON. Saved to {out}. Final URL={r.url}")

    text = r.text.lstrip()
    if text.startswith(")]}'"):
        text = text.split("\n", 1)[1] if "\n" in text else ""

    return json.loads(text)


def main():
    season = 2014
    week = 1
    data = fetch_week(season, week)

    print("top keys:", list(data.keys()))

    sched = data.get("schedule", [])
    print("schedule len:", len(sched))
    if not sched:
        return

    m = sched[0]
    print("matchup keys:", list(m.keys()))

    home = m.get("home", {})
    away = m.get("away", {})
    print("home keys:", list(home.keys()))
    print("away keys:", list(away.keys()))

    for label, side in [("home", home), ("away", away)]:
        for k in side.keys():
            lk = k.lower()
            if "stat" in lk or "score" in lk or "point" in lk:
                v = side.get(k)
                print(f"{label}.{k}: type={type(v).__name__}")
                if isinstance(v, dict):
                    print(f"  {label}.{k} keys:", list(v.keys())[:50])
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    print(f"  {label}.{k}[0] keys:", list(v[0].keys())[:50])

    out = f"/tmp/espn_week_{season}_{week}.json"
    with open(out, "w") as f:
        json.dump(data, f)
    print("saved:", out)


if __name__ == "__main__":
    main()