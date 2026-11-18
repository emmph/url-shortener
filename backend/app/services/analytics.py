from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import redis_store
from app.models.blocked_url import BlockedUrl
from app.models.click_event import ClickEvent
from app.models.link import Link
from app.schemas.admin import (
    AdminLinkDetailStatsResponse,
    AdminOverviewResponse,
    RecentClickItem,
    TopLinkItem,
)
from app.schemas.links import CountBucket, LinkStatsResponse, TimeseriesPoint

_APP_START_TIME = time.time()


async def _fetch_link_aggregates(
    db: AsyncSession,
    link: Link,
) -> Dict[str, Any]:
    # Count unique daily IP hashes
    unique_clicks = int(
        await db.scalar(
            select(func.count(func.distinct(ClickEvent.ip_hash))).where(ClickEvent.link_id == link.id)
        )
        or 0
    )

    ts_rows = (
        await db.execute(
            select(func.date(ClickEvent.clicked_at).label("day"), func.count(ClickEvent.id))
            .where(ClickEvent.link_id == link.id)
            .group_by(func.date(ClickEvent.clicked_at))
            .order_by(func.date(ClickEvent.clicked_at))
        )
    ).all()

    dev_rows = (
        await db.execute(
            select(ClickEvent.device_type, func.count(ClickEvent.id))
            .where(ClickEvent.link_id == link.id)
            .group_by(ClickEvent.device_type)
            .order_by(desc(func.count(ClickEvent.id)))
        )
    ).all()

    browser_rows = (
        await db.execute(
            select(ClickEvent.browser, func.count(ClickEvent.id))
            .where(ClickEvent.link_id == link.id)
            .group_by(ClickEvent.browser)
            .order_by(desc(func.count(ClickEvent.id)))
        )
    ).all()

    ref_rows = (
        await db.execute(
            select(func.coalesce(ClickEvent.referer, "Direct"), func.count(ClickEvent.id))
            .where(ClickEvent.link_id == link.id)
            .group_by(func.coalesce(ClickEvent.referer, "Direct"))
            .order_by(desc(func.count(ClickEvent.id)))
            .limit(10)
        )
    ).all()

    remaining_clicks = (
        max(0, link.max_clicks - link.clicks_count) if link.max_clicks is not None else None
    )

    return {
        "unique_clicks": unique_clicks,
        "remaining_clicks": remaining_clicks,
        "timeseries": [TimeseriesPoint(bucket=str(r[0]), clicks=int(r[1])) for r in ts_rows],
        "devices": [CountBucket(label=str(r[0]), count=int(r[1])) for r in dev_rows],
        "browsers": [CountBucket(label=str(r[0]), count=int(r[1])) for r in browser_rows],
        "referers": [CountBucket(label=str(r[0]), count=int(r[1])) for r in ref_rows],
    }


async def get_public_link_stats(db: AsyncSession, link: Link) -> LinkStatsResponse:
    cache_key = f"cache:stats:{link.short_code}"
    # Serve cached stats for 30s to protect DB
    cached = await redis_store.get_json(cache_key)
    if isinstance(cached, dict):
        return LinkStatsResponse(**cached)

    agg = await _fetch_link_aggregates(db, link)
    resp = LinkStatsResponse(
        short_code=link.short_code,
        original_url=link.original_url,
        clicks_count=link.clicks_count,
        unique_clicks=agg["unique_clicks"],
        max_clicks=link.max_clicks,
        remaining_clicks=agg["remaining_clicks"],
        is_active=link.is_active,
        scan_status=link.scan_status,
        risk_score=link.risk_score,
        scan_report=link.scan_report,
        created_at=link.created_at,
        expires_at=link.expires_at,
        timeseries=agg["timeseries"],
        devices=agg["devices"],
        browsers=agg["browsers"],
        referers=agg["referers"],
    )
    await redis_store.set_json(cache_key, resp.model_dump(mode="json"), ttl=30)
    return resp


async def get_admin_link_detail_stats(db: AsyncSession, link: Link) -> AdminLinkDetailStatsResponse:
    agg = await _fetch_link_aggregates(db, link)
    recent_rows = (
        await db.execute(
            select(ClickEvent)
            .where(ClickEvent.link_id == link.id)
            .order_by(desc(ClickEvent.clicked_at))
            .limit(25)
        )
    ).scalars().all()

    return AdminLinkDetailStatsResponse(
        short_code=link.short_code,
        original_url=link.original_url,
        clicks_count=link.clicks_count,
        unique_clicks=agg["unique_clicks"],
        max_clicks=link.max_clicks,
        remaining_clicks=agg["remaining_clicks"],
        is_active=link.is_active,
        scan_status=link.scan_status,
        risk_score=link.risk_score,
        scan_report=link.scan_report,
        created_at=link.created_at,
        expires_at=link.expires_at,
        timeseries=agg["timeseries"],
        devices=agg["devices"],
        browsers=agg["browsers"],
        referers=agg["referers"],
        recent_clicks=[
            RecentClickItem(
                clicked_at=c.clicked_at,
                device_type=c.device_type,
                browser=c.browser,
                referer=c.referer,
                ip_hash=c.ip_hash,
            )
            for c in recent_rows
        ],
    )


async def get_admin_overview(db: AsyncSession, use_cache: bool = True) -> AdminOverviewResponse:
    cache_key = "cache:admin:overview"
    if use_cache:
        cached = await redis_store.get_json(cache_key)
        if isinstance(cached, dict):
            return AdminOverviewResponse(**cached)

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    # Aggregate global service KPIs
    total_links = int(await db.scalar(select(func.count(Link.id))) or 0)
    active_links = int(await db.scalar(select(func.count(Link.id)).where(Link.is_active.is_(True))) or 0)
    limited_links = int(
        await db.scalar(select(func.count(Link.id)).where(Link.max_clicks.is_not(None))) or 0
    )
    one_time_links = int(
        await db.scalar(select(func.count(Link.id)).where(Link.max_clicks == 1)) or 0
    )
    exhausted_links = int(
        await db.scalar(
            select(func.count(Link.id)).where(
                Link.max_clicks.is_not(None),
                Link.clicks_count >= Link.max_clicks,
            )
        )
        or 0
    )
    pending_scan_links = int(
        await db.scalar(
            select(func.count(Link.id)).where(Link.scan_status.in_(["PENDING", "SCANNING"]))
        )
        or 0
    )
    blocked_urls_count = int(await db.scalar(select(func.count(BlockedUrl.id))) or 0)

    total_clicks = int(await db.scalar(select(func.coalesce(func.sum(Link.clicks_count), 0))) or 0)
    clicks_24h = int(
        await db.scalar(
            select(func.count(ClickEvent.id)).where(ClickEvent.clicked_at >= cutoff_24h)
        )
        or 0
    )
    clicks_7d = int(
        await db.scalar(
            select(func.count(ClickEvent.id)).where(ClickEvent.clicked_at >= cutoff_7d)
        )
        or 0
    )
    unique_visitors_total = int(
        await db.scalar(select(func.count(func.distinct(ClickEvent.ip_hash)))) or 0
    )

    ts_rows = (
        await db.execute(
            select(func.date(ClickEvent.clicked_at).label("day"), func.count(ClickEvent.id))
            .where(ClickEvent.clicked_at >= cutoff_7d)
            .group_by(func.date(ClickEvent.clicked_at))
            .order_by(func.date(ClickEvent.clicked_at))
        )
    ).all()

    top_rows = (
        await db.execute(select(Link).order_by(desc(Link.clicks_count), desc(Link.id)).limit(10))
    ).scalars().all()

    dev_rows = (
        await db.execute(
            select(ClickEvent.device_type, func.count(ClickEvent.id))
            .group_by(ClickEvent.device_type)
            .order_by(desc(func.count(ClickEvent.id)))
        )
    ).all()

    browser_rows = (
        await db.execute(
            select(ClickEvent.browser, func.count(ClickEvent.id))
            .group_by(ClickEvent.browser)
            .order_by(desc(func.count(ClickEvent.id)))
        )
    ).all()

    ref_rows = (
        await db.execute(
            select(func.coalesce(ClickEvent.referer, "Direct"), func.count(ClickEvent.id))
            .group_by(func.coalesce(ClickEvent.referer, "Direct"))
            .order_by(desc(func.count(ClickEvent.id)))
            .limit(10)
        )
    ).all()

    redis_stats = await redis_store.info_stats()
    scan_queue_len = await redis_store.llen("scan:queue")
    analytics_buf_len = await redis_store.llen("analytics:buffer")

    resp = AdminOverviewResponse(
        total_links=total_links,
        active_links=active_links,
        limited_links=limited_links,
        one_time_links=one_time_links,
        exhausted_links=exhausted_links,
        pending_scan_links=pending_scan_links,
        blocked_urls_count=blocked_urls_count,
        total_clicks=total_clicks,
        clicks_24h=clicks_24h,
        clicks_7d=clicks_7d,
        unique_visitors_total=unique_visitors_total,
        timeseries_7d=[TimeseriesPoint(bucket=str(r[0]), clicks=int(r[1])) for r in ts_rows],
        top_links=[
            TopLinkItem(
                short_code=item.short_code,
                original_url=item.original_url,
                clicks_count=item.clicks_count,
                max_clicks=item.max_clicks,
                is_active=item.is_active,
                scan_status=item.scan_status,
            )
            for item in top_rows
        ],
        devices=[CountBucket(label=str(r[0]), count=int(r[1])) for r in dev_rows],
        browsers=[CountBucket(label=str(r[0]), count=int(r[1])) for r in browser_rows],
        referers=[CountBucket(label=str(r[0]), count=int(r[1])) for r in ref_rows],
        infra={
            "uptime_seconds": int(time.time() - _APP_START_TIME),
            "redis": redis_stats,
            "scan_queue_depth": scan_queue_len,
            "analytics_buffer_depth": analytics_buf_len,
        },
    )
    await redis_store.set_json(cache_key, resp.model_dump(mode="json"), ttl=30)
    return resp
