"""The offer list ``GET /api/v1/job-offers`` and the tag list ``GET /api/v1/tags`` (D-21).

The tests go through HTTP only: the app runs on this test's own migrated database (D-12),
and the offers are created through the API. They check the filters (combined with AND),
the sort orders, the pagination (D-08) and that offers of inactive companies are hidden
unless asked for (D-04).
"""

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark: pytest.MarkDecorator = pytest.mark.integration

COMPANIES: str = "/api/v1/companies"
JOB_OFFERS: str = "/api/v1/job-offers"
TAGS: str = "/api/v1/tags"


async def _company(client: AsyncClient, name: str) -> str:
    response = await client.post(COMPANIES, json={"name": name})
    assert response.status_code == 201, response.text
    company_id: str = response.json()["id"]
    return company_id


async def _offer(client: AsyncClient, company_id: str, title: str, **fields: Any) -> str:
    """Create an offer titled ``title`` and return its ID; the URL is derived from the title."""
    slug = title.lower().replace(" ", "-").replace("%", "pct")
    payload: dict[str, Any] = {
        "company_id": company_id,
        "title": title,
        "url": f"https://justjoin.it/job-offer/{slug}",
        "source": "justjoinit",
        "seniority": "mid",
        "work_mode": "remote",
    }
    response = await client.post(JOB_OFFERS, json=payload | fields)
    assert response.status_code == 201, response.text
    offer_id: str = response.json()["id"]
    return offer_id


async def _titles(client: AsyncClient, **params: Any) -> list[str]:
    response = await client.get(JOB_OFFERS, params=params)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def _salary(maximum: int, currency: str = "PLN") -> dict[str, Any]:
    return {"salary_min": maximum - 1000, "salary_max": maximum, "currency": currency}


# --- Shape, pagination, default order ------------------------------------------------------


async def test_list_of_no_offers_is_an_empty_page(db_client: AsyncClient) -> None:
    response = await db_client.get(JOB_OFFERS)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_items_have_the_shape_of_a_single_offer(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    offer_id = await _offer(db_client, company_id, "Python Developer", tags=["python"])

    page = (await db_client.get(JOB_OFFERS)).json()
    single = (await db_client.get(f"{JOB_OFFERS}/{offer_id}")).json()

    assert page["items"] == [single]


async def test_newest_first_by_posting_date_then_creation(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Older", posted_on="2026-10-01")
    await _offer(db_client, company_id, "Without date")
    await _offer(db_client, company_id, "Newer", posted_on="2026-10-20")
    await _offer(db_client, company_id, "Also without date")

    # Posting date descending, missing dates last; among those, the latest created first.
    assert await _titles(db_client) == ["Newer", "Older", "Also without date", "Without date"]


async def test_limit_and_offset_select_a_page_and_total_counts_all(
    db_client: AsyncClient,
) -> None:
    company_id = await _company(db_client, "ACME")
    for day in range(1, 6):
        await _offer(db_client, company_id, f"Offer {day}", posted_on=f"2026-10-0{day}")

    response = await db_client.get(JOB_OFFERS, params={"limit": 2, "offset": 1})

    page = response.json()
    assert [item["title"] for item in page["items"]] == ["Offer 4", "Offer 3"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 1)


# --- Filters ------------------------------------------------------------------------------


async def test_filter_by_company(db_client: AsyncClient) -> None:
    acme = await _company(db_client, "ACME")
    globex = await _company(db_client, "Globex")
    await _offer(db_client, acme, "At ACME")
    await _offer(db_client, globex, "At Globex")

    assert await _titles(db_client, company_id=globex) == ["At Globex"]


async def test_filter_by_any_of_several_work_modes(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Remote", work_mode="remote", posted_on="2026-10-03")
    await _offer(db_client, company_id, "Hybrid", work_mode="hybrid", posted_on="2026-10-02")
    await _offer(db_client, company_id, "Office", work_mode="office", posted_on="2026-10-01")

    assert await _titles(db_client, work_mode=["remote", "hybrid"]) == ["Remote", "Hybrid"]


async def test_filter_by_seniority_includes_combined_levels(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    for day, seniority in enumerate(["junior", "junior_mid", "mid", "mid_senior", "senior"], 1):
        await _offer(
            db_client, company_id, seniority, seniority=seniority, posted_on=f"2026-10-0{day}"
        )

    assert await _titles(db_client, seniority="mid") == ["mid_senior", "mid", "junior_mid"]


async def test_filter_by_tags_requires_all_of_them(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Both", tags=["python", "fastapi"], posted_on="2026-10-02")
    await _offer(db_client, company_id, "Python only", tags=["python"], posted_on="2026-10-01")

    assert await _titles(db_client, tag="python") == ["Both", "Python only"]
    assert await _titles(db_client, tag=["Python", "FastAPI"]) == ["Both"]
    assert await _titles(db_client, tag="django") == []


async def test_filter_by_minimum_salary_in_a_currency(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "High", posted_on="2026-10-04", **_salary(30_000))
    await _offer(db_client, company_id, "Exact", posted_on="2026-10-03", **_salary(25_000))
    await _offer(db_client, company_id, "Low", posted_on="2026-10-02", **_salary(20_000))
    await _offer(db_client, company_id, "Euro", posted_on="2026-10-01", **_salary(30_000, "EUR"))
    await _offer(db_client, company_id, "No salary")

    # An offer can pay at least min_salary when its maximum reaches it (D-21).
    assert await _titles(db_client, min_salary=25_000, currency="PLN") == ["High", "Exact"]


async def test_minimum_salary_without_currency_returns_422(db_client: AsyncClient) -> None:
    response = await db_client.get(JOB_OFFERS, params={"min_salary": 20_000})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_filter_by_any_of_several_sources(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "LinkedIn", source="linkedin", posted_on="2026-10-03")
    await _offer(db_client, company_id, "Pracuj", source="pracuj", posted_on="2026-10-02")
    await _offer(db_client, company_id, "JJIT", source="justjoinit", posted_on="2026-10-01")

    assert await _titles(db_client, source=["linkedin", "pracuj"]) == ["LinkedIn", "Pracuj"]


async def test_search_matches_a_fragment_of_the_title_regardless_of_case(
    db_client: AsyncClient,
) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Senior Python Developer", posted_on="2026-10-03")
    await _offer(db_client, company_id, "Backend Engineer (python)", posted_on="2026-10-02")
    await _offer(db_client, company_id, "100% Remote Go Developer", posted_on="2026-10-01")

    assert await _titles(db_client, search="PYTHON") == [
        "Senior Python Developer",
        "Backend Engineer (python)",
    ]
    assert await _titles(db_client, search="%") == ["100% Remote Go Developer"]


async def test_offers_of_inactive_companies_are_hidden_unless_asked(
    db_client: AsyncClient,
) -> None:
    active = await _company(db_client, "Active")
    inactive = await _company(db_client, "Inactive")
    await _offer(db_client, active, "Visible", posted_on="2026-10-02")
    await _offer(db_client, inactive, "Hidden", posted_on="2026-10-01")
    await db_client.patch(f"{COMPANIES}/{inactive}", json={"is_active": False})

    default = (await db_client.get(JOB_OFFERS)).json()
    everything = (await db_client.get(JOB_OFFERS, params={"include_inactive": True})).json()

    assert [item["title"] for item in default["items"]] == ["Visible"]
    assert default["total"] == 1
    assert [item["title"] for item in everything["items"]] == ["Visible", "Hidden"]
    assert everything["total"] == 2


async def test_filters_are_combined(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Match", work_mode="remote", tags=["python"])
    await _offer(db_client, company_id, "Wrong mode", work_mode="office", tags=["python"])
    await _offer(db_client, company_id, "Wrong tag", work_mode="remote", tags=["go"])

    assert await _titles(db_client, work_mode="remote", tag="python") == ["Match"]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"sort": "random"}, "sort"),
        ({"seniority": "principal"}, "seniority"),
        ({"limit": 101}, "limit"),
        ({"tag": "ci/cd"}, "tag.0"),
    ],
    ids=["sort", "seniority", "limit", "tag"],
)
async def test_invalid_query_parameter_returns_422(
    db_client: AsyncClient, params: dict[str, Any], field: str
) -> None:
    response = await db_client.get(JOB_OFFERS, params=params)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert [detail["field"] for detail in body["error"]["details"]] == [field]


# --- Sort ---------------------------------------------------------------------------------


async def test_sort_by_salary_puts_the_best_paid_first(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Middle", **_salary(25_000))
    await _offer(db_client, company_id, "No salary")
    await _offer(db_client, company_id, "Top", **_salary(30_000))
    await _offer(db_client, company_id, "Bottom", **_salary(20_000))

    assert await _titles(db_client, sort="salary") == ["Top", "Middle", "Bottom", "No salary"]


async def test_sort_by_title_regardless_of_case(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    for title in ["beta", "Gamma", "Alpha"]:
        await _offer(db_client, company_id, title)

    assert await _titles(db_client, sort="title") == ["Alpha", "beta", "Gamma"]


# --- GET /tags ----------------------------------------------------------------------------


async def test_tags_are_listed_alphabetically_with_a_total(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "First", tags=["python", "fastapi"])
    await _offer(db_client, company_id, "Second", tags=["aws", "python"])

    response = await db_client.get(TAGS)

    assert response.status_code == 200
    assert response.json() == {
        "items": ["aws", "fastapi", "python"],
        "total": 3,
        "limit": 20,
        "offset": 0,
    }


async def test_tags_can_be_searched_and_paginated(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    await _offer(db_client, company_id, "Offer", tags=["postgresql", "mysql", "python", "sql"])

    searched = (await db_client.get(TAGS, params={"search": "SQL"})).json()
    paged = (await db_client.get(TAGS, params={"limit": 2, "offset": 1})).json()

    assert searched["items"] == ["mysql", "postgresql", "sql"]
    assert (paged["items"], paged["total"]) == (["postgresql", "python"], 4)


async def test_tags_of_a_deleted_offer_stay_listed(db_client: AsyncClient) -> None:
    company_id = await _company(db_client, "ACME")
    offer_id = await _offer(db_client, company_id, "Offer", tags=["python"])

    await db_client.delete(f"{JOB_OFFERS}/{offer_id}")

    assert (await db_client.get(TAGS)).json()["items"] == ["python"]


# --- OpenAPI ------------------------------------------------------------------------------


async def test_openapi_documents_the_lists(db_client: AsyncClient) -> None:
    paths = (await db_client.get("/openapi.json")).json()["paths"]

    assert set(paths[JOB_OFFERS]) == {"get", "post"}
    assert set(paths[TAGS]) == {"get"}
    assert "422" in paths[JOB_OFFERS]["get"]["responses"]
