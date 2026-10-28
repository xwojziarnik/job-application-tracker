import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class DomainError(Exception):
    """Base class for errors raised by the service layer."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "domain_error"
    default_message: str = "Request could not be processed"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class ConflictError(DomainError):
    status_code: int = status.HTTP_409_CONFLICT
    code: str = "conflict"
    default_message: str = "Request conflicts with the current state of the resource"


class ServiceUnavailableError(DomainError):
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE
    code: str = "service_unavailable"
    default_message: str = "Service unavailable"


class DatabaseUnavailableError(ServiceUnavailableError):
    code: str = "database_unavailable"
    default_message: str = "Database unavailable"


class CompanyInactiveError(ConflictError):
    code: str = "company_inactive"


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    default_message = "Resource not found"


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    error = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(exclude_none=True),
        headers=headers,
    )


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):
        raise exc
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        # The client gets only the clean message; the original cause (chained with
        # "raise ... from exc") goes to the log together with the traceback.
        logger.error("%s: %s", exc.code, exc.message, exc_info=exc)
    return error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
