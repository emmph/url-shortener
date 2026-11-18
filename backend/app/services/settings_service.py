from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.redis import redis_store
from app.models.blocked_url import BlockedUrl
from app.models.service_settings import ServiceSettings
from app.schemas.admin import ServiceSettingsSchema

SETTINGS_CACHE_KEY = "service:settings"
BLOCKED_URLS_SET_KEY = "blocked:urls"


async def get_service_settings(db: AsyncSession) -> ServiceSettingsSchema:
    """Read dynamic service settings from Redis cache (5m TTL) or database."""
    cached = await redis_store.get_json(SETTINGS_CACHE_KEY)
    if isinstance(cached, dict):
        return ServiceSettingsSchema(**cached)

    row = await db.scalar(select(ServiceSettings).where(ServiceSettings.id == 1))
    if row is None:
        row = ServiceSettings(
            id=1,
            allow_public_creation=True,
            rate_limit_create_per_min=settings.rate_limit_create_per_min,
            default_max_clicks=None,
            blocked_domains=[],
            enable_security_scan=True,
            min_block_cvss=settings.scanner_min_block_cvss,
            estimated_scan_seconds=settings.scanner_estimated_seconds,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    schema = ServiceSettingsSchema(
        allow_public_creation=row.allow_public_creation,
        rate_limit_create_per_min=row.rate_limit_create_per_min,
        default_max_clicks=row.default_max_clicks,
        blocked_domains=list(row.blocked_domains or []),
        enable_security_scan=row.enable_security_scan,
        min_block_cvss=row.min_block_cvss,
        estimated_scan_seconds=row.estimated_scan_seconds,
    )
    await redis_store.set_json(SETTINGS_CACHE_KEY, schema.model_dump(), ttl=300)
    return schema


async def update_service_settings(
    db: AsyncSession,
    payload: ServiceSettingsSchema,
) -> ServiceSettingsSchema:
    row = await db.scalar(select(ServiceSettings).where(ServiceSettings.id == 1))
    normalized_domains = sorted({d.strip().lower().lstrip(".") for d in payload.blocked_domains if d.strip()})
    if row is None:
        row = ServiceSettings(id=1)
        db.add(row)

    row.allow_public_creation = payload.allow_public_creation
    row.rate_limit_create_per_min = payload.rate_limit_create_per_min
    row.default_max_clicks = payload.default_max_clicks
    row.blocked_domains = normalized_domains
    row.enable_security_scan = payload.enable_security_scan
    row.min_block_cvss = payload.min_block_cvss
    row.estimated_scan_seconds = payload.estimated_scan_seconds
    await db.commit()

    updated = ServiceSettingsSchema(
        allow_public_creation=row.allow_public_creation,
        rate_limit_create_per_min=row.rate_limit_create_per_min,
        default_max_clicks=row.default_max_clicks,
        blocked_domains=normalized_domains,
        enable_security_scan=row.enable_security_scan,
        min_block_cvss=row.min_block_cvss,
        estimated_scan_seconds=row.estimated_scan_seconds,
    )
    await redis_store.set_json(SETTINGS_CACHE_KEY, updated.model_dump(), ttl=300)
    return updated


def is_domain_in_blacklist(domain: str, blocked_domains: List[str]) -> bool:
    clean_domain = domain.strip().lower().rstrip(".")
    for blocked in blocked_domains:
        b = blocked.strip().lower().lstrip(".")
        if not b:
            continue
        if clean_domain == b or clean_domain.endswith(f".{b}"):
            return True
    return False


async def is_url_blocked(db: AsyncSession, url_hash: str) -> bool:
    """O(1) Redis Set check with PostgreSQL fallback for blocked URLs."""
    if await redis_store.sismember(BLOCKED_URLS_SET_KEY, url_hash):
        return True

    row = await db.scalar(select(BlockedUrl.id).where(BlockedUrl.url_hash == url_hash))
    if row is not None:
        await redis_store.sadd(BLOCKED_URLS_SET_KEY, url_hash)
        return True
    return False
