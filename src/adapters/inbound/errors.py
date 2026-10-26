"""
Uniform error envelope (ErrorBody) for every non-2xx API error: domain errors,
request validation, unknown routes and unexpected failures. No stack traces leak.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.adapters.inbound.schemas import ErrorBody
from src.composition import get_clock
from src.domain.exceptions import DomainError, InvalidTokenCountError, StorageUnavailableError

logger = logging.getLogger(__name__)

CORRELATION_HEADER = "X-Correlation-ID"
# Client-supplied ids are echoed and logged, so only safe tokens are accepted
_CORRELATION_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")

_DOMAIN_STATUS = {
    InvalidTokenCountError: status.HTTP_400_BAD_REQUEST,
    StorageUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}

_HTTP_CODES = {
    404: "ERR_NOT_FOUND",
    405: "ERR_METHOD_NOT_ALLOWED",
}


def _correlation_id(request: Request) -> str:
    supplied = request.headers.get(CORRELATION_HEADER, "")
    return supplied if _CORRELATION_ID_RE.fullmatch(supplied) else str(uuid.uuid4())


def _now(request: Request):
    # Same time source as the use cases (AD-5), honouring test overrides.
    provider = request.app.dependency_overrides.get(get_clock, get_clock)
    try:
        return provider().now()
    except Exception:
        # An error handler must never fail; fall back to the system UTC time
        return datetime.now(timezone.utc)


def error_response(
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    correlation_id = _correlation_id(request)
    body = ErrorBody(
        error_code=error_code,
        message=message,
        correlation_id=correlation_id,
        timestamp=_now(request),
        details=details,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={CORRELATION_HEADER: correlation_id, **(headers or {})},
    )


async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
    status_code = next(
        (code for kind, code in _DOMAIN_STATUS.items() if isinstance(exc, kind)),
        status.HTTP_400_BAD_REQUEST,
    )
    headers = {"Retry-After": "5"} if isinstance(exc, StorageUnavailableError) else None
    return error_response(request, status_code, exc.code, exc.message, headers=headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        request,
        422,  # literal: the starlette constant was renamed across versions
        "ERR_VALIDATION",
        "Request payload failed validation",
        details={"errors": jsonable_encoder(exc.errors())},
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return error_response(
        request,
        exc.status_code,
        _HTTP_CODES.get(exc.status_code, f"ERR_HTTP_{exc.status_code}"),
        str(exc.detail),
        headers=getattr(exc, "headers", None),
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    response = error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "ERR_INTERNAL",
        "Unexpected internal error",
    )
    logger.exception(
        "unhandled_error path=%s correlation_id=%s",
        request.url.path, response.headers[CORRELATION_HEADER],
    )
    return response


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
