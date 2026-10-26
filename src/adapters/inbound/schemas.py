from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Sanity bound per consumption event. Counters are BIGINT, so this is not an overflow
# guard; it rejects absurd payloads from a misbehaving gateway with 422.
MAX_TOKENS_PER_EVENT = 1_000_000

# Identifiers: 1-64 characters, no whitespace (so " sam" and "sam" are not two users)
ID_PATTERN = r"^\S+$"


class QuotaWarningDTO(BaseModel):
    warning: bool = Field(..., description="Whether the soft-warning threshold has been reached")
    threshold: str = Field(..., description="Active warning threshold, e.g. 80%")
    status: Optional[str] = Field(None, description="Warning status code, e.g. QUOTA_WARNING_80_PERCENT")
    remaining_tokens_before_denial: int = Field(..., description="Tokens left before hard denial at 100%")
    message: Optional[str] = Field(None, description="Human-readable warning message")


class TokenEventRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64, pattern=ID_PATTERN, examples=["sam"])
    subject_id: str = Field(..., min_length=1, max_length=64, pattern=ID_PATTERN, examples=["CS-480"])
    prompt_tokens: int = Field(..., ge=0, le=MAX_TOKENS_PER_EVENT, strict=True, examples=[500])
    completion_tokens: int = Field(..., ge=0, le=MAX_TOKENS_PER_EVENT, strict=True, examples=[250])


class TokenEventResponse(BaseModel):
    id: str = Field(..., description="Ledger entry UUID")
    user_id: str
    subject_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int = Field(..., description="prompt_tokens + completion_tokens")
    tokens_used: int = Field(..., description="Cumulative daily tokens used by the user")
    token_limit: int = Field(..., description="Daily quota ceiling")
    remaining_balance: int = Field(..., description="max(0, token_limit - tokens_used)")
    warning: QuotaWarningDTO
    timestamp: datetime


class CheckAllowanceRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64, pattern=ID_PATTERN, examples=["sam"])
    # No upper bound: any request above the remaining quota is an explained denial (AD-6)
    requested_tokens: int = Field(..., gt=0, strict=True, examples=[500])


class CheckAllowanceResponse(BaseModel):
    allowed: bool = Field(..., description="True if within quota; False if hard denied")
    reason: Optional[str] = Field(None, description="Human-readable denial reason")
    reason_code: Optional[str] = Field(None, description="Denial code, e.g. DAILY_QUOTA_EXCEEDED")
    requested_tokens: int
    remaining_balance: int
    tokens_used: int
    token_limit: int
    resets_at: datetime = Field(..., description="Next daily reset (00:00 UTC)")


class QuotaBalanceResponse(BaseModel):
    user_id: str
    date: str
    tokens_used: int
    token_limit: int
    remaining_balance: int
    percentage_used: float
    resets_at: datetime
    warning: QuotaWarningDTO


class HealthResponse(BaseModel):
    status: str = Field(..., description="ok | degraded")
    database: str = Field(..., description="healthy | unhealthy")
    cluster: Dict[str, Any]
    timestamp: datetime


class FleetResponse(BaseModel):
    cluster_summary: Dict[str, Any]
    nodes: List[Dict[str, Any]]


class RootResponse(BaseModel):
    service: str
    module: str
    version: str
    documentation: str
    health: str


class ErrorBody(BaseModel):
    """Single error envelope for every non-2xx API response (contract ErrorBody)."""
    error_code: str = Field(..., examples=["ERR_INVALID_TOKEN_COUNT"])
    message: str
    correlation_id: str
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None
