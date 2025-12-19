# webapp/services/standings_cache.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

# Key: (season, completed_through_week)
_CACHE: Dict[Tuple[int, int], Dict[str, Any]] = {}
_TS: Dict[Tuple[int, int], float] = {}

DEFAULT_TTL_SECONDS = 60  # short TTL; standings only truly change when a week completes


def get(season: int, completed_through_week: int, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    key = (int(season), int(completed_through_week))
    val = _CACHE.get(key)
    if val is None:
        return None

    ts = _TS.get(key, 0.0)
    if (time.time() - ts) > ttl_seconds:
        _CACHE.pop(key, None)
        _TS.pop(key, None)
        return None

    return val


def set(season: int, completed_through_week: int, payload: Dict[str, Any]) -> None:
    key = (int(season), int(completed_through_week))
    _CACHE[key] = payload
    _TS[key] = time.time()


def invalidate_season(season: int) -> None:
    season = int(season)
    keys = [k for k in _CACHE.keys() if k[0] == season]
    for k in keys:
        _CACHE.pop(k, None)
        _TS.pop(k, None)