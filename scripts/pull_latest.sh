#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Activate venv if it exists (safe in VS Code tasks + terminal)
if [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
fi

# Resolve season (prefer env override, otherwise MAX_YEAR from config)
SEASON="${SEASON:-$(PYTHONPATH=. python -c 'from webapp.config import MAX_YEAR; print(int(MAX_YEAR))')}"

echo "[1/3] Pull latest completed week (season=${SEASON})"
PYTHONPATH=. python scripts/pull_week.py --latest

echo "[2/3] Rebuild opponent_matrix_agg_year (season=${SEASON})"
PYTHONPATH=. python scripts/rebuild_opponent_matrix_agg_year.py --year "${SEASON}" --force

echo "[3/3] Rebuild team_history_agg (season=${SEASON})"
PYTHONPATH=. python scripts/rebuild_team_history_agg_year.py --year "${SEASON}" --force