"""
Inbound HTTP adapter. Thin by design: translate DTOs <-> use-case commands/results and
set quota headers. No persistence or business rules live here.
"""
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from src.adapters.inbound.schemas import (
    CheckAllowanceRequest,
    CheckAllowanceResponse,
    ErrorBody,
    FleetResponse,
    HealthResponse,
    QuotaBalanceResponse,
    QuotaWarningDTO,
    TokenEventRequest,
    TokenEventResponse,
)
from src.application.use_cases import (
    CheckAllowance,
    GetQuotaBalance,
    IngestTokenEvent,
    TokenEventCommand,
)
from src.composition import (
    get_check_allowance,
    get_clock,
    get_fleet_provider,
    get_ingest_token_event,
    get_quota_balance,
    get_repository,
)
from src.config import settings
from src.domain.models import QuotaWarningInfo
from src.ports.clock import IClock
from src.ports.fleet import IFleetProvider
from src.ports.repository import IQuotaRepository

router = APIRouter(prefix=settings.API_V1_PREFIX, tags=["Token Quota Service"])

ERRORS_422 = {422: {"model": ErrorBody, "description": "Request payload failed validation"}}
ERRORS_503 = {503: {"model": ErrorBody, "description": "Quota store unavailable (fail closed)"}}


def _warning_dto(info: QuotaWarningInfo) -> QuotaWarningDTO:
    return QuotaWarningDTO(
        warning=info.warning,
        threshold=info.threshold,
        status=info.status,
        remaining_tokens_before_denial=info.remaining_tokens_before_denial,
        message=info.message,
    )


def _set_quota_headers(response: Response, info: QuotaWarningInfo, resets_at) -> None:
    """PRD FR-11: X-Quota-Warning: 80 on every response while usage >= 80%."""
    response.headers["X-Quota-Remaining"] = str(info.remaining_tokens_before_denial)
    response.headers["X-Quota-Reset"] = resets_at.isoformat().replace("+00:00", "Z")
    if info.warning:
        response.headers["X-Quota-Warning"] = str(info.threshold_percent)


@router.post(
    "/tokens/events",
    response_model=TokenEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest token consumption event (Story 8.1 & Story 8.2)",
    responses={
        400: {"model": ErrorBody, "description": "Invalid token counts (total must be > 0)"},
        **ERRORS_422,
        **ERRORS_503,
    },
)
def ingest_token_event(
    payload: TokenEventRequest,
    response: Response,
    use_case: IngestTokenEvent = Depends(get_ingest_token_event),
):
    """Story 8.1: atomic ledger append + daily counter increment. Story 8.2: warning flags."""
    result = use_case.execute(
        TokenEventCommand(
            user_id=payload.user_id,
            subject_id=payload.subject_id,
            prompt_tokens=payload.prompt_tokens,
            completion_tokens=payload.completion_tokens,
        )
    )
    _set_quota_headers(response, result.warning, result.resets_at)
    entry, quota = result.entry, result.quota
    return TokenEventResponse(
        id=entry.id,
        user_id=entry.user_id,
        subject_id=entry.subject_id,
        prompt_tokens=entry.prompt_tokens,
        completion_tokens=entry.completion_tokens,
        total_tokens=entry.total_tokens,
        tokens_used=quota.tokens_used,
        token_limit=quota.token_limit,
        remaining_balance=quota.remaining_balance,
        warning=_warning_dto(result.warning),
        timestamp=entry.timestamp,
    )


@router.post(
    "/tokens/check-allowance",
    response_model=CheckAllowanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Check token allowance and enforce 100% hard denial (Story 8.3)",
    responses={**ERRORS_422, **ERRORS_503},
)
def check_token_allowance(
    payload: CheckAllowanceRequest,
    response: Response,
    use_case: CheckAllowance = Depends(get_check_allowance),
):
    """Story 8.3: allowed only if (tokens_used + requested_tokens) <= token_limit."""
    result = use_case.execute(payload.user_id, payload.requested_tokens)
    decision = result.decision
    _set_quota_headers(response, result.warning, decision.resets_at)
    return CheckAllowanceResponse(
        allowed=decision.allowed,
        reason=decision.reason,
        reason_code=decision.reason_code,
        requested_tokens=decision.requested_tokens,
        remaining_balance=decision.remaining_balance,
        tokens_used=decision.current_used,
        token_limit=decision.token_limit,
        resets_at=decision.resets_at,
    )


@router.get(
    "/tokens/balance/{user_id}",
    response_model=QuotaBalanceResponse,
    summary="Query current quota balance and warning threshold (Story 8.2)",
    responses={**ERRORS_422, **ERRORS_503},
)
def get_user_quota_balance(
    user_id: str,
    response: Response,
    use_case: GetQuotaBalance = Depends(get_quota_balance),
):
    """Story 8.2: returns QUOTA_WARNING_80_PERCENT and X-Quota-Warning while usage >= 80%."""
    result = use_case.execute(user_id)
    quota = result.quota
    _set_quota_headers(response, result.warning, result.resets_at)
    return QuotaBalanceResponse(
        user_id=quota.user_id,
        date=quota.date,
        tokens_used=quota.tokens_used,
        token_limit=quota.token_limit,
        remaining_balance=quota.remaining_balance,
        percentage_used=quota.percentage_used,
        resets_at=result.resets_at,
        warning=_warning_dto(result.warning),
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Subsystem health and fleet topology probe",
    responses={503: {"model": HealthResponse, "description": "Database unreachable"}},
)
def health_check(
    repository: IQuotaRepository = Depends(get_repository),
    fleet: IFleetProvider = Depends(get_fleet_provider),
    clock: IClock = Depends(get_clock),
):
    """Database connectivity plus simulated 32-node cluster summary. 503 when degraded."""
    db_ok = repository.ping()
    body = HealthResponse(
        status="ok" if db_ok else "degraded",
        database="healthy" if db_ok else "unhealthy",
        cluster=fleet.get_cluster_summary(),
        timestamp=clock.now(),
    )
    if db_ok:
        return body
    return JSONResponse(status_code=503, content=body.model_dump(mode="json"))


@router.get(
    "/fleet",
    response_model=FleetResponse,
    summary="Retrieve full simulated 32-node compute cluster inventory",
)
def get_fleet_inventory(fleet: IFleetProvider = Depends(get_fleet_provider)):
    """Cluster inventory: 31 workstations x 24 GB + 1 server x 2 x 48 GB."""
    return FleetResponse(cluster_summary=fleet.get_cluster_summary(), nodes=fleet.get_all_nodes())
