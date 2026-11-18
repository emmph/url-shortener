from __future__ import annotations

from typing import List, Optional

from sqlalchemy import JSON, Boolean, Float, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ServiceSettings(Base):
    """Singleton dynamic service configuration editable via Admin Panel."""

    __tablename__ = "service_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    allow_public_creation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_create_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    default_max_clicks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    blocked_domains: Mapped[List[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    enable_security_scan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_block_cvss: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    estimated_scan_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
