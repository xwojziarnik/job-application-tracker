"""Request validation errors (422) in the shared error format (D-13).

Each validation error becomes one entry in ``details``: ``field`` is the path to the
invalid value without its source (``body``, ``query``, ``path``), joined with dots, and
``message`` is the reason. The rejected input is never sent back.
"""

from typing import Annotated

from fastapi import FastAPI, Query
from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel, ValidationInfo, field_validator

from job_tracker.core.exceptions import register_exception_handlers


class Tag(BaseModel):
    name: str


class Item(BaseModel):
    name: str
    price: int
    tags: list[Tag]


class Offer(BaseModel):
    salary_min: int
    salary_max: int

    @field_validator("salary_max")
    @classmethod
    def max_not_below_min(cls, value: int, info: ValidationInfo) -> int:
        if value < info.data.get("salary_min", value):
            raise ValueError("must be greater than or equal to salary_min")
        return value


def _validation_app() -> FastAPI:
    """Minimal app whose routes validate a body, a query parameter and a path parameter."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/items")
    async def create_item(item: Item) -> Item:
        return item

    @app.get("/items/{item_id}")
    async def get_item(item_id: int, limit: Annotated[int, Query(ge=1)] = 20) -> int:
        return item_id

    @app.post("/offers")
    async def create_offer(offer: Offer) -> Offer:
        return offer

    return app


async def _send(method: str, path: str, **kwargs: object) -> Response:
    """Send a request to the validation app and return the response."""
    transport = ASGITransport(app=_validation_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)  # type: ignore[arg-type]


def _validation_error(*details: dict[str, str]) -> dict[str, object]:
    """Expected body of a validation error with the given details."""
    return {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed",
            "details": list(details),
        }
    }


VALID_ITEM = {"name": "Keyboard", "price": 100, "tags": [{"name": "hardware"}]}


async def test_missing_body_field() -> None:
    response = await _send("POST", "/items", json={"price": 100, "tags": []})

    assert response.status_code == 422
    assert response.json() == _validation_error({"field": "name", "message": "Field required"})


async def test_every_error_is_listed_in_order() -> None:
    response = await _send("POST", "/items", json={})

    assert response.status_code == 422
    assert response.json() == _validation_error(
        {"field": "name", "message": "Field required"},
        {"field": "price", "message": "Field required"},
        {"field": "tags", "message": "Field required"},
    )


async def test_nested_field_path_is_joined_with_dots() -> None:
    response = await _send("POST", "/items", json={**VALID_ITEM, "tags": [{"name": "ok"}, {}]})

    assert response.status_code == 422
    assert response.json() == _validation_error(
        {"field": "tags.1.name", "message": "Field required"}
    )


async def test_query_parameter_is_named_without_its_source() -> None:
    response = await _send("GET", "/items/1", params={"limit": 0})

    assert response.status_code == 422
    assert response.json() == _validation_error(
        {"field": "limit", "message": "Input should be greater than or equal to 1"}
    )


async def test_path_parameter_is_named_without_its_source() -> None:
    response = await _send("GET", "/items/abc")

    assert response.status_code == 422
    assert response.json() == _validation_error(
        {
            "field": "item_id",
            "message": "Input should be a valid integer, unable to parse string as an integer",
        }
    )


async def test_rejected_input_is_not_echoed_back() -> None:
    response = await _send("POST", "/items", json={**VALID_ITEM, "price": "secret-123"})

    assert response.status_code == 422
    assert "secret-123" not in response.text
    assert response.json() == _validation_error(
        {
            "field": "price",
            "message": "Input should be a valid integer, unable to parse string as an integer",
        }
    )


async def test_custom_validator_message_has_no_value_error_prefix() -> None:
    response = await _send("POST", "/offers", json={"salary_min": 20000, "salary_max": 10000})

    assert response.status_code == 422
    assert response.json() == _validation_error(
        {"field": "salary_max", "message": "must be greater than or equal to salary_min"}
    )


async def test_invalid_json_is_reported_on_the_body() -> None:
    response = await _send(
        "POST", "/items", content=b'{"name": ', headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json() == _validation_error({"field": "body", "message": "JSON decode error"})
