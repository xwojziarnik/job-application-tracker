"""Job offer endpoints under ``/api/v1/job-offers``: create, read, update, delete (D-21).

The tests go through HTTP only: the app runs on this test's own migrated database (D-12),
and every state a test needs is created through the API itself. Business rules are
covered in detail by the service and schema tests; these tests check the HTTP contract:
paths, status codes, the response shape and the error format (D-13). The list of offers
and ``GET /tags`` come in the next pull request.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

pytestmark: pytest.MarkDecorator = pytest.mark.integration

COMPANIES: str = "/api/v1/companies"
JOB_OFFERS: str = "/api/v1/job-offers"
UNKNOWN_ID: str = "00000000-0000-4000-8000-000000000000"
SALARY: dict[str, Any] = {"salary_min": 18_000, "salary_max": 24_000, "currency": "PLN"}

READ_FIELDS: set[str] = {
    "id",
    "company",
    "title",
    "url",
    "source",
    "seniority",
    "work_mode",
    "location",
    "salary_min",
    "salary_max",
    "currency",
    "posted_on",
    "description",
    "notes",
    "tags",
    "created_at",
    "updated_at",
}


async def _company(client: AsyncClient, name: str = "ACME") -> str:
    """Create a company through the API and return its ID."""
    response = await client.post(COMPANIES, json={"name": name})
    assert response.status_code == 201, response.text
    company_id: str = response.json()["id"]
    return company_id


def _payload(company_id: str, slug: str = "python-developer", **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "company_id": company_id,
        "title": "Python Developer",
        "url": f"https://justjoin.it/job-offer/{slug}",
        "source": "justjoinit",
        "seniority": "mid",
        "work_mode": "remote",
    }
    return data | fields


async def _create(client: AsyncClient, company_id: str, **fields: Any) -> dict[str, Any]:
    """Create an offer through the API and return its body."""
    response = await client.post(JOB_OFFERS, json=_payload(company_id, **fields))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _error_code(body: dict[str, Any]) -> str:
    code: str = body["error"]["code"]
    return code


def _invalid_fields(body: dict[str, Any]) -> list[str]:
    assert body["error"]["code"] == "validation_error"
    return [detail["field"] for detail in body["error"]["details"]]


# --- POST /job-offers ---------------------------------------------------------------------


async def test_create_returns_201_with_the_new_offer(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)

    response = await db_client.post(
        JOB_OFFERS,
        json=_payload(
            company_id,
            url=" HTTPS://JustJoin.IT/job-offer/acme/?utm_source=newsletter ",
            seniority="mid_senior",
            tags=["Python", "FastAPI", "python"],
            posted_on="2026-10-30",
            **SALARY,
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == READ_FIELDS
    UUID(body["id"])
    assert body["company"] == {"id": company_id, "name": "ACME", "is_active": True}
    assert body["url"] == "https://justjoin.it/job-offer/acme"
    assert body["seniority"] == "mid_senior"
    assert body["tags"] == ["fastapi", "python"]
    assert (body["salary_min"], body["salary_max"], body["currency"]) == (18_000, 24_000, "PLN")
    assert body["posted_on"] == "2026-10-30"
    assert body["location"] is None


async def test_created_offer_can_be_read_back(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id, tags=["python"])

    response = await db_client.get(f"{JOB_OFFERS}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_create_for_an_unknown_company_returns_404(db_client: AsyncClient) -> None:
    response = await db_client.post(JOB_OFFERS, json=_payload(UNKNOWN_ID))

    assert response.status_code == 404
    assert _error_code(response.json()) == "not_found"


async def test_create_for_an_inactive_company_returns_409(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    await db_client.patch(f"{COMPANIES}/{company_id}", json={"is_active": False})

    response = await db_client.post(JOB_OFFERS, json=_payload(company_id))

    assert response.status_code == 409
    assert _error_code(response.json()) == "company_inactive"


async def test_create_with_a_stored_url_in_another_spelling_returns_409(
    db_client: AsyncClient,
) -> None:
    company_id = await _company(db_client)
    await _create(db_client, company_id, url="https://acme.com/jobs/1")

    response = await db_client.post(
        JOB_OFFERS, json=_payload(company_id, url="HTTPS://ACME.com/jobs/1/#apply")
    )

    assert response.status_code == 409
    assert _error_code(response.json()) == "job_offer_already_exists"


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"title": "   "}, "title"),
        ({"url": "http://acme.com/jobs/1"}, "url"),
        ({"seniority": "principal"}, "seniority"),
        ({"posted_on": "2999-01-01"}, "posted_on"),
        ({"tags": ["ci/cd"]}, "tags.0"),
        ({"id": UNKNOWN_ID}, "id"),
        ({"salary_min": 18_000}, "body"),
    ],
    ids=["blank-title", "http-url", "seniority", "future-date", "invalid-tag", "id", "salary"],
)
async def test_create_with_invalid_data_returns_422(
    db_client: AsyncClient, fields: dict[str, Any], field: str
) -> None:
    company_id = await _company(db_client)

    response = await db_client.post(JOB_OFFERS, json=_payload(company_id, **fields))

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == [field]


# --- GET /job-offers/{job_offer_id} -------------------------------------------------------


async def test_get_returns_an_offer_of_an_inactive_company_too(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id)
    await db_client.patch(f"{COMPANIES}/{company_id}", json={"is_active": False})

    response = await db_client.get(f"{JOB_OFFERS}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["company"]["is_active"] is False


async def test_get_unknown_offer_returns_404(db_client: AsyncClient) -> None:
    response = await db_client.get(f"{JOB_OFFERS}/{UNKNOWN_ID}")

    assert response.status_code == 404
    assert _error_code(response.json()) == "not_found"


async def test_get_with_an_id_that_is_not_a_uuid_returns_422(db_client: AsyncClient) -> None:
    response = await db_client.get(f"{JOB_OFFERS}/42")

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == ["job_offer_id"]


# --- PATCH /job-offers/{job_offer_id} -----------------------------------------------------


async def test_update_changes_only_the_fields_sent(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id, location="Kraków", tags=["python"])

    response = await db_client.patch(
        f"{JOB_OFFERS}/{created['id']}", json={"title": "Senior Python Developer"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Senior Python Developer"
    assert body["location"] == "Kraków"
    assert body["tags"] == ["python"]
    assert body["company"] == created["company"]
    assert body["created_at"] == created["created_at"]


async def test_update_replaces_the_tags_and_is_persisted(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id, tags=["django", "python"])

    patched = await db_client.patch(
        f"{JOB_OFFERS}/{created['id']}", json={"tags": ["Python", "FastAPI"]}
    )
    read = await db_client.get(f"{JOB_OFFERS}/{created['id']}")

    assert patched.json()["tags"] == ["fastapi", "python"]
    assert read.json()["tags"] == ["fastapi", "python"]


async def test_update_with_null_clears_an_optional_field(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id, location="Kraków")

    response = await db_client.patch(f"{JOB_OFFERS}/{created['id']}", json={"location": None})

    assert response.status_code == 200
    assert response.json()["location"] is None


async def test_update_that_leaves_an_incomplete_salary_returns_422(
    db_client: AsyncClient,
) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id)

    response = await db_client.patch(f"{JOB_OFFERS}/{created['id']}", json={"salary_max": 30_000})

    assert response.status_code == 422
    assert _error_code(response.json()) == "invalid_salary"


async def test_update_to_the_url_of_another_offer_returns_409(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    await _create(db_client, company_id, url="https://acme.com/jobs/1")
    second = await _create(db_client, company_id, url="https://acme.com/jobs/2")

    response = await db_client.patch(
        f"{JOB_OFFERS}/{second['id']}", json={"url": "https://acme.com/jobs/1/"}
    )

    assert response.status_code == 409
    assert _error_code(response.json()) == "job_offer_already_exists"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"company_id": UNKNOWN_ID}, "company_id"),
        ({"title": None}, "title"),
        ({"tags": None}, "tags"),
    ],
    ids=["company-id", "null-title", "null-tags"],
)
async def test_update_with_invalid_data_returns_422(
    db_client: AsyncClient, payload: dict[str, Any], field: str
) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id)

    response = await db_client.patch(f"{JOB_OFFERS}/{created['id']}", json=payload)

    assert response.status_code == 422
    assert _invalid_fields(response.json()) == [field]


async def test_update_unknown_offer_returns_404(db_client: AsyncClient) -> None:
    response = await db_client.patch(f"{JOB_OFFERS}/{UNKNOWN_ID}", json={"title": "Anything"})

    assert response.status_code == 404
    assert _error_code(response.json()) == "not_found"


# --- DELETE /job-offers/{job_offer_id} ----------------------------------------------------


async def test_delete_returns_204_without_a_body(db_client: AsyncClient) -> None:
    company_id = await _company(db_client)
    created = await _create(db_client, company_id, tags=["python"])

    response = await db_client.delete(f"{JOB_OFFERS}/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await db_client.get(f"{JOB_OFFERS}/{created['id']}")).status_code == 404


async def test_delete_unknown_offer_returns_404(db_client: AsyncClient) -> None:
    response = await db_client.delete(f"{JOB_OFFERS}/{UNKNOWN_ID}")

    assert response.status_code == 404
    assert _error_code(response.json()) == "not_found"


# --- OpenAPI ------------------------------------------------------------------------------


async def test_openapi_documents_the_job_offer_endpoints(db_client: AsyncClient) -> None:
    paths = (await db_client.get("/openapi.json")).json()["paths"]
    item = f"{JOB_OFFERS}/{{job_offer_id}}"

    assert "post" in paths[JOB_OFFERS]
    assert set(paths[item]) == {"get", "patch", "delete"}
    assert {"404", "409", "422"} <= set(paths[JOB_OFFERS]["post"]["responses"])
    assert {"404", "409", "422"} <= set(paths[item]["patch"]["responses"])
    assert {"204", "404"} <= set(paths[item]["delete"]["responses"])
    assert "404" in paths[item]["get"]["responses"]
