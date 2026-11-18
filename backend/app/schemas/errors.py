from __future__ import annotations

from pydantic import BaseModel


class UnifiedErrorResponse(BaseModel):
    error_code: int
    reason: str
    detail: str
    error_url: str
