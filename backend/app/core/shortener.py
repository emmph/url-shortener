from __future__ import annotations

import secrets
import string

BASE62_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase
RESERVED_CODES = frozenset(
    {
        "api",
        "admin",
        "scanning",
        "error",
        "stats",
        "healthz",
        "readyz",
        "metrics",
        "assets",
        "docs",
        "redoc",
        "openapi",
        "favicon",
        "robots",
    }
)


def generate_short_code(length: int = 7) -> str:
    """Generate a cryptographically random Base62 short code."""
    while True:
        code = "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))
        if code.lower() not in RESERVED_CODES:
            return code
