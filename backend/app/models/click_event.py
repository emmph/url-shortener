from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ClickEvent(Base):
    """Compact click analytics row without raw user_agent or raw IP (no PII)."""

    __tablename__ = "click_events"
    __table_args__ = (
        Index("idx_click_events_link_time", "link_id", "clicked_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    link_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        ForeignKey("links.id", ondelete="CASCADE"),
        nullable=False,
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    ip_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    device_type: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    browser: Mapped[str] = mapped_column(String(32), nullable=False, default="Other")
    referer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    link = relationship("Link", back_populates="click_events")
