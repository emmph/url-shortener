from __future__ import annotations

from typing import Dict, Optional
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse


def build_error_url(code: int, reason: str) -> str:
    query = urlencode({"reason": reason})
    return f"/error/{code}?{query}"


def is_browser_navigation(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    return "text/html" in accept


def unified_error_response(
    status_code: int,
    reason: str,
    detail: str,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": status_code,
            "reason": reason,
            "detail": detail,
            "error_url": build_error_url(status_code, reason),
        },
        headers=headers,
    )


def browser_or_json_error(
    request: Request,
    status_code: int,
    reason: str,
    detail: str,
    headers: Optional[Dict[str, str]] = None,
):
    if is_browser_navigation(request):
        return RedirectResponse(
            url=build_error_url(status_code, reason),
            status_code=307,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                **(headers or {}),
            },
        )
    return unified_error_response(status_code, reason, detail, headers=headers)
