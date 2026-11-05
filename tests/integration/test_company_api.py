"""Company endpoints under ``/api/v1/companies`` (D-04, D-05, D-08, D-10, D-13).

The tests go through HTTP only: the app runs on this test's own migrated database (D-12),
and every state a test needs is created through the API itself. Business rules are
covered in detail by the service tests; these tests check the HTTP contract: paths,
status codes, the response shape and the error format.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

pytestmark: pytest.MarkDecorator = pytest.mark.integration

COMPANIES: str = "/api/v1/companies"
GET_OR_CREATE: str = f"{COMPANIES}/get-or-create"
UNKNOWN_ID: str = "00000000-0000-4000-8000-000000000000"

READ_FIELDS: set[str] = {
    "id",
    "name",
    "notes",
    "location",
    "industry",
    "website",
    "is_active",
    "created_at",
    "updated_at",
}


async def _create(client: AsyncClient, name: str, **fields: Any) -> dict[str, Any]:
    """Create a company through the API and return its body."""
    response = await client.post(COMPANIES, json={"name": name, **fields})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _deactivate(client: AsyncClient, company_id: str) -> None:
    response = await client.patch(f"{COMPANIES}/{company_id}", json={"is_active": False})
    assert response.status_code == 200, response.text


def _error_code(body: dict[str, Any]) -> str:
    code: str = body["error"]["code"]
    return code


def _invalid_fields(body: dict[str, Any]) -> list[str]:
    assert body["error"]["code"] == "validation_error"
    return [detail["field"] for detail in body["error"]["details"]]


def _names(page: dict[str, Any]) -> list[str]:
    return [item["name"] for item in page["items"]]


# --- POST /companies -------------------------------------------------------------------


async def test_create_returns_201_with_the_new_company(db_client: AsyncClient) -> None:
    response = await db_client.post(
        COMPANIES,
        json={"name": "  Acme  ", "website": "https://acme.com", "location": "Warszawa"},
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == READ_FIELDS
    UUID(body["id"])
    assert body["name"] == "Acme"
    assert body["website"] == "https://acme.com"
    assert body["location"] == "Warszawa"
    assert body["industry"] is None
    assert body["notes"] is None
    assert body["is_active"] is True


async def test_created_company_can_be_read_back(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme")

    response = await db_client.get(f"{COMPANIES}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_create_with_a_taken_name_regardless_of_case_returns_409(
    db_client: AsyncClient,
) -> None:
    await _create(db_client, "Acme")

    response = await db_client.post(COMPANIES, json={"name": "ACME"})

    assert response.status_code == 409
    assert _error_code(response.json()) == "company_already_exists"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"name": "Acme", "website": "http://acme.com"}, "website"),
    ],
    ids=["missing-name", "blank-name", "too-long-name", "website-not-https"],
)
async def test_create_with_invalid_data_returns_422(
    db_client: AsyncClient, payload: dict[str, Any], field: str
) -> None:
    response = await db_client.post(COMPANIES, json=payload)

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == [field]


@pytest.mark.parametrize("field", ["id", "is_active", "created_at", "updated_at"])
async def test_create_rejects_fields_the_client_must_not_set(
    db_client: AsyncClient, field: str
) -> None:
    response = await db_client.post(COMPANIES, json={"name": "Acme", field: "x"})

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == [field]


# --- GET /companies/{company_id} ---------------------------------------------------------


async def test_get_returns_an_inactive_company_too(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme")
    await _deactivate(db_client, created["id"])

    response = await db_client.get(f"{COMPANIES}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_get_unknown_company_returns_404(db_client: AsyncClient) -> None:
    response = await db_client.get(f"{COMPANIES}/{UNKNOWN_ID}")

    assert response.status_code == 404
    assert _error_code(response.json()) == "not_found"


async def test_get_with_an_id_that_is_not_a_uuid_returns_422(db_client: AsyncClient) -> None:
    response = await db_client.get(f"{COMPANIES}/42")

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == ["company_id"]


# --- GET /companies ----------------------------------------------------------------------


async def test_list_returns_a_page_sorted_by_name_regardless_of_case(
    db_client: AsyncClient,
) -> None:
    for name in ["beta", "Gamma", "Alpha"]:
        await _create(db_client, name)

    response = await db_client.get(COMPANIES)

    assert response.status_code == 200
    page = response.json()
    assert set(page) == {"items", "total", "limit", "offset"}
    assert _names(page) == ["Alpha", "beta", "Gamma"]
    assert page["total"] == 3
    assert page["limit"] == 20
    assert page["offset"] == 0
    assert set(page["items"][0]) == READ_FIELDS


async def test_list_of_no_companies_is_an_empty_page(db_client: AsyncClient) -> None:
    response = await db_client.get(COMPANIES)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_applies_limit_and_offset_and_counts_all_matches(
    db_client: AsyncClient,
) -> None:
    for name in ["A", "B", "C", "D"]:
        await _create(db_client, name)

    response = await db_client.get(COMPANIES, params={"limit": 2, "offset": 1})

    assert response.status_code == 200
    page = response.json()
    assert _names(page) == ["B", "C"]
    assert page["total"] == 4
    assert page["limit"] == 2
    assert page["offset"] == 1


async def test_list_hides_inactive_companies_unless_asked(db_client: AsyncClient) -> None:
    await _create(db_client, "Active")
    inactive = await _create(db_client, "Inactive")
    await _deactivate(db_client, inactive["id"])

    default = (await db_client.get(COMPANIES)).json()
    with_inactive = (await db_client.get(COMPANIES, params={"include_inactive": True})).json()

    assert _names(default) == ["Active"]
    assert default["total"] == 1
    assert _names(with_inactive) == ["Active", "Inactive"]
    assert with_inactive["total"] == 2


async def test_list_search_matches_a_fragment_regardless_of_case(db_client: AsyncClient) -> None:
    for name in ["Software House", "Acme Soft", "Bank"]:
        await _create(db_client, name)

    page = (await db_client.get(COMPANIES, params={"search": "SOFT"})).json()

    assert _names(page) == ["Acme Soft", "Software House"]
    assert page["total"] == 2


async def test_list_search_takes_wildcards_literally(db_client: AsyncClient) -> None:
    await _create(db_client, "100% Remote")
    await _create(db_client, "Acme")

    page = (await db_client.get(COMPANIES, params={"search": "%"})).json()

    assert _names(page) == ["100% Remote"]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"offset": -1}, "offset"),
        ({"search": "x" * 201}, "search"),
        ({"include_inactive": "maybe"}, "include_inactive"),
    ],
    ids=["limit-zero", "limit-above-max", "negative-offset", "too-long-search", "bad-flag"],
)
async def test_list_with_invalid_query_parameters_returns_422(
    db_client: AsyncClient, params: dict[str, Any], field: str
) -> None:
    response = await db_client.get(COMPANIES, params=params)

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == [field]


# --- PATCH /companies/{company_id} -------------------------------------------------------


async def test_update_changes_only_the_fields_sent(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme", location="Warszawa", notes="Recruiter: Ola")

    response = await db_client.patch(f"{COMPANIES}/{created['id']}", json={"industry": "Fintech"})

    assert response.status_code == 200
    body = response.json()
    assert body["industry"] == "Fintech"
    assert body["location"] == "Warszawa"
    assert body["notes"] == "Recruiter: Ola"
    assert body["name"] == "Acme"
    assert body["id"] == created["id"]
    assert body["created_at"] == created["created_at"]


async def test_update_with_null_clears_an_optional_field(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme", location="Warszawa")

    response = await db_client.patch(f"{COMPANIES}/{created['id']}", json={"location": None})

    assert response.status_code == 200
    assert response.json()["location"] is None


async def test_update_can_deactivate_and_reactivate_a_company(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme")
    url = f"{COMPANIES}/{created['id']}"

    deactivated = await db_client.patch(url, json={"is_active": False})
    reactivated = await db_client.patch(url, json={"is_active": True})

    assert deactivated.json()["is_active"] is False
    assert reactivated.json()["is_active"] is True


async def test_update_is_persisted(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme")

    await db_client.patch(f"{COMPANIES}/{created['id']}", json={"name": "Acme Corp"})

    assert (await db_client.get(f"{COMPANIES}/{created['id']}")).json()["name"] == "Acme Corp"


async def test_update_to_a_taken_name_returns_409(db_client: AsyncClient) -> None:
    await _create(db_client, "Acme")
    other = await _create(db_client, "Other")

    response = await db_client.patch(f"{COMPANIES}/{other['id']}", json={"name": "acme"})

    assert response.status_code == 409
    assert _error_code(response.json()) == "company_already_exists"


async def test_update_unknown_company_returns_404(db_client: AsyncClient) -> None:
    response = await db_client.patch(f"{COMPANIES}/{UNKNOWN_ID}", json={"name": "Acme"})

    assert response.status_code == 404
    assert _error_code(response.json()) == "not_found"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": None}, "name"),
        ({"is_active": None}, "is_active"),
        ({"website": "ftp://acme.com"}, "website"),
        ({"id": UNKNOWN_ID}, "id"),
        ({"created_at": "2026-01-01T00:00:00Z"}, "created_at"),
    ],
    ids=["null-name", "null-is-active", "website-not-https", "id", "created-at"],
)
async def test_update_with_invalid_data_returns_422(
    db_client: AsyncClient, payload: dict[str, Any], field: str
) -> None:
    created = await _create(db_client, "Acme")

    response = await db_client.patch(f"{COMPANIES}/{created['id']}", json=payload)

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == [field]


async def test_companies_cannot_be_deleted(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme")

    response = await db_client.delete(f"{COMPANIES}/{created['id']}")

    assert response.status_code == 405
    assert _error_code(response.json()) == "method_not_allowed"


# --- POST /companies/get-or-create -------------------------------------------------------


async def test_get_or_create_creates_a_missing_company_with_201(db_client: AsyncClient) -> None:
    response = await db_client.post(GET_OR_CREATE, json={"name": "Acme", "industry": "Fintech"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == READ_FIELDS
    assert body["name"] == "Acme"
    assert body["industry"] == "Fintech"


async def test_get_or_create_returns_an_existing_company_unchanged_with_200(
    db_client: AsyncClient,
) -> None:
    created = await _create(db_client, "Acme", industry="Fintech")

    response = await db_client.post(GET_OR_CREATE, json={"name": "ACME", "industry": "Retail"})

    assert response.status_code == 200
    assert response.json() == created


async def test_get_or_create_twice_creates_one_company(db_client: AsyncClient) -> None:
    first = await db_client.post(GET_OR_CREATE, json={"name": "Acme"})
    second = await db_client.post(GET_OR_CREATE, json={"name": "Acme"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert (await db_client.get(COMPANIES)).json()["total"] == 1


async def test_get_or_create_refuses_an_inactive_company_with_409(db_client: AsyncClient) -> None:
    created = await _create(db_client, "Acme")
    await _deactivate(db_client, created["id"])

    response = await db_client.post(GET_OR_CREATE, json={"name": "acme"})

    assert response.status_code == 409
    assert _error_code(response.json()) == "company_inactive"
    assert (await db_client.get(f"{COMPANIES}/{created['id']}")).json()["is_active"] is False


async def test_get_or_create_with_invalid_data_returns_422(db_client: AsyncClient) -> None:
    response = await db_client.post(GET_OR_CREATE, json={"name": ""})

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == ["name"]


# --- OpenAPI -----------------------------------------------------------------------------


async def test_openapi_documents_the_company_endpoints(db_client: AsyncClient) -> None:
    paths = (await db_client.get("/openapi.json")).json()["paths"]

    assert set(paths[COMPANIES]) == {"get", "post"}
    assert set(paths[f"{COMPANIES}/{{company_id}}"]) == {"get", "patch"}
    assert set(paths[GET_OR_CREATE]) == {"post"}
    assert "404" in paths[f"{COMPANIES}/{{company_id}}"]["get"]["responses"]
    assert "409" in paths[COMPANIES]["post"]["responses"]
