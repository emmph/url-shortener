from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_utils import browser_or_json_error, is_browser_navigation
from app.core.bot_shield import build_bot_preview_response, is_bot_or_prefetch_request
from app.core.rate_limit import RateLimitExceeded, check_404_bruteforce_shield, record_404_miss
from app.core.security import compute_ip_hash, extract_client_ip
from app.core.shortener import RESERVED_CODES
from app.core.ua_parser import parse_user_agent
from app.core.url_security import VALID_SHORT_CODE_RE
from app.db.redis import redis_store
from app.db.session import get_db
from app.models.link import Link

router = APIRouter(tags=["redirect"])

# Headers keeping redirect uncached and hiding referrer
_SAFE_REDIRECT_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Opener-Policy": "same-origin",
}


async def _warm_cache_from_db(db: AsyncSession, short_code: str) -> str:
    """Fallback DB lookup ONLY on Redis cache miss; populates link cache or DEAD tombstone."""
    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    now = datetime.now(timezone.utc)

    # Write a 15-min dead tombstone if missing, disabled, expired, or exhausted
    if (
        link is None
        or not link.is_active
        or (link.expires_at is not None and link.expires_at <= now)
        or (link.max_clicks is not None and link.clicks_count >= link.max_clicks)
    ):
        await redis_store.hset(f"link:{short_code}", {"scan_status": "DEAD"}, ttl=900)
        return "DEAD"

    ttl: Optional[int] = None
    if link.expires_at is not None:
        ttl = max(60, int((link.expires_at - now).total_seconds()))

    remaining = (
        max(0, link.max_clicks - link.clicks_count) if link.max_clicks is not None else -1
    )
    await redis_store.hset(
        f"link:{short_code}",
        {
            "url": link.original_url,
            "remaining": str(remaining),
            "scan_status": link.scan_status,
            "link_id": str(link.id),
            "expires_at": str(int(link.expires_at.timestamp())) if link.expires_at else "0",
        },
        ttl=ttl or 86400,
    )
    return link.scan_status


@router.api_route("/{short_code}", methods=["GET", "HEAD"])
async def redirect_short_link(
    short_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Skip non-link routes and bad code formats
    if short_code.lower() in RESERVED_CODES or not VALID_SHORT_CODE_RE.match(short_code):
        return browser_or_json_error(
            request,
            404,
            "page_not_found",
            "Page not found",
        )

    # Protect one-time/limited links from chat preview bots and browser prefetch
    if is_bot_or_prefetch_request(request):
        return build_bot_preview_response(is_head=(request.method.upper() == "HEAD"))

    ip_hash = compute_ip_hash(extract_client_ip(request))

    # Block IPs guessing non-existent short codes
    try:
        await check_404_bruteforce_shield(ip_hash)
    except RateLimitExceeded as exc:
        return browser_or_json_error(
            request,
            429,
            "rate_limit",
            exc.detail,
            headers={"Retry-After": str(exc.retry_after)},
        )

    ua_raw = request.headers.get("user-agent", "")
    device_type, browser = parse_user_agent(ua_raw)
    referer_raw = request.headers.get("referer")
    referer = referer_raw[:255] if referer_raw else None

    event_payload = {
        "ts": int(time.time()),
        "ip_hash": ip_hash,
        "dev": device_type,
        "br": browser,
        "ref": referer,
        "short_code": short_code,
    }

    # Run atomic Redis Lua check (<0.5ms, zero DB writes)
    status_tag, target_url, _ = await redis_store.execute_redirect_lua(
        short_code,
        event_payload,
    )

    if status_tag == "MISS":
        warmed_status = await _warm_cache_from_db(db, short_code)
        if warmed_status == "DEAD":
            status_tag = "DEAD"
        else:
            status_tag, target_url, _ = await redis_store.execute_redirect_lua(
                short_code,
                event_payload,
            )

    # Hold user on waiting page while CVE scan finishes (do not burn clicks)
    if status_tag == "SCANNING":
        scan_info = await redis_store.hgetall(f"scan:status:{short_code}")
        est_sec = int(scan_info.get("estimated_seconds", "15") or 15)
        started_at = int(scan_info.get("started_at", str(int(time.time()))) or time.time())
        rem_sec = max(3, est_sec - max(0, int(time.time()) - started_at))
        minutes = max(1, (rem_sec + 59) // 60)

        if is_browser_navigation(request):
            return RedirectResponse(
                url=f"/scanning/{short_code}",
                status_code=307,
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
        return JSONResponse(
            status_code=423,
            content={
                "error_code": 423,
                "reason": "scanning",
                "detail": (
                    f"Link is unavailable until security scan completes "
                    f"(ready in ~{minutes} min / {rem_sec} sec)"
                ),
                "scan_url": f"/scanning/{short_code}",
                "estimated_remaining_seconds": rem_sec,
            },
            headers={"Retry-After": str(rem_sec), "Cache-Control": "no-store"},
        )

    # Handle missing, blocked, expired, or exhausted links uniformly
    if status_tag == "DEAD" or not target_url:
        await record_404_miss(ip_hash)
        return browser_or_json_error(
            request,
            410,
            "unavailable",
            "This link is no longer valid or has reached its visit limit",
        )

    return RedirectResponse(
        url=target_url,
        status_code=307,
        headers=_SAFE_REDIRECT_HEADERS,
    )
