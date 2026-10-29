"""Unexpected exceptions (500) in the shared error format (D-13).

The client gets only a generic ``internal_server_error``, the same code an explicit
``HTTPException(500)`` gets; the exception, its message and the traceback go to the
server log. Nothing from the exception may appear in the response.
"""

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel

from job_tracker.core.exceptions import register_exception_handlers

INTERNAL_ERROR = {"error": {"code": "internal_server_error", "message": "Internal server error"}}


class Item(BaseModel):
    name: str


def _crashing_app() -> FastAPI:
    """Minimal app whose routes fail in ways the client must not learn about."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("password=hunter2 at db.internal:5432")

    @app.get("/invalid-response", response_model=Item)
    async def invalid_response() -> dict[str, str]:
        # Does not match the response model, so FastAPI raises ResponseValidationError.
        return {"secret": "token-abc"}

    return app


async def _get(path: str) -> Response:
    """GET ``path`` and return the response instead of re-raising the app's exception.

    Starlette re-raises an unhandled exception after sending the 500 response, so that
    the server can log it; ``raise_app_exceptions=False`` lets the test see the response.
    """
    transport = ASGITransport(app=_crashing_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_unexpected_exception_returns_generic_internal_error() -> None:
    response = await _get("/crash")

    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
    assert "hunter2" not in response.text


async def test_unexpected_exception_is_logged_with_request_and_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="job_tracker.core.exceptions"):
        await _get("/crash")

    [record] = [r for r in caplog.records if r.name == "job_tracker.core.exceptions"]
    assert record.levelno == logging.ERROR
    assert "GET" in record.getMessage()
    assert "/crash" in record.getMessage()
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], RuntimeError)


async def test_invalid_response_is_an_internal_error() -> None:
    response = await _get("/invalid-response")

    assert response.status_code == 500
    assert response.json() == INTERNAL_ERROR
    assert "token-abc" not in response.text
