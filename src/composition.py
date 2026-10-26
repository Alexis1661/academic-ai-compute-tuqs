"""
Composition root: the only module that wires concrete adapters to ports.
FastAPI dependencies are declared here so tests can override any of them
(e.g. get_clock -> FakeClock) via app.dependency_overrides.
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from src.adapters.outbound.db import get_db
from src.adapters.outbound.fleet_adapter import JsonFleetAdapter
from src.adapters.outbound.sql_repository import SQLQuotaRepository
from src.adapters.outbound.system_clock import SystemClock
from src.application.use_cases import CheckAllowance, GetQuotaBalance, IngestTokenEvent
from src.config import settings
from src.domain.services import QuotaDomainService
from src.ports.clock import IClock
from src.ports.fleet import IFleetProvider
from src.ports.repository import IQuotaRepository

_system_clock = SystemClock()
_domain_service = QuotaDomainService(warning_threshold=settings.SOFT_WARNING_THRESHOLD)
_fleet_provider = JsonFleetAdapter()


def get_clock() -> IClock:
    return _system_clock


def get_domain_service() -> QuotaDomainService:
    return _domain_service


def get_fleet_provider() -> IFleetProvider:
    return _fleet_provider


def get_repository(db: Session = Depends(get_db)) -> IQuotaRepository:
    return SQLQuotaRepository(db)


def get_ingest_token_event(
    repository: IQuotaRepository = Depends(get_repository),
    clock: IClock = Depends(get_clock),
    domain: QuotaDomainService = Depends(get_domain_service),
) -> IngestTokenEvent:
    return IngestTokenEvent(repository, clock, domain, settings.DEFAULT_DAILY_TOKEN_LIMIT)


def get_quota_balance(
    repository: IQuotaRepository = Depends(get_repository),
    clock: IClock = Depends(get_clock),
    domain: QuotaDomainService = Depends(get_domain_service),
) -> GetQuotaBalance:
    return GetQuotaBalance(repository, clock, domain, settings.DEFAULT_DAILY_TOKEN_LIMIT)


def get_check_allowance(
    repository: IQuotaRepository = Depends(get_repository),
    clock: IClock = Depends(get_clock),
    domain: QuotaDomainService = Depends(get_domain_service),
) -> CheckAllowance:
    return CheckAllowance(repository, clock, domain, settings.DEFAULT_DAILY_TOKEN_LIMIT)
