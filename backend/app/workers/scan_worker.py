from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.ssrf_guard import ResolverFn
from app.db import session as db_session
from app.db.redis import redis_store
from app.models.blocked_url import BlockedUrl
from app.models.link import Link
from app.services.scanner import ScanOutcome, scan_url_security
from app.services.settings_service import BLOCKED_URLS_SET_KEY, get_service_settings

logger = logging.getLogger(__name__)
SCAN_QUEUE_KEY = "scan:queue"


async def enqueue_link_scan(short_code: str, estimated_seconds: int) -> None:
    """Register initial Redis scan status and push short_code to background scan queue."""
    now_ts = int(time.time())
    # Track scan ETA directly in Redis so polling never hits DB
    await redis_store.hset(
        f"scan:status:{short_code}",
        {
            "status": "PENDING",
            "started_at": str(now_ts),
            "estimated_seconds": str(estimated_seconds),
            "stage": "Queued for security and CVE scan",
            "risk_score": "0",
        },
        ttl=900,
    )
    await redis_store.lpush(SCAN_QUEUE_KEY, short_code)


async def _apply_outcome_to_link(
    short_code: str,
    outcome: ScanOutcome,
) -> None:
    now = datetime.now(timezone.utc)
    async with db_session.AsyncSessionLocal() as session:
        link = await session.scalar(select(Link).where(Link.short_code == short_code))
        if link is None:
            return

        if outcome.is_safe:
            # Mark link safe and warm Redis cache for fast redirects
            link.scan_status = "SAFE"
            link.risk_score = outcome.risk_score
            link.scan_report = outcome.report
            link.scan_completed_at = now
            await session.commit()

            ttl: Optional[int] = None
            if link.expires_at is not None:
                ttl = max(60, int((link.expires_at - now).total_seconds()))
            await redis_store.hset(
                f"link:{short_code}",
                {
                    "url": link.original_url,
                    "remaining": str(max(0, link.max_clicks - link.clicks_count)) if link.max_clicks is not None else "-1",
                    "scan_status": "SAFE",
                    "link_id": str(link.id),
                    "expires_at": str(int(link.expires_at.timestamp())) if link.expires_at else "0",
                },
                ttl=ttl or 86400,
            )
            await redis_store.hset(
                f"scan:status:{short_code}",
                {
                    "status": "SAFE",
                    "stage": outcome.reason,
                    "risk_score": str(outcome.risk_score),
                    "target_url": link.original_url,
                },
                ttl=900,
            )
        else:
            # Scan failed (MEDIUM/HIGH/CRITICAL): delete link and block URL forever
            original_url = link.original_url
            url_hash = link.url_hash
            domain = (urlsplit(original_url).hostname or "unknown").lower()

            existing_block = await session.scalar(select(BlockedUrl).where(BlockedUrl.url_hash == url_hash))
            if existing_block is None:
                session.add(
                    BlockedUrl(
                        url_hash=url_hash,
                        original_url=original_url,
                        domain=domain,
                        reason=outcome.reason,
                        max_cvss=outcome.max_cvss,
                        max_severity=outcome.max_severity,
                        scan_report=outcome.report,
                        blocked_at=now,
                    )
                )

            await session.execute(delete(Link).where(Link.id == link.id))
            await session.commit()

            # Write dead tombstone + blocked hash set
            await redis_store.sadd(BLOCKED_URLS_SET_KEY, url_hash)
            await redis_store.hset(
                f"link:{short_code}",
                {"scan_status": "DEAD"},
                ttl=900,
            )
            await redis_store.hset(
                f"scan:status:{short_code}",
                {
                    "status": "REMOVED_UNSAFE",
                    "stage": outcome.reason,
                    "risk_score": str(outcome.risk_score),
                },
                ttl=900,
            )


async def process_scan_for_code(
    short_code: str,
    resolver: Optional[ResolverFn] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> Optional[ScanOutcome]:
    """Scan a single short_code with in-flight deduplication and DB/Redis synchronization."""
    async with db_session.AsyncSessionLocal() as session:
        link = await session.scalar(select(Link).where(Link.short_code == short_code))
        if link is None:
            return None
        svc_settings = await get_service_settings(session)
        min_block_cvss = svc_settings.min_block_cvss
        original_url = link.original_url
        url_hash = link.url_hash

        await session.execute(
            update(Link)
            .where(Link.id == link.id)
            .values(scan_status="SCANNING", scan_started_at=datetime.now(timezone.utc))
        )
        await session.commit()

    await redis_store.hset(
        f"scan:status:{short_code}",
        {
            "status": "SCANNING",
            "stage": "Checking TLS, security headers, and CVEs",
        },
        ttl=900,
    )
    await redis_store.hset(f"link:{short_code}", {"scan_status": "SCANNING"})

    # Deduplicate concurrent scans of the exact same URL
    inflight_key = f"scan:inflight:{url_hash}"
    acquired = await redis_store.set_str(inflight_key, short_code, ttl=120, nx=True)

    outcome: Optional[ScanOutcome] = None
    if acquired:
        try:
            outcome = await scan_url_security(
                original_url,
                min_block_cvss=min_block_cvss,
                resolver=resolver,
                transport=transport,
            )
            await redis_store.set_json(
                f"scan:result:{url_hash}",
                {
                    "is_safe": outcome.is_safe,
                    "risk_score": outcome.risk_score,
                    "max_cvss": outcome.max_cvss,
                    "max_severity": outcome.max_severity,
                    "reason": outcome.reason,
                    "report": outcome.report,
                },
                ttl=60,
            )
        finally:
            await redis_store.delete(inflight_key)
    else:
        # Wait for the active scan on this URL to finish
        for _ in range(30):
            cached_res = await redis_store.get_json(f"scan:result:{url_hash}")
            if isinstance(cached_res, dict):
                outcome = ScanOutcome(
                    is_safe=bool(cached_res["is_safe"]),
                    risk_score=int(cached_res["risk_score"]),
                    max_cvss=float(cached_res["max_cvss"]),
                    max_severity=str(cached_res["max_severity"]),
                    reason=str(cached_res["reason"]),
                    report=dict(cached_res.get("report") or {}),
                )
                break
            await asyncio.sleep(0.2)

        if outcome is None:
            outcome = await scan_url_security(
                original_url,
                min_block_cvss=min_block_cvss,
                resolver=resolver,
                transport=transport,
            )

    await _apply_outcome_to_link(short_code, outcome)
    return outcome


async def run_scan_worker_loop(stop_event: asyncio.Event) -> None:
    """Embedded async pool consuming scan:queue with bounded concurrency."""
    sem = asyncio.Semaphore(settings.scanner_concurrency)
    active_tasks = set()

    async def _worker_task(code: str) -> None:
        async with sem:
            try:
                await process_scan_for_code(code)
            except Exception as exc:
                logger.warning("scan_worker failed for %s: %s", code, exc)

    while not stop_event.is_set():
        try:
            batch = await redis_store.lpop_batch(SCAN_QUEUE_KEY, 5)
            for code in batch:
                task = asyncio.create_task(_worker_task(code))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)
        except Exception as exc:
            logger.warning("scan_worker poll error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.25)
        except asyncio.TimeoutError:
            pass

    if active_tasks:
        await asyncio.gather(*active_tasks, return_exceptions=True)
