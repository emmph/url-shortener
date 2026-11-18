from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        CheckConstraint(
            "max_clicks IS NULL OR (max_clicks >= 1 AND max_clicks <= 250)",
            name="ck_links_max_clicks_range",
        ),
        Index(
            "idx_links_active_code",
            "short_code",
            postgresql_where=text("is_active = TRUE"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    short_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    max_clicks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    clicks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scan_report: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    scan_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scan_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    click_events = relationship(
        "ClickEvent",
        back_populates="link",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
