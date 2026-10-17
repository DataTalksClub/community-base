"""Fixed-window IP budgets for the anonymous device endpoints."""

from __future__ import annotations

from django.core.cache import cache

START_LIMIT = 10
START_WINDOW_SECONDS = 600
POLL_LIMIT = 240
POLL_WINDOW_SECONDS = 600


def _key(prefix: str, ip: str) -> str:
    return f"device-login:{prefix}:{ip or 'unknown'}"


def check_budget(*, prefix: str, ip: str, limit: int, window: int) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Counts the call when allowed."""
    key = _key(prefix, ip)
    try:
        count = cache.get(key, 0)
    except Exception:
        return True, 0
    if count >= limit:
        return False, window
    try:
        if count:
            cache.incr(key)
        else:
            cache.set(key, 1, window)
    except Exception:
        pass
    return True, 0
