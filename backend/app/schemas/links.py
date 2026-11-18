from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class LinkCreateRequest(BaseModel):
    original_url: str = Field(..., min_length=1)
    max_clicks: Optional[int] = Field(default=None, ge=1, le=250)
    custom_alias: Optional[str] = Field(default=None, min_length=4, max_length=16)
    expires_in_hours: Optional[int] = Field(default=None, ge=1, le=8760)

    @field_validator("custom_alias")
    @classmethod
    def validate_alias(cls, val: Optional[str]) -> Optional[str]:
        if val is None or val == "":
            return None
        if not val.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Alias can only contain letters, digits, '-' and '_'")
        return val


class LinkCreateResponse(BaseModel):
    short_code: str
    short_url: str
    original_url: str
    max_clicks: Optional[int]
    scan_status: str
    estimated_wait_seconds: int
    expires_at: Optional[datetime]
    created_at: datetime


class ScanStatusResponse(BaseModel):
    short_code: str
    scan_status: str
    risk_score: int = 0
    estimated_remaining_seconds: int = 0
    estimated_remaining_minutes_text: str = "less than a minute"
    stage: str = "queued"
    target_url: Optional[str] = None
    error_url: Optional[str] = None


class CountBucket(BaseModel):
    label: str
    count: int


class TimeseriesPoint(BaseModel):
    bucket: str
    clicks: int


class LinkStatsResponse(BaseModel):
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
