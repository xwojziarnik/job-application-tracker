"""Domain errors and the handlers that render every API error in one format (D-13).

Each error response has the shape ``{"error": {"code", "message", "details"?}}``:
``code`` is a stable, machine-readable identifier clients can branch on, ``message`` is
meant for humans, and ``details`` is present only when there are field-level details.
"""

import logging
import re
from collections.abc import Mapping
from http import HTTPStatus

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic_core import ErrorDetails
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    """Base class for errors raised by the service layer.

    Subclasses define the HTTP status, the error code and a default message as class
    attributes, so a specific error only overrides what differs from its category,
    e.g. ``CompanyInactiveError`` keeps the 409 of ``ConflictError`` and changes the code.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "domain_error"
    default_message: str = "Request could not be processed"

    def __init__(self, message: str | None = None) -> None:
        """Use ``message`` if given, otherwise the class's ``default_message``."""
        self.message = message or self.default_message
        super().__init__(self.message)


class ConflictError(DomainError):
    """The request conflicts with the current state of a resource (409)."""

    status_code: int = status.HTTP_409_CONFLICT
    code: str = "conflict"
    default_message: str = "Request conflicts with the current state of the resource"


class ServiceUnavailableError(DomainError):
    """A dependency the request needs is not available (503)."""

    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE
    code: str = "service_unavailable"
    default_message: str = "Service unavailable"


class DatabaseUnavailableError(ServiceUnavailableError):
    """The database cannot be reached."""

    code: str = "database_unavailable"
    default_message: str = "Database unavailable"


class CompanyInactiveError(ConflictError):
    """The operation is not allowed for an inactive company (D-10)."""

    code: str = "company_inactive"


class NotFoundError(DomainError):
    """The requested resource does not exist (404)."""

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
    """Build a JSON response in the shared error format.

    ``details`` is left out of the body when it is ``None``. ``headers`` are passed on
    unchanged, e.g. ``Allow`` for 405 or ``WWW-Authenticate`` for 401.
    """
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


async def domain_error_handler(_: Request, exception: Exception) -> JSONResponse:
    """Render a ``DomainError`` using its status, code and message.

    Server-side errors (5xx) are also logged with the traceback, which includes the
    original cause chained with ``raise ... from``; client errors (4xx) are not logged.
    """
    if not isinstance(exception, DomainError):
        raise exception
    if exception.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        # The client gets only the clean message; the original cause (chained with
        # "raise ... from exc") goes to the log together with the traceback.
        logger.error("%s: %s", exception.code, exception.message, exc_info=exception)
    return error_response(
        status_code=exception.status_code,
        code=exception.code,
        message=exception.message,
    )


def _code_for_status(status_code: int) -> str:
    """Derive a snake_case error code from the HTTP status phrase.

    Every run of characters other than letters and digits becomes one underscore, e.g.
    404 -> ``not_found``, 418 ("I'm a Teapot") -> ``i_m_a_teapot``. Statuses outside
    the standard (e.g. 499) fall back to ``http_error``.
    """
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        return "http_error"
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower().strip())


async def http_exception_handler(_: Request, exception: Exception) -> JSONResponse:
    """Render an ``HTTPException`` in the shared error format.

    Registered for Starlette's ``HTTPException``, so it also covers FastAPI's subclass
    and the 404/405 raised by the router itself. A string ``detail`` (by default the
    status phrase) becomes the message; any other ``detail`` is not exposed.
    """
    if not isinstance(exception, StarletteHTTPException):
        raise exception
    return error_response(
        status_code=exception.status_code,
        code=_code_for_status(exception.status_code),
        message=exception.detail if isinstance(exception.detail, str) else "HTTP error",
        headers=exception.headers,
    )


def _error_detail(error: ErrorDetails) -> ErrorDetail:
    """Turn one error from ``RequestValidationError.errors()`` into an ``ErrorDetail``.

    ``field`` is the location without its source (``body``, ``query``, ``path``), joined
    with dots: ``("body", "tags", 1, "name")`` -> ``tags.1.name``. The source itself is
    used when nothing else is left (an error on the whole model) and for invalid JSON,
    whose location is only a character position. ``message`` is Pydantic's message
    without the ``"Value error, "`` prefix it adds to errors from custom validators.
    The rejected input and the error context are left out.
    """
    source, *path = error["loc"]
    if error["type"] == "json_invalid" or not path:
        field = str(source)
    else:
        field = ".".join(str(part) for part in path)
    return ErrorDetail(field=field, message=error["msg"].removeprefix("Value error, "))


async def validation_error_handler(_: Request, exception: Exception) -> JSONResponse:
    """Render a ``RequestValidationError`` as 422 in the shared error format.

    FastAPI raises it when the body, query, path or header parameters of a request do not
    match their declared types. Each error becomes one entry in ``details``; the rejected
    input is never sent back.
    """
    from fastapi.exceptions import RequestValidationError

    if not isinstance(exception, RequestValidationError):
        raise exception
    details = [_error_detail(error) for error in exception.errors()]
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message="Request validation failed",
        details=details,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the error handlers on ``app``, replacing FastAPI's defaults."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
