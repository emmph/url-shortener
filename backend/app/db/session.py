from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all ORM models."""


def _build_engine(url: str) -> AsyncEngine:
    is_sqlite = url.startswith("sqlite")
    kwargs = {
        "echo": False,
        "future": True,
    }
    if not is_sqlite:
        kwargs.update(
            {
                "pool_size": 10,
                "max_overflow": 10,
                "pool_pre_ping": True,
            }
        )
    else:
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = _build_engine(settings.database_url)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db_and_defaults() -> None:
    """Ensure tables and singleton ServiceSettings row exist (safe for trial & tests)."""
    from app.models import BlockedUrl, ClickEvent, Link, ServiceSettings  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(ServiceSettings).where(ServiceSettings.id == 1))
        if existing is None:
            session.add(
                ServiceSettings(
                    id=1,
                    allow_public_creation=True,
                    rate_limit_create_per_min=settings.rate_limit_create_per_min,
                    default_max_clicks=None,
                    blocked_domains=[],
                    enable_security_scan=True,
                    min_block_cvss=settings.scanner_min_block_cvss,
                    estimated_scan_seconds=settings.scanner_estimated_seconds,
                )
            )
            await session.commit()


async def check_db_ready() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
