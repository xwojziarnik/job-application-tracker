"""Shared pagination of list endpoints (D-08).

Every list endpoint takes ``limit`` (default 20, 1 to 100) and ``offset`` (default 0) as
query parameters and returns ``{"items": [...], "total": ..., "limit": ..., "offset": ...}``.
Invalid values are rejected with ``422`` in the shared error format (D-13, D-17).
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel

from job_tracker.api.deps import PaginationDep
from job_tracker.core.exceptions import register_exception_handlers
from job_tracker.schemas.pagination import Page, PaginationParams


class ItemRead(BaseModel):
    name: str


ITEMS = [ItemRead(name=f"item-{n}") for n in range(5)]


def _paginated_app() -> FastAPI:
    """Minimal app with one list endpoint that pages a fixed list of items."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/items")
    async def list_items(pagination: PaginationDep) -> Page[ItemRead]:
        page = ITEMS[pagination.offset : pagination.offset + pagination.limit]
        return Page(items=page, total=len(ITEMS), limit=pagination.limit, offset=pagination.offset)

    return app


async def _list(**params: int) -> Response:
    """GET ``/items`` with the given query parameters."""
    transport = ASGITransport(app=_paginated_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/items", params=params)


def _invalid(field: str, message: str) -> dict[str, object]:
    """Expected body of a 422 for one invalid pagination parameter."""
    return {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed",
            "details": [{"field": field, "message": message}],
        }
    }


def test_default_pagination() -> None:
    params = PaginationParams()

    assert (params.limit, params.offset) == (20, 0)


async def test_list_uses_defaults_without_parameters() -> None:
    response = await _list()

    assert response.status_code == 200
    assert response.json() == {
        "items": [item.model_dump() for item in ITEMS],
        "total": 5,
        "limit": 20,
        "offset": 0,
    }


async def test_list_returns_the_requested_page() -> None:
    response = await _list(limit=2, offset=2)

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"name": "item-2"}, {"name": "item-3"}],
        "total": 5,
        "limit": 2,
        "offset": 2,
    }


async def test_offset_past_the_end_returns_an_empty_page_with_total() -> None:
    response = await _list(offset=10)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 5, "limit": 20, "offset": 10}


async def test_maximum_limit_is_accepted() -> None:
    response = await _list(limit=100)

    assert response.status_code == 200
    assert response.json()["limit"] == 100


async def test_limit_above_maximum_is_rejected() -> None:
    response = await _list(limit=101)

    assert response.status_code == 422
    assert response.json() == _invalid("limit", "Input should be less than or equal to 100")


async def test_limit_below_one_is_rejected() -> None:
    response = await _list(limit=0)

    assert response.status_code == 422
    assert response.json() == _invalid("limit", "Input should be greater than or equal to 1")


async def test_negative_offset_is_rejected() -> None:
    response = await _list(offset=-1)

    assert response.status_code == 422
    assert response.json() == _invalid("offset", "Input should be greater than or equal to 0")


def test_pagination_is_documented_as_query_parameters() -> None:
    operation = _paginated_app().openapi()["paths"]["/items"]["get"]

    parameters = {p["name"]: p for p in operation["parameters"]}
    assert set(parameters) == {"limit", "offset"}
    assert all(p["in"] == "query" for p in parameters.values())
    assert "requestBody" not in operation
