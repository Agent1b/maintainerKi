from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from time import monotonic

from fastapi import HTTPException, status


@dataclass(slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


@dataclass(slots=True)
class _WindowState:
    events: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, _WindowState] = {}

    def consume(
        self,
        scope: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        block_seconds: int = 0,
    ) -> RateLimitDecision:
        if limit <= 0 or window_seconds <= 0:
            return RateLimitDecision(allowed=True, retry_after_seconds=0, remaining=max(limit, 0))

        now = monotonic()
        state_key = f"{scope}:{key}"

        with self._lock:
            state = self._states.setdefault(state_key, _WindowState())
            self._prune(state, now=now, window_seconds=window_seconds)

            if state.blocked_until > now:
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=max(1, math.ceil(state.blocked_until - now)),
                    remaining=0,
                )

            if len(state.events) >= limit:
                retry_after_seconds = max(
                    1,
                    math.ceil(window_seconds - (now - state.events[0])),
                )
                if block_seconds > 0:
                    state.blocked_until = now + block_seconds
                    retry_after_seconds = block_seconds
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after_seconds,
                    remaining=0,
                )

            state.events.append(now)
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                remaining=max(0, limit - len(state.events)),
            )

    def clear(self, scope: str, key: str) -> None:
        state_key = f"{scope}:{key}"
        with self._lock:
            self._states.pop(state_key, None)

    @staticmethod
    def _prune(state: _WindowState, *, now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while state.events and state.events[0] <= cutoff:
            state.events.popleft()
        if state.blocked_until <= now and not state.events:
            state.blocked_until = 0.0


rate_limiter = InMemoryRateLimiter()


def too_many_requests(detail: str, retry_after_seconds: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(retry_after_seconds, 1))},
    )
