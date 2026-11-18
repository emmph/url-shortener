from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Optional[str]:
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database & Redis
    database_url: str = Field(default="sqlite+aiosqlite:///./url_shortener.db")
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")
    allow_memory_fallback: bool = Field(default=True)

    # Application
    app_name: str = Field(default="URL Shortener")
    base_url: str = Field(default="http://127.0.0.1:8000")
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    serve_frontend_dist: bool = Field(default=False)

    # Security & Admin Auth
    ip_hash_salt: str = Field(default="dev-salt-change-in-production")
    admin_username: str = Field(default="admin")
    admin_password: str = Field(default="admin123")
    admin_password_hash: str = Field(default="")
    jwt_secret_key: str = Field(default="dev-jwt-secret-key-minimum-32-characters")
    jwt_expire_minutes: int = Field(default=120)
    cookie_secure: bool = Field(default=False)
    admin_cookie_name: str = Field(default="admin_session")

    # Limits & Anti-Abuse
    max_custom_clicks: int = Field(default=250)
    max_url_length: int = Field(default=2048)
    short_code_length: int = Field(default=7)
    rate_limit_create_per_min: int = Field(default=30)
    bruteforce_404_threshold: int = Field(default=30)
    bruteforce_404_window_sec: int = Field(default=60)
    bruteforce_404_block_sec: int = Field(default=300)
    admin_lockout_attempts: int = Field(default=5)
    admin_lockout_seconds: int = Field(default=900)

    # CVE & Security Scanner
    scanner_timeout_seconds: float = Field(default=8.0)
    scanner_estimated_seconds: int = Field(default=15)
    scanner_max_bytes: int = Field(default=65536)
    scanner_max_redirects: int = Field(default=5)
    max_scan_queue_size: int = Field(default=5000)
    scanner_min_block_cvss: float = Field(default=4.0)
    scanner_concurrency: int = Field(default=10)
    osv_api_url: str = Field(default="https://api.osv.dev/v1/query")
    nvd_api_key: str = Field(default="")

    # Write-Behind Batching & Embedded Worker
    analytics_flush_interval: float = Field(default=3.0)
    analytics_batch_size: int = Field(default=500)
    run_embedded_worker: bool = Field(default=True)


settings = Settings()
