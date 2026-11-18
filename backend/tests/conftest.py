from __future__ import annotations

import os
from typing import AsyncGenerator

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configure isolated test environment before importing app modules
os.environ["ENVIRONMENT"] = "test"
os.environ["ALLOW_MEMORY_FALLBACK"] = "true"
os.environ["RUN_EMBEDDED_WORKER"] = "false"
os.environ["SERVE_FRONTEND_DIST"] = "false"

from app.core.config import settings
from app.db import session as db_session
from app.db.redis import redis_store
from app.main import app
from app.models import BlockedUrl, ClickEvent, Link, ServiceSettings  # noqa: F401


@pytest_asyncio.fixture()
async def test_client(tmp_path) -> AsyncGenerator[httpx.AsyncClient, None]:
    db_file = tmp_path / "test_url_shortener.db"
    test_url = f"sqlite+aiosqlite:///{db_file}"

    settings.environment = "test"
    settings.allow_memory_fallback = True
    settings.run_embedded_worker = False
    settings.database_url = test_url

    test_engine = create_async_engine(
        test_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    db_session.engine = test_engine
    db_session.AsyncSessionLocal = test_session_maker
    redis_store.reset_memory_for_tests()
    await db_session.init_db_and_defaults()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await test_engine.dispose()
