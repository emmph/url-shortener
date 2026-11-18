from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.links import CountBucket, TimeseriesPoint


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class AdminSessionResponse(BaseModel):
    authenticated: bool
    username: str


class TopLinkItem(BaseModel):
    short_code: str
    original_url: str
    clicks_count: int
    max_clicks: Optional[int]
    is_active: bool
    scan_status: str


class AdminOverviewResponse(BaseModel):
    total_links: int
    active_links: int
    limited_links: int
    one_time_links: int
    exhausted_links: int
    pending_scan_links: int
    blocked_urls_count: int
    total_clicks: int
    clicks_24h: int
    clicks_7d: int
    unique_visitors_total: int
    timeseries_7d: List[TimeseriesPoint]
    top_links: List[TopLinkItem]
    devices: List[CountBucket]
    browsers: List[CountBucket]
    referers: List[CountBucket]
    infra: Dict[str, Any]


class AdminLinkItem(BaseModel):
    id: int
    short_code: str
    original_url: str
    max_clicks: Optional[int]
    clicks_count: int
    is_active: bool
    scan_status: str
    risk_score: int
    scan_report: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime]
    created_at: datetime


class AdminLinksListResponse(BaseModel):
    total: int
    page: int
    limit: int
    items: List[AdminLinkItem]


class AdminLinkUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    max_clicks: Optional[int] = Field(default=None, ge=1, le=250)
    clear_max_clicks: bool = False
    reset_clicks: bool = False
    scan_status: Optional[str] = Field(default=None, pattern="^(PENDING|SCANNING|SAFE)$")
    expires_in_hours: Optional[int] = Field(default=None, ge=1, le=8760)


class RecentClickItem(BaseModel):
    clicked_at: datetime
    device_type: str
    browser: str
    referer: Optional[str]
    ip_hash: str


class AdminLinkDetailStatsResponse(BaseModel):
    short_code: str
    original_url: str
    clicks_count: int
    unique_clicks: int
    max_clicks: Optional[int]
    remaining_clicks: Optional[int]
    is_active: bool
    scan_status: str
    risk_score: int
    scan_report: Optional[Dict[str, Any]] = None
    created_at: datetime
    expires_at: Optional[datetime]
    timeseries: List[TimeseriesPoint]
    devices: List[CountBucket]
    browsers: List[CountBucket]
    referers: List[CountBucket]
    recent_clicks: List[RecentClickItem]


class BlockedUrlItem(BaseModel):
    id: int
    url_hash: str
    original_url: str
    domain: str
    reason: str
    max_cvss: Optional[float]
    max_severity: str
    scan_report: Optional[Dict[str, Any]] = None
    blocked_at: datetime


class BlockedUrlsListResponse(BaseModel):
    total: int
    items: List[BlockedUrlItem]


class ServiceSettingsSchema(BaseModel):
    allow_public_creation: bool = True
    rate_limit_create_per_min: int = Field(default=30, ge=1, le=10000)
    default_max_clicks: Optional[int] = Field(default=None, ge=1, le=250)
    blocked_domains: List[str] = Field(default_factory=list)
    enable_security_scan: bool = True
    min_block_cvss: float = Field(default=4.0, ge=0.0, le=10.0)
    estimated_scan_seconds: int = Field(default=15, ge=5, le=600)


class MaintenanceResponse(BaseModel):
    status: str
    affected_count: int
    detail: str
