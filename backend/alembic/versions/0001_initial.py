"""Initial schema: links, click_events, blocked_urls, service_settings.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "links",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("short_code", sa.String(length=16), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("max_clicks", sa.Integer(), nullable=True),
        sa.Column("clicks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("scan_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scan_report", _json_type(), nullable=True),
        sa.Column("scan_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "max_clicks IS NULL OR (max_clicks >= 1 AND max_clicks <= 250)",
            name="ck_links_max_clicks_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("short_code"),
    )
    op.create_index("ix_links_short_code", "links", ["short_code"], unique=False)
    op.create_index("ix_links_url_hash", "links", ["url_hash"], unique=False)
    op.create_index(
        "idx_links_active_code",
        "links",
        ["short_code"],
        unique=False,
        postgresql_where=sa.text("is_active = TRUE"),
        sqlite_where=sa.text("is_active = 1"),
    )

    op.create_table(
        "click_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("link_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ip_hash", sa.String(length=32), nullable=False),
        sa.Column("device_type", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("browser", sa.String(length=32), nullable=False, server_default="Other"),
        sa.Column("referer", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["link_id"], ["links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_click_events_clicked_at", "click_events", ["clicked_at"], unique=False)
    op.create_index("idx_click_events_link_time", "click_events", ["link_id", "clicked_at"], unique=False)

    op.create_table(
        "blocked_urls",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("max_cvss", sa.Float(), nullable=True),
        sa.Column("max_severity", sa.String(length=20), nullable=False),
        sa.Column("scan_report", _json_type(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash"),
    )
    op.create_index("ix_blocked_urls_url_hash", "blocked_urls", ["url_hash"], unique=False)
    op.create_index("ix_blocked_urls_domain", "blocked_urls", ["domain"], unique=False)

    op.create_table(
        "service_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("allow_public_creation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rate_limit_create_per_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("default_max_clicks", sa.Integer(), nullable=True),
        sa.Column("blocked_domains", _json_type(), nullable=False),
        sa.Column("enable_security_scan", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("min_block_cvss", sa.Float(), nullable=False, server_default="4.0"),
        sa.Column("estimated_scan_seconds", sa.Integer(), nullable=False, server_default="15"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("service_settings")
    op.drop_index("ix_blocked_urls_domain", table_name="blocked_urls")
    op.drop_index("ix_blocked_urls_url_hash", table_name="blocked_urls")
    op.drop_table("blocked_urls")
    op.drop_index("idx_click_events_link_time", table_name="click_events")
    op.drop_index("ix_click_events_clicked_at", table_name="click_events")
    op.drop_table("click_events")
    op.drop_index("idx_links_active_code", table_name="links")
    op.drop_index("ix_links_url_hash", table_name="links")
    op.drop_index("ix_links_short_code", table_name="links")
    op.drop_table("links")
