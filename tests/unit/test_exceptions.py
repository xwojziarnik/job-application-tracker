import json
import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from job_tracker.core.exceptions import (
    CompanyInactiveError,
    ConflictError,
    DatabaseUnavailableError,
    DomainError,
    ErrorDetail,
    NotFoundError,
    ServiceUnavailableError,
    error_response,
    register_exception_handlers,
)


def _json(response: Response) -> object:
    return json.loads(bytes(response.body))


def test_error_response_without_details_omits_the_key() -> None:
    response = error_response(status_code=404, code="not_found", message="Company not found")

    assert response.status_code == 404
    assert _json(response) == {"error": {"code": "not_found", "message": "Company not found"}}


def test_error_response_includes_details() -> None:
    response = error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=[ErrorDetail(field="salary_max", message="must be >= salary_min")],
    )

    assert response.status_code == 422
    assert _json(response) == {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed",
            "details": [{"field": "salary_max", "message": "must be >= salary_min"}],
        }
    }


def test_error_response_sets_headers() -> None:
    response = error_response(
        status_code=405,
        code="method_not_allowed",
        message="Method Not Allowed",
        headers={"Allow": "GET"},
    )

    assert response.headers["allow"] == "GET"


async def test_domain_error_is_returned_in_the_shared_format() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise NotFoundError("Company not found")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Company not found"}}


async def _get_error(exc: DomainError) -> tuple[int, object]:
    """Raise exc from a route of a minimal app and return the status and JSON body."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/boom")
    return response.status_code, response.json()


@pytest.mark.parametrize(
    ("exc_class", "status_code", "code"),
    [
        (DomainError, 400, "domain_error"),
        (NotFoundError, 404, "not_found"),
        (ConflictError, 409, "conflict"),
        (CompanyInactiveError, 409, "company_inactive"),
        (ServiceUnavailableError, 503, "service_unavailable"),
        (DatabaseUnavailableError, 503, "database_unavailable"),
    ],
)
async def test_domain_errors_map_to_status_and_code(
    exc_class: type[DomainError], status_code: int, code: str
) -> None:
    actual_status, body = await _get_error(exc_class("Something went wrong"))

    assert actual_status == status_code
    assert body == {"error": {"code": code, "message": "Something went wrong"}}


def test_domain_error_uses_default_message_without_argument() -> None:
    exc = DatabaseUnavailableError()

    assert exc.message == "Database unavailable"
    assert str(exc) == "Database unavailable"


def test_explicit_message_overrides_default() -> None:
    exc = DatabaseUnavailableError("Primary database is down")

    assert exc.message == "Primary database is down"


def test_subclass_without_own_default_inherits_parent_default() -> None:
    assert CompanyInactiveError().message == ConflictError().message


@pytest.mark.parametrize(
    ("exc_class", "message"),
    [
        (NotFoundError, "Resource not found"),
        (ConflictError, "Request conflicts with the current state of the resource"),
        (ServiceUnavailableError, "Service unavailable"),
        (DatabaseUnavailableError, "Database unavailable"),
    ],
)
def test_error_categories_have_default_messages(exc_class: type[DomainError], message: str) -> None:
    assert exc_class().message == message


async def test_server_side_domain_error_logs_original_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cause = OSError("connection refused by 10.0.0.5:5432")
    exc = DatabaseUnavailableError()
    exc.__cause__ = cause  # what "raise DatabaseUnavailableError() from cause" sets

    with caplog.at_level(logging.ERROR, logger="job_tracker.core.exceptions"):
        status_code, body = await _get_error(exc)

    assert status_code == 503
    assert body == {"error": {"code": "database_unavailable", "message": "Database unavailable"}}
    assert "10.0.0.5" not in json.dumps(body)
    [record] = caplog.records
    assert record.exc_info is not None
    assert record.exc_info[1] is exc
    assert record.exc_info[1].__cause__ is cause


async def test_client_side_domain_error_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="job_tracker.core.exceptions"):
        await _get_error(NotFoundError())

    assert caplog.records == []
