from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.redis import redis_store
from app.db.session import check_db_ready

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    db_ok = await check_db_ready()
    redis_ok = await redis_store.ping()
    if db_ok and redis_ok:
        return {"status": "ready", "database": "up", "redis": "up"}
    return JSONResponse(
        status_code=503,
        content={
            "status": "degraded",
            "database": "up" if db_ok else "down",
            "redis": "up" if redis_ok else "down",
        },
    )
