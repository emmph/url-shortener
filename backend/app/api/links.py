from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_utils import unified_error_response
from app.core.config import settings
from app.core.rate_limit import RateLimitExceeded, check_create_rate_limit
from app.core.shortener import RESERVED_CODES, generate_short_code
from app.core.url_security import URLValidationError, sanitize_and_normalize_url
from app.db.redis import redis_store
from app.db.session import get_db
from app.models.link import Link
from app.schemas.links import (
    LinkCreateRequest,
    LinkCreateResponse,
    LinkStatsResponse,
    ScanStatusResponse,
)
from app.services.analytics import get_public_link_stats
from app.services.settings_service import (
    get_service_settings,
    is_domain_in_blacklist,
    is_url_blocked,
)
from app.workers.scan_worker import SCAN_QUEUE_KEY, enqueue_link_scan

router = APIRouter(prefix="/api/v1/links", tags=["links"])


def _format_minutes_text(seconds: int) -> str:
    if seconds <= 10:
        return "less than 10 sec"
    if seconds < 60:
        return f"about {seconds} sec"
    minutes = max(1, (seconds + 59) // 60)
    if minutes == 1:
        return "about 1 minute"
    return f"about {minutes} minutes"


@router.post("", response_model=LinkCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_short_link(
    payload: LinkCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    svc_settings = await get_service_settings(db)

    # Bail out if admin paused public link creation
    if not svc_settings.allow_public_creation:
        return unified_error_response(
            503,
            "maintenance",
            "Public link creation is temporarily paused by administrator",
        )

    # Enforce per-IP creation limit
    try:
        await check_create_rate_limit(request, svc_settings.rate_limit_create_per_min)
    except RateLimitExceeded as exc:
        return unified_error_response(
            429,
            "rate_limit",
            exc.detail,
            headers={"Retry-After": str(exc.retry_after)},
        )

    # Validate and normalize URL in memory
    try:
        sanitized = sanitize_and_normalize_url(
            payload.original_url,
            max_length=settings.max_url_length,
        )
    except URLValidationError as exc:
        return unified_error_response(exc.status_code, exc.reason, exc.detail)

    # Reject blocked domains and permanently blocked CVE URLs
    if is_domain_in_blacklist(sanitized.domain, svc_settings.blocked_domains):
        return unified_error_response(
            403,
            "unsafe_url",
            f"Domain '{sanitized.domain}' is blocked by security policy",
        )

    if await is_url_blocked(db, sanitized.url_hash):
        return unified_error_response(
            403,
            "unsafe_url",
            "This URL is blocked due to previously detected CVEs or threats",
        )

    # Protect worker memory when queue is full
    if svc_settings.enable_security_scan:
        queue_len = await redis_store.llen(SCAN_QUEUE_KEY)
        if queue_len >= settings.max_scan_queue_size:
            return unified_error_response(
                503,
                "maintenance",
                "Security scan queue is full. Please try again later",
                headers={"Retry-After": "30"},
            )

    # Pick unique short code or validate custom alias
    if payload.custom_alias:
        if payload.custom_alias.lower() in RESERVED_CODES:
            return unified_error_response(422, "invalid_url", "This custom alias is reserved")
        existing = await db.scalar(select(Link.id).where(Link.short_code == payload.custom_alias))
        if existing is not None:
            return unified_error_response(422, "invalid_url", "This short code is already taken")
        short_code = payload.custom_alias
    else:
        short_code = ""
        for _ in range(10):
            candidate = generate_short_code(settings.short_code_length)
            exists = await db.scalar(select(Link.id).where(Link.short_code == candidate))
            if exists is None:
                short_code = candidate
                break
        if not short_code:
            return unified_error_response(500, "server_error", "Could not generate a unique short code")

    effective_max_clicks = (
        payload.max_clicks if payload.max_clicks is not None else svc_settings.default_max_clicks
    )
    now = datetime.now(timezone.utc)
    expires_at: Optional[datetime] = None
    if payload.expires_in_hours is not None:
        expires_at = now + timedelta(hours=payload.expires_in_hours)

    initial_scan_status = "PENDING" if svc_settings.enable_security_scan else "SAFE"
    link = Link(
        short_code=short_code,
        original_url=sanitized.original_url,
        url_hash=sanitized.url_hash,
        max_clicks=effective_max_clicks,
        clicks_count=0,
        is_active=True,
        scan_status=initial_scan_status,
        risk_score=0,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    # Warm Redis cache immediately
    ttl: Optional[int] = None
    if expires_at is not None:
        ttl = max(60, int((expires_at - now).total_seconds()))

    await redis_store.hset(
        f"link:{short_code}",
        {
            "url": link.original_url,
            "remaining": str(link.max_clicks) if link.max_clicks is not None else "-1",
            "scan_status": initial_scan_status,
            "link_id": str(link.id),
            "expires_at": str(int(expires_at.timestamp())) if expires_at else "0",
        },
        ttl=ttl or 86400,
    )

    estimated_wait = svc_settings.estimated_scan_seconds if svc_settings.enable_security_scan else 0
    if svc_settings.enable_security_scan:
        await enqueue_link_scan(short_code, estimated_wait)

    # Bust admin overview cache
    await redis_store.delete("cache:admin:overview")

    base = str(request.base_url).rstrip("/") if str(request.base_url) else settings.base_url.rstrip("/")
    return LinkCreateResponse(
        short_code=link.short_code,
        short_url=f"{base}/{link.short_code}",
        original_url=link.original_url,
        max_clicks=link.max_clicks,
        scan_status=link.scan_status,
        estimated_wait_seconds=estimated_wait,
        expires_at=link.expires_at,
        created_at=link.created_at,
    )


@router.get("/{short_code}/scan-status", response_model=ScanStatusResponse)
async def get_link_scan_status(
    short_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Read live scan progress and ETA directly from Redis (0 DB hits on hot path)."""
    redis_status = await redis_store.hgetall(f"scan:status:{short_code}")
    if redis_status:
        status_val = redis_status.get("status", "PENDING")
        risk_score = int(redis_status.get("risk_score", "0") or 0)
        stage = redis_status.get("stage", "Running security scan")

        if status_val == "SAFE":
            return ScanStatusResponse(
                short_code=short_code,
                scan_status="SAFE",
                risk_score=risk_score,
                estimated_remaining_seconds=0,
                estimated_remaining_minutes_text="ready",
                stage=stage,
                target_url=f"/{short_code}",
            )

        if status_val == "REMOVED_UNSAFE":
            return ScanStatusResponse(
                short_code=short_code,
                scan_status="REMOVED_UNSAFE",
                risk_score=risk_score,
                estimated_remaining_seconds=0,
                estimated_remaining_minutes_text="blocked",
                stage=stage,
                error_url="/error/410?reason=unavailable",
            )

        started_at = int(redis_status.get("started_at", str(int(time.time()))) or time.time())
        est_total = int(redis_status.get("estimated_seconds", str(settings.scanner_estimated_seconds)) or 15)
        elapsed = max(0, int(time.time()) - started_at)
        remaining = max(3, est_total - elapsed)
        return ScanStatusResponse(
            short_code=short_code,
            scan_status=status_val,
            risk_score=risk_score,
            estimated_remaining_seconds=remaining,
            estimated_remaining_minutes_text=_format_minutes_text(remaining),
            stage=stage,
        )

    # Fall back to link cache if scan status expired
    link_cache = await redis_store.hgetall(f"link:{short_code}")
    if link_cache:
        st = link_cache.get("scan_status", "")
        if st == "SAFE":
            return ScanStatusResponse(
                short_code=short_code,
                scan_status="SAFE",
                estimated_remaining_seconds=0,
                estimated_remaining_minutes_text="ready",
                stage="Scan completed",
                target_url=f"/{short_code}",
            )
        if st == "DEAD":
            return ScanStatusResponse(
                short_code=short_code,
                scan_status="REMOVED_UNSAFE",
                estimated_remaining_seconds=0,
                estimated_remaining_minutes_text="unavailable",
                stage="Link unavailable",
                error_url="/error/410?reason=unavailable",
            )

    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    if link is None:
        return JSONResponse(
            status_code=410,
            content={
                "short_code": short_code,
                "scan_status": "REMOVED_UNSAFE",
                "risk_score": 100,
                "estimated_remaining_seconds": 0,
                "estimated_remaining_minutes_text": "unavailable",
                "stage": "Link not found or removed after security check",
                "error_url": "/error/410?reason=unavailable",
            },
        )

    if link.scan_status == "SAFE":
        return ScanStatusResponse(
            short_code=short_code,
            scan_status="SAFE",
            risk_score=link.risk_score,
            estimated_remaining_seconds=0,
            estimated_remaining_minutes_text="ready",
            stage="Scan passed",
            target_url=f"/{short_code}",
        )

    return ScanStatusResponse(
        short_code=short_code,
        scan_status=link.scan_status,
        risk_score=link.risk_score,
        estimated_remaining_seconds=settings.scanner_estimated_seconds,
        estimated_remaining_minutes_text=_format_minutes_text(settings.scanner_estimated_seconds),
        stage="Security scan in progress",
    )


@router.get("/{short_code}/stats", response_model=LinkStatsResponse)
async def get_link_stats(
    short_code: str,
    db: AsyncSession = Depends(get_db),
):
    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    if link is None:
        return unified_error_response(
            410,
            "unavailable",
            "This link is no longer valid or has reached its visit limit",
        )
    return await get_public_link_stats(db, link)
