"""Building blocks of the offer list (D-21): seniority matching and the list parameters.

- ``Seniority.matching()`` lists the stored values an offer may have to match a requested
  level: ``mid`` also matches the combined ``junior_mid`` and ``mid_senior`` (D-15).
- ``JobOfferFilters`` validates the query parameters of ``GET /job-offers``: repeatable
  filters default to empty lists, tags are normalised like stored tags, ``min_salary`` and
  ``currency`` go together, and ``sort`` comes from a closed list.
"""

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from job_tracker.core.tags import MAX_TAGS_PER_OFFER
from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode
from job_tracker.schemas.job_offer import JobOfferFilters, JobOfferSort

# --- Seniority.matching -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (Seniority.JUNIOR, [Seniority.JUNIOR, Seniority.JUNIOR_MID]),
        (Seniority.MID, [Seniority.JUNIOR_MID, Seniority.MID, Seniority.MID_SENIOR]),
        (Seniority.SENIOR, [Seniority.MID_SENIOR, Seniority.SENIOR, Seniority.SENIOR_LEAD]),
        (Seniority.LEAD, [Seniority.SENIOR_LEAD, Seniority.LEAD]),
        (Seniority.MID_SENIOR, [Seniority.MID_SENIOR]),
    ],
    ids=["junior", "mid", "senior", "lead", "combined-matches-itself"],
)
def test_seniority_matches_every_value_that_contains_its_levels(
    level: Seniority, expected: list[Seniority]
) -> None:
    assert level.matching() == expected


# --- JobOfferFilters ----------------------------------------------------------------------


def _filters(**params: Any) -> JobOfferFilters:
    return JobOfferFilters.model_validate(params)


def test_no_parameters_mean_no_filters_and_the_newest_first() -> None:
    filters = _filters()

    assert filters.model_dump() == {
        "company_id": None,
        "work_mode": [],
        "seniority": None,
        "tag": [],
        "min_salary": None,
        "currency": None,
        "source": [],
        "search": None,
        "include_inactive": False,
        "sort": JobOfferSort.NEWEST,
    }


def test_parameters_are_converted_to_their_types() -> None:
    company_id = uuid.uuid4()

    filters = _filters(
        company_id=str(company_id),
        work_mode=["remote", "hybrid"],
        seniority="mid",
        source=["linkedin"],
        min_salary="20000",
        currency="PLN",
        include_inactive="true",
        sort="salary",
    )

    assert filters.company_id == company_id
    assert filters.work_mode == [WorkMode.REMOTE, WorkMode.HYBRID]
    assert filters.seniority is Seniority.MID
    assert filters.source == [OfferSource.LINKEDIN]
    assert (filters.min_salary, filters.currency) == (20_000, Currency.PLN)
    assert filters.include_inactive is True
    assert filters.sort is JobOfferSort.SALARY


def test_tags_are_normalised_like_stored_tags() -> None:
    assert _filters(tag=["FastAPI", " Machine Learning ", "fastapi"]).tag == [
        "fastapi",
        "machine-learning",
    ]


@pytest.mark.parametrize(
    "params",
    [{"min_salary": 20_000}, {"currency": "PLN"}],
    ids=["amount-without-currency", "currency-without-amount"],
)
def test_minimum_salary_and_currency_go_together(params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="must be given together"):
        _filters(**params)


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"sort": "random"}, "sort"),
        ({"seniority": "principal"}, "seniority"),
        ({"work_mode": ["anywhere"]}, "work_mode"),
        ({"source": ["indeed"]}, "source"),
        ({"tag": ["ci/cd"]}, "tag"),
        ({"min_salary": 0, "currency": "PLN"}, "min_salary"),
        ({"min_salary": 20_000, "currency": "GBP"}, "currency"),
        ({"search": "x" * 201}, "search"),
        ({"company_id": "42"}, "company_id"),
    ],
    ids=[
        "sort",
        "seniority",
        "work-mode",
        "source",
        "tag",
        "min-salary",
        "currency",
        "search",
        "company-id",
    ],
)
def test_invalid_parameter_is_rejected(params: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _filters(**params)

    assert {str(error["loc"][0]) for error in excinfo.value.errors()} == {field}


def test_search_is_trimmed_and_blank_search_is_no_search() -> None:
    assert _filters(search="  python ").search == "python"
    assert _filters(search="   ").search is None


@pytest.mark.parametrize("sort", ["newest", "salary", "title"])
def test_sort_accepts_the_decided_values(sort: str) -> None:
    assert _filters(sort=sort).sort == sort


# Repeatable parameters are capped, so a request cannot send thousands of values: enum
# filters at the number of values (each given once), tags at MAX_TAGS_PER_OFFER.
@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("work_mode", [mode.value for mode in WorkMode]),
        ("source", [source.value for source in OfferSource]),
        ("tag", [f"tag-{n}" for n in range(MAX_TAGS_PER_OFFER)]),
    ],
    ids=["work-mode", "source", "tag"],
)
def test_repeatable_parameter_accepts_up_to_its_limit(field: str, values: list[str]) -> None:
    assert len(getattr(_filters(**{field: values}), field)) == len(values)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("work_mode", [WorkMode.REMOTE.value] * (len(WorkMode) + 1)),
        ("source", [OfferSource.LINKEDIN.value] * (len(OfferSource) + 1)),
        ("tag", [f"tag-{n}" for n in range(MAX_TAGS_PER_OFFER + 1)]),
    ],
    ids=["work-mode", "source", "tag"],
)
def test_repeatable_parameter_over_its_limit_is_rejected(field: str, values: list[str]) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _filters(**{field: values})

    assert [error["type"] for error in excinfo.value.errors()] == ["too_long"]
