from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, auth, health, links, redirect
from app.api.error_utils import unified_error_response
from app.core.config import settings
from app.db.redis import redis_store
from app.db.session import init_db_and_defaults
from app.workers.analytics_flusher import run_analytics_flusher_loop
from app.workers.scan_worker import run_scan_worker_loop

FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Boot DB defaults and Redis connection
    await init_db_and_defaults()
    await redis_store.connect()

    stop_event = asyncio.Event()
    tasks = []
    # Run embedded scan + analytics workers in background
    if settings.run_embedded_worker:
        tasks.append(asyncio.create_task(run_analytics_flusher_loop(stop_event)))
        tasks.append(asyncio.create_task(run_scan_worker_loop(stop_event)))

    try:
        yield
    finally:
        # Stop workers cleanly and drain buffers
        stop_event.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await redis_store.close()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        settings.base_url.rstrip("/"),
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator(excluded_handlers=["/metrics", "/healthz", "/readyz"]).instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    msg = "Invalid URL format or request parameters"
    if errors:
        first = errors[0]
        loc = ".".join(str(x) for x in first.get("loc", []))
        if "max_clicks" in loc:
            msg = "Click limit must be between 1 and 250"
    return unified_error_response(422, "invalid_url", msg)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = exc.status_code
    reason_map = {
        401: "invalid_credentials",
        403: "unsafe_url",
        404: "page_not_found",
        410: "unavailable",
        413: "payload_too_large",
        422: "invalid_url",
        429: "rate_limit",
        503: "maintenance",
    }
    reason = reason_map.get(code, "server_error")
    return unified_error_response(code, reason, str(exc.detail))


# Static and API routes must register before /{short_code}
app.include_router(health.router)
app.include_router(links.router)
app.include_router(auth.router)
app.include_router(admin.router)


def _spa_index_response() -> Optional[FileResponse]:
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file, media_type="text/html")
    return None


if settings.serve_frontend_dist and FRONTEND_DIST_DIR.is_dir():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/favicon.ico", include_in_schema=False)
    async def serve_favicon():
        svg_path = FRONTEND_DIST_DIR / "favicon.svg"
        if svg_path.is_file():
            return FileResponse(svg_path, media_type="image/svg+xml")
        return unified_error_response(404, "page_not_found", "Favicon not found")

    @app.get("/", include_in_schema=False)
    @app.get("/scanning/{path:path}", include_in_schema=False)
    @app.get("/error/{path:path}", include_in_schema=False)
    @app.get("/error", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{path:path}", include_in_schema=False)
    @app.get("/stats/{path:path}", include_in_schema=False)
    async def serve_spa_routes(path: str = ""):
        resp = _spa_index_response()
        if resp is not None:
            return resp
        return unified_error_response(404, "page_not_found", "Page not found")


app.include_router(redirect.router)
