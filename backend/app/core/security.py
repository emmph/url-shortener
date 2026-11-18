from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, Request
from pwdlib import PasswordHash

from app.core.config import settings

# Recommended Argon2id password hasher
password_hasher = PasswordHash.recommended()


def extract_client_ip(request: Request) -> str:
    """Extract client IP respecting X-Forwarded-For behind Nginx/Ingress."""
    # Check proxy header first
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first

    x_real = request.headers.get("x-real-ip", "").strip()
    if x_real:
        return x_real

    # Fall back to direct socket address
    if request.client and request.client.host:
        return request.client.host
    return "0.0.0.0"


def compute_ip_hash(ip: str, now: Optional[datetime] = None) -> str:
    """Compute daily-rotating 32-char SHA-256 hash so no raw IP/PII is ever persisted."""
    dt = now or datetime.now(timezone.utc)
    # Rotate daily to keep unique counts without long-term tracking
    day_bucket = dt.strftime("%Y-%m-%d")
    payload = f"{ip}:{settings.ip_hash_salt}:{day_bucket}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def hash_admin_password(plain: str) -> str:
    return password_hasher.hash(plain)


def verify_admin_credentials(username: str, password: str) -> bool:
    """Verify admin username and password via Argon2id or constant-time digest."""
    # Constant-time username check
    user_ok = secrets.compare_digest(username, settings.admin_username)
    if not user_ok:
        return False

    # Prefer Argon2id hash when configured
    if settings.admin_password_hash:
        try:
            return password_hasher.verify(password, settings.admin_password_hash)
        except Exception:
            return False

    return secrets.compare_digest(password, settings.admin_password)


def create_admin_jwt(username: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload: Dict[str, Any] = {
        "sub": username,
        "role": "admin",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_admin_jwt(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired admin token") from exc

    if payload.get("role") != "admin" or not payload.get("sub"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return payload


def require_admin(request: Request) -> Dict[str, Any]:
    """Dependency validating JWT from HttpOnly cookie (or Bearer header fallback)."""
    # Grab token from HttpOnly cookie first
    token = request.cookies.get(settings.admin_cookie_name)
    if not token:
        # Also allow Bearer header for API tools
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(status_code=401, detail="Admin authentication required")

    return decode_admin_jwt(token)
