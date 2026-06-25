from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

_MAX_RESULTS = 200
_lock = Lock()
_results: deque[dict[str, Any]] = deque(maxlen=_MAX_RESULTS)


def record_scoring_result(result: dict[str, Any]) -> None:
    with _lock:
        _results.appendleft(result)


def list_scoring_results(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        return list(_results)[:limit]
