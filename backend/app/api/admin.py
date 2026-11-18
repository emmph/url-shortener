from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_utils import unified_error_response
from app.core.security import require_admin
from app.db.redis import redis_store
from app.db.session import get_db
from app.models.blocked_url import BlockedUrl
from app.models.link import Link
from app.schemas.admin import (
    AdminLinkDetailStatsResponse,
    AdminLinkItem,
    AdminLinksListResponse,
    AdminLinkUpdateRequest,
    AdminOverviewResponse,
    BlockedUrlItem,
    BlockedUrlsListResponse,
    MaintenanceResponse,
    ServiceSettingsSchema,
)
from app.services.analytics import get_admin_link_detail_stats, get_admin_overview
from app.services.settings_service import (
    BLOCKED_URLS_SET_KEY,
    get_service_settings,
    update_service_settings,
)
from app.workers.analytics_flusher import flush_analytics_batch
from app.workers.scan_worker import enqueue_link_scan

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


async def _sync_link_cache(link: Link) -> None:
    """Keep Redis hot cache synced after admin edits."""
    now = datetime.now(timezone.utc)
    await redis_store.delete(f"cache:stats:{link.short_code}", "cache:admin:overview")

    if (
        not link.is_active
        or (link.expires_at is not None and link.expires_at <= now)
        or (link.max_clicks is not None and link.clicks_count >= link.max_clicks)
    ):
        await redis_store.hset(f"link:{link.short_code}", {"scan_status": "DEAD"}, ttl=900)
        return

    ttl: Optional[int] = None
    if link.expires_at is not None:
        ttl = max(60, int((link.expires_at - now).total_seconds()))

    remaining = (
        max(0, link.max_clicks - link.clicks_count) if link.max_clicks is not None else -1
    )
    await redis_store.hset(
        f"link:{link.short_code}",
        {
            "url": link.original_url,
            "remaining": str(remaining),
            "scan_status": link.scan_status,
            "link_id": str(link.id),
            "expires_at": str(int(link.expires_at.timestamp())) if link.expires_at else "0",
        },
        ttl=ttl or 86400,
    )


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    # Flush buffered clicks so metrics stay fresh
    await flush_analytics_batch(500)
    return await get_admin_overview(db, use_cache=(not refresh))


@router.get("/links", response_model=AdminLinksListResponse)
async def admin_list_links(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    status_filter: str = Query(default="all", alias="filter"),
    scan_filter: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Link)
    count_stmt = select(func.count(Link.id))

    if search:
        pattern = f"%{search.strip()}%"
        cond = or_(Link.short_code.ilike(pattern), Link.original_url.ilike(pattern))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    now = datetime.now(timezone.utc)
    if status_filter == "active":
        cond = Link.is_active.is_(True)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    elif status_filter == "exhausted":
        cond = (Link.max_clicks.is_not(None)) & (Link.clicks_count >= Link.max_clicks)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    elif status_filter == "disabled":
        cond = Link.is_active.is_(False)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    elif status_filter == "one_time":
        cond = Link.max_clicks == 1
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    elif status_filter == "limited":
        cond = Link.max_clicks.is_not(None)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    elif status_filter == "expired":
        cond = Link.expires_at.is_not(None) & (Link.expires_at <= now)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    if scan_filter:
        cond = Link.scan_status == scan_filter.upper()
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int(await db.scalar(count_stmt) or 0)
    rows = (
        await db.execute(
            stmt.order_by(desc(Link.created_at), desc(Link.id))
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()

    return AdminLinksListResponse(
        total=total,
        page=page,
        limit=limit,
        items=[
            AdminLinkItem(
                id=r.id,
                short_code=r.short_code,
                original_url=r.original_url,
                max_clicks=r.max_clicks,
                clicks_count=r.clicks_count,
                is_active=r.is_active,
                scan_status=r.scan_status,
                risk_score=r.risk_score,
                scan_report=r.scan_report,
                expires_at=r.expires_at,
                created_at=r.created_at,
            )
            for r in rows
        ],
    )


@router.get("/links/{short_code}/stats", response_model=AdminLinkDetailStatsResponse)
async def admin_link_detail_stats(
    short_code: str,
    db: AsyncSession = Depends(get_db),
):
    await flush_analytics_batch(500)
    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    if link is None:
        return unified_error_response(410, "unavailable", "Link not found")
    return await get_admin_link_detail_stats(db, link)


@router.patch("/links/{short_code}", response_model=AdminLinkItem)
async def admin_update_link(
    short_code: str,
    payload: AdminLinkUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    if link is None:
        return unified_error_response(410, "unavailable", "Link not found")

    if payload.reset_clicks:
        link.clicks_count = 0
        if link.max_clicks is None or link.max_clicks > 0:
            link.is_active = True
    if payload.clear_max_clicks:
        link.max_clicks = None
    elif payload.max_clicks is not None:
        link.max_clicks = payload.max_clicks
        if link.clicks_count >= link.max_clicks:
            link.is_active = False

    if payload.is_active is not None:
        link.is_active = payload.is_active
    if payload.scan_status is not None:
        link.scan_status = payload.scan_status
    if payload.expires_in_hours is not None:
        link.expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)

    await db.commit()
    await db.refresh(link)
    await _sync_link_cache(link)

    return AdminLinkItem(
        id=link.id,
        short_code=link.short_code,
        original_url=link.original_url,
        max_clicks=link.max_clicks,
        clicks_count=link.clicks_count,
        is_active=link.is_active,
        scan_status=link.scan_status,
        risk_score=link.risk_score,
        scan_report=link.scan_report,
        expires_at=link.expires_at,
        created_at=link.created_at,
    )


@router.post("/links/{short_code}/rescan", response_model=MaintenanceResponse)
async def admin_rescan_link(
    short_code: str,
    db: AsyncSession = Depends(get_db),
):
    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    if link is None:
        return unified_error_response(410, "unavailable", "Link not found")

    svc_settings = await get_service_settings(db)
    link.scan_status = "PENDING"
    await db.commit()
    await _sync_link_cache(link)
    await enqueue_link_scan(link.short_code, svc_settings.estimated_scan_seconds)

    return MaintenanceResponse(
        status="queued",
        affected_count=1,
        detail=f"Link {short_code} queued for CVE rescan",
    )


@router.delete("/links/{short_code}", response_model=MaintenanceResponse)
async def admin_delete_link(
    short_code: str,
    db: AsyncSession = Depends(get_db),
):
    link = await db.scalar(select(Link).where(Link.short_code == short_code))
    if link is None:
        return unified_error_response(410, "unavailable", "Link not found")

    await db.execute(delete(Link).where(Link.id == link.id))
    await db.commit()
    await redis_store.hset(f"link:{short_code}", {"scan_status": "DEAD"}, ttl=900)
    await redis_store.delete(f"cache:stats:{short_code}", f"scan:status:{short_code}", "cache:admin:overview")

    return MaintenanceResponse(
        status="deleted",
        affected_count=1,
        detail=f"Link {short_code} deleted",
    )


@router.get("/blocked-urls", response_model=BlockedUrlsListResponse)
async def admin_list_blocked_urls(
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(BlockedUrl).order_by(desc(BlockedUrl.blocked_at)))
    ).scalars().all()
    return BlockedUrlsListResponse(
        total=len(rows),
        items=[
            BlockedUrlItem(
                id=r.id,
                url_hash=r.url_hash,
                original_url=r.original_url,
                domain=r.domain,
                reason=r.reason,
                max_cvss=r.max_cvss,
                max_severity=r.max_severity,
                scan_report=r.scan_report,
                blocked_at=r.blocked_at,
            )
            for r in rows
        ],
    )


@router.delete("/blocked-urls/{blocked_id}", response_model=MaintenanceResponse)
async def admin_unblock_url(
    blocked_id: int,
    db: AsyncSession = Depends(get_db),
):
    row = await db.scalar(select(BlockedUrl).where(BlockedUrl.id == blocked_id))
    if row is None:
        return unified_error_response(404, "page_not_found", "Blocked URL record not found")

    url_hash = row.url_hash
    domain = row.domain
    await db.execute(delete(BlockedUrl).where(BlockedUrl.id == blocked_id))
    await db.commit()

    # Clear Redis blocklist and host cache so URL can be shortened again
    await redis_store.srem(BLOCKED_URLS_SET_KEY, url_hash)
    await redis_store.delete(f"scan:host:{domain}", f"scan:result:{url_hash}", "cache:admin:overview")

    return MaintenanceResponse(
        status="unblocked",
        affected_count=1,
        detail=f"Unblocked URL: {row.original_url}",
    )


@router.get("/settings", response_model=ServiceSettingsSchema)
async def admin_get_settings(db: AsyncSession = Depends(get_db)):
    return await get_service_settings(db)


@router.put("/settings", response_model=ServiceSettingsSchema)
async def admin_put_settings(
    payload: ServiceSettingsSchema,
    db: AsyncSession = Depends(get_db),
):
    return await update_service_settings(db, payload)


@router.post("/maintenance/cleanup", response_model=MaintenanceResponse)
async def admin_maintenance_cleanup(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    stale_links = (
        await db.execute(
            select(Link).where(
                or_(
                    Link.is_active.is_(False),
                    (Link.expires_at.is_not(None)) & (Link.expires_at <= now),
                    (Link.max_clicks.is_not(None)) & (Link.clicks_count >= Link.max_clicks),
                )
            )
        )
    ).scalars().all()

    count = len(stale_links)
    for item in stale_links:
        await redis_store.delete(f"link:{item.short_code}", f"cache:stats:{item.short_code}")
        await db.execute(delete(Link).where(Link.id == item.id))

    await db.commit()
    await redis_store.delete("cache:admin:overview")

    return MaintenanceResponse(
        status="cleaned",
        affected_count=count,
        detail=f"Removed {count} inactive or exhausted links",
    )


@router.post("/maintenance/flush-cache", response_model=MaintenanceResponse)
async def admin_flush_cache():
    removed = 0
    for prefix in ("link:", "scan:host:", "cache:"):
        removed += await redis_store.delete_by_prefix(prefix)
    return MaintenanceResponse(
        status="flushed",
        affected_count=removed,
        detail=f"Flushed {removed} Redis cache keys",
    )
