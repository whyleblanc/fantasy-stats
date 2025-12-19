from analysis.services import compute_opponent_matrix_multi_for_api
from analysis.constants import CATEGORIES

def test_opponent_matrix_multi_unique_pairs():
    payload = compute_opponent_matrix_multi_for_api(2024, 2026, current_owner_era_only=False)
    rows = payload.get("rows", [])

    # 1) basic shape
    assert payload.get("startYear") == 2024
    assert payload.get("endYear") == 2026
    assert isinstance(rows, list)

    # 2) composite key uniqueness
    pairs = [(int(r["teamId"]), int(r["opponentId"])) for r in rows]
    assert len(pairs) == len(set(pairs)), "Duplicate (teamId, opponentId) rows detected"

    # 3) minimal schema sanity
    for r in rows[:10]:  # sample
        assert "overall" in r and "categories" in r
        assert set(CATEGORIES).issubset(set(r["categories"].keys()))

def test_opponent_matrix_team_has_unique_opponents():
    payload = compute_opponent_matrix_multi_for_api(2024, 2026, current_owner_era_only=False)
    rows = payload.get("rows", [])

    # pick a team that exists in your league (teamId=1 in your curl example)
    team_id = 1
    team_rows = [r for r in rows if int(r["teamId"]) == team_id]
    opps = [int(r["opponentId"]) for r in team_rows]
    assert len(opps) == len(set(opps)), "Duplicate opponentId rows for the same teamId"