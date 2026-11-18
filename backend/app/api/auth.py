from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response

from app.api.error_utils import unified_error_response
from app.core.config import settings
from app.core.security import (
    compute_ip_hash,
    create_admin_jwt,
    extract_client_ip,
    require_admin,
    verify_admin_credentials,
)
from app.db.redis import redis_store
from app.schemas.admin import AdminLoginRequest, AdminSessionResponse

router = APIRouter(prefix="/api/v1/admin", tags=["admin-auth"])


@router.post("/login", response_model=AdminSessionResponse)
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
):
    ip_hash = compute_ip_hash(extract_client_ip(request))
    lockout_key = f"admin:lockout:ban:{ip_hash}"
    fail_key = f"admin:lockout:cnt:{ip_hash}"

    # Check if IP is currently locked out
    if await redis_store.get_str(lockout_key):
        return unified_error_response(
            429,
            "rate_limit",
            "Too many failed login attempts. Please wait 15 minutes.",
            headers={"Retry-After": str(settings.admin_lockout_seconds)},
        )

    if not verify_admin_credentials(payload.username, payload.password):
        attempts = await redis_store.incr_with_window(
            fail_key,
            window_seconds=settings.admin_lockout_seconds,
        )
        # Lock out IP after 5 bad attempts
        if attempts >= settings.admin_lockout_attempts:
            await redis_store.set_str(lockout_key, "1", ttl=settings.admin_lockout_seconds)
            return unified_error_response(
                429,
                "rate_limit",
                "Too many failed attempts. Access locked for 15 minutes.",
                headers={"Retry-After": str(settings.admin_lockout_seconds)},
            )
        return unified_error_response(
            401,
            "invalid_credentials",
            "Invalid username or password",
        )

    # Clear failure counter on success
    await redis_store.delete(fail_key, lockout_key)
    token = create_admin_jwt(payload.username)

    # Set strict HttpOnly cookie for XSS/CSRF safety
    response.set_cookie(
        key=settings.admin_cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return AdminSessionResponse(authenticated=True, username=payload.username)


@router.post("/logout", response_model=AdminSessionResponse)
async def admin_logout(response: Response):
    response.delete_cookie(
        key=settings.admin_cookie_name,
        path="/",
        httponly=True,
        samesite="strict",
    )
    return AdminSessionResponse(authenticated=False, username="")


@router.get("/session", response_model=AdminSessionResponse)
async def admin_session(admin_user: Dict[str, Any] = Depends(require_admin)):
    return AdminSessionResponse(authenticated=True, username=str(admin_user.get("sub", "admin")))
