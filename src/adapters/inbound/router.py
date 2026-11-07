"""
Inbound HTTP adapter. Thin by design: translate DTOs <-> use-case commands/results and
set quota headers. No persistence or business rules live here.
"""
from pathlib import Path as FilePath

from fastapi import APIRouter, Depends, Path, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.adapters.inbound.schemas import (
    ID_PATTERN,
    CheckAllowanceRequest,
    CheckAllowanceResponse,
    ErrorBody,
    FleetResponse,
    HealthResponse,
    MidnightResetResponse,
    QuotaBalanceResponse,
    QuotaWarningDTO,
    ReserveRejectedResponse,
    ReserveRequest,
    ReserveResponse,
    SeedBucketsRequest,
    TokenEventRequest,
    TokenEventResponse,
)
from src.application.use_cases import (
    CheckAllowance,
    GetQuotaBalance,
    IngestTokenEvent,
    MidnightResetJob,
    ReserveTokens,
    TokenEventCommand,
)
from src.composition import (
    get_check_allowance,
    get_clock,
    get_fleet_provider,
    get_ingest_token_event,
    get_midnight_reset,
    get_quota_balance,
    get_repository,
    get_reserve_tokens,
)
from src.config import settings
from src.domain.exceptions import QuotaExceededError
from src.domain.models import QuotaWarningInfo, period_key
from src.ports.clock import IClock
from src.ports.fleet import IFleetProvider
from src.ports.repository import IQuotaRepository

# Jinja2 templates for the Story 8.6 student web view
_TEMPLATES_DIR = FilePath(__file__).resolve().parents[3] / "src" / "frontend" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter(prefix=settings.API_V1_PREFIX, tags=["Token Quota Service"])
# Web router for student-facing pages (no /api/v1 prefix)
web_router = APIRouter(tags=["Student Web"])

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
    response: Response,
    user_id: str = Path(..., min_length=1, max_length=64, pattern=ID_PATTERN),
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


# ---------------------------------------------------------------------------
# Story 8.4 — Atomic Quota Reservation (AD-19: zero overdrafts)
# ---------------------------------------------------------------------------

@router.post(
    "/quota/reserve",
    response_model=ReserveResponse,
    status_code=status.HTTP_200_OK,
    summary="Atomically reserve tokens from the daily bucket (Story 8.4)",
    include_in_schema=False,
    responses={
        429: {
            "model": ReserveRejectedResponse,
            "description": "Quota Exceeded: insufficient balance for this reservation",
        },
        **ERRORS_422,
        **ERRORS_503,
    },
)
def reserve_quota_tokens(
    payload: ReserveRequest,
    use_case: ReserveTokens = Depends(get_reserve_tokens),
):
    """
    Story 8.4 / AD-19: atomically reserve tokens using a database-level conditional UPDATE.

    Two simultaneous requests against a near-empty bucket result in exactly one approval
    (HTTP 200) and one rejection (HTTP 429) — zero overdrafts guaranteed.
    """
    try:
        result = use_case.execute(payload.user_id, payload.requested_tokens)
        quota = result.quota
        return ReserveResponse(
            user_id=quota.user_id,
            reserved_tokens=result.reserved_tokens,
            remaining_tokens=quota.remaining_balance,
            tokens_used=quota.tokens_used,
            token_limit=quota.token_limit,
            date=quota.date,
        )
    except QuotaExceededError as exc:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=ReserveRejectedResponse(
                remaining_tokens=exc.remaining_tokens,
                requested_tokens=exc.requested_tokens,
            ).model_dump(),
            headers={"Retry-After": "3600"},  # suggest retry after quota resets
        )


# ---------------------------------------------------------------------------
# Story 8.5 — Midnight Reset Daemon (high-throughput bulk reset)
# ---------------------------------------------------------------------------

@router.post(
    "/quota/cron/midnight-reset",
    response_model=MidnightResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger midnight quota reset for all active daily buckets (Story 8.5)",
    include_in_schema=False,
    responses={**ERRORS_503},
)
def trigger_midnight_reset(
    use_case: MidnightResetJob = Depends(get_midnight_reset),
):
    """
    Story 8.5: bulk reset tokens_used to 0 for every quota bucket in today's period.

    Executed in chunks to avoid table-level lock contention so concurrent read queries
    remain unblocked during the reset sweep.
    """
    result = use_case.execute()
    return MidnightResetResponse(
        buckets_reset=result.buckets_reset,
        period=result.period,
        message=(
            f"Midnight reset complete: {result.buckets_reset} quota buckets "
            f"reset to 0 for period {result.period}."
        ),
    )


@router.post(
    "/quota/cron/seed-test-buckets",
    status_code=status.HTTP_201_CREATED,
    summary="[DEV/TEST] Seed N quota buckets with high usage for NFR benchmark (Story 8.5)",
    include_in_schema=False,
    tags=["Dev Tools"],
)
def seed_test_buckets(
    payload: SeedBucketsRequest,
    repository: IQuotaRepository = Depends(get_repository),
    clock: IClock = Depends(get_clock),
):
    """
    Story 8.5 NFR helper: populates `count` user quota rows with usage_percent consumption
    so the k6 benchmark has realistic data to reset against.
    Only intended for dev/test environments.
    """
    from src.adapters.outbound.db import UserQuotaDB
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    session = repository.session  # type: ignore[attr-defined]
    today = period_key(clock.now())
    tokens_used = int(payload.token_limit * payload.usage_percent)

    seeded = 0
    for i in range(payload.count):
        user_id = f"bench_user_{i:04d}"
        try:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                ins = pg_insert(UserQuotaDB.__table__)
            else:
                ins = sqlite_insert(UserQuotaDB.__table__)

            session.execute(
                ins.values(
                    user_id=user_id,
                    date=today,
                    tokens_used=tokens_used,
                    token_limit=payload.token_limit,
                ).on_conflict_do_nothing(index_elements=["user_id", "date"])
            )
            seeded += 1
        except Exception:
            session.rollback()
            raise
    session.commit()
    return {"seeded": seeded, "period": today, "tokens_used": tokens_used}


# ---------------------------------------------------------------------------
# Fleet & Health endpoints
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Story 8.6 — Student Web View: Real-Time Token Usage Dashboard
# ---------------------------------------------------------------------------

@web_router.get(
    "/student/quota",
    summary="Real-time token usage dashboard with quota breach banner (Story 8.6)",
    tags=["Student Web"],
    include_in_schema=False,
)
def student_quota_dashboard(
    request: Request,
    user_id: str = "sam",
    use_case: GetQuotaBalance = Depends(get_quota_balance),
):
    """
    Story 8.6 / Flow E: Renders the Token Usage Dashboard HTML page.

    Server-side renders the initial state; a client-side polling script then
    refreshes every 5 s by calling GET /api/v1/tokens/balance/{user_id}.

    Colour states:
      - Green  → usage < 80%
      - Amber  → 80% <= usage < 100%
      - Red    → usage >= 100% (breach banner visible)
    """
    result = use_case.execute(user_id)
    quota = result.quota
    pct = quota.percentage_used

    if pct >= 100:
        meter_state = "red"
    elif pct >= 80:
        meter_state = "amber"
    else:
        meter_state = "green"

    return templates.TemplateResponse(
        request=request,
        name="quota_dashboard.html",
        context={
            "user_id": quota.user_id,
            "date": quota.date,
            "tokens_used": quota.tokens_used,
            "token_limit": quota.token_limit,
            "remaining_balance": quota.remaining_balance,
            "percentage_used": pct,
            "meter_state": meter_state,
            "resets_at": result.resets_at.isoformat().replace("+00:00", "Z"),
        },
    )

