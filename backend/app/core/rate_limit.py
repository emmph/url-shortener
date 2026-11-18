from __future__ import annotations

from fastapi import Request

from app.core.config import settings
from app.core.security import compute_ip_hash, extract_client_ip
from app.db.redis import redis_store


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int = 60, detail: str = "Too many requests. Please wait.") -> None:
        super().__init__(detail)
        self.retry_after = retry_after
        self.detail = detail


async def check_create_rate_limit(request: Request, limit_per_min: int) -> None:
    """Enforce per-IP rate limiting for link creation via Redis."""
    if limit_per_min <= 0:
        return
    # Count creations per IP hash inside a 60s bucket
    ip_hash = compute_ip_hash(extract_client_ip(request))
    key = f"rl:create:{ip_hash}"
    count = await redis_store.incr_with_window(key, window_seconds=60)
    if count > limit_per_min:
        raise RateLimitExceeded(
            retry_after=60,
            detail="Link creation rate limit exceeded. Please wait a minute.",
        )


async def check_404_bruteforce_shield(ip_hash: str) -> None:
    """Block IPs hammering non-existent/DEAD short codes (>30 misses/min -> 5 min block)."""
    # Check active 404 ban flag first
    blocked = await redis_store.get_str(f"bf:404:ban:{ip_hash}")
    if blocked:
        raise RateLimitExceeded(
            retry_after=settings.bruteforce_404_block_sec,
            detail="Too many requests to invalid links. Please try again later.",
        )


async def record_404_miss(ip_hash: str) -> None:
    """Increment 404/DEAD counter and trigger temporary block if threshold exceeded."""
    count = await redis_store.incr_with_window(
        f"bf:404:cnt:{ip_hash}",
        window_seconds=settings.bruteforce_404_window_sec,
    )
    # Ban abusive scanner IP for 5 minutes
    if count >= settings.bruteforce_404_threshold:
        await redis_store.set_str(
            f"bf:404:ban:{ip_hash}",
            "1",
            ttl=settings.bruteforce_404_block_sec,
        )
