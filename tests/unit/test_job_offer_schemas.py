"""Request and response schemas of a job offer (decisions: "Job offer", D-03, D-05, D-09).

- ``title``, ``url``, ``source``, ``seniority``, ``work_mode`` and ``company_id`` are
  required on creation; text is trimmed and blank optional text becomes ``None``.
- ``url`` must be an ``https`` URL and is stored normalised (``normalise_offer_url``).
- The salary is all or nothing: ``salary_min``, ``salary_max`` and ``currency`` together,
  positive, ``salary_min <= salary_max``.
- ``posted_on`` cannot be in the future.
- ``tags`` are normalised (``normalise_tag_name``), duplicates merged, at most 20.
- Unknown fields are rejected: the client cannot set ``id`` or the timestamps, nor change
  ``company_id`` in an update.
- In an update an omitted field is not set; ``None`` clears an optional field and is
  rejected for the required ones and for ``tags``. Whether the salary is complete after an
  update is checked by the service, which knows the stored values.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode
from job_tracker.schemas.job_offer import JobOfferCreate, JobOfferRead, JobOfferUpdate

COMPANY_ID: str = str(uuid.uuid4())
FUTURE: date = date.today() + timedelta(days=400)

REQUIRED: dict[str, Any] = {
    "company_id": COMPANY_ID,
    "title": "Python Developer",
    "url": "https://justjoin.it/job-offer/acme-python-developer",
    "source": "justjoinit",
    "seniority": "mid",
    "work_mode": "remote",
}
SALARY: dict[str, Any] = {"salary_min": 18_000, "salary_max": 24_000, "currency": "PLN"}


def _create(**fields: Any) -> JobOfferCreate:
    return JobOfferCreate.model_validate(REQUIRED | fields)


def _invalid_fields(
    schema: type[JobOfferCreate | JobOfferUpdate], data: dict[str, Any]
) -> set[str]:
    """Validate ``data`` and return the names of the fields that failed."""
    with pytest.raises(ValidationError) as excinfo:
        schema.model_validate(data)
    return {str(error["loc"][0]) for error in excinfo.value.errors() if error["loc"]}


def _changes(data: dict[str, Any]) -> dict[str, Any]:
    """Fields an update with ``data`` would change."""
    return JobOfferUpdate.model_validate(data).model_dump(exclude_unset=True)


# --- JobOfferCreate: required and optional fields ----------------------------------------


def test_create_with_only_the_required_fields() -> None:
    offer = _create()

    assert offer.company_id == uuid.UUID(COMPANY_ID)
    assert offer.source is OfferSource.JUSTJOINIT
    assert offer.seniority is Seniority.MID
    assert offer.work_mode is WorkMode.REMOTE
    assert offer.model_dump(
        include={
            "location",
            "salary_min",
            "salary_max",
            "currency",
            "posted_on",
            "description",
            "notes",
            "tags",
        }
    ) == {
        "location": None,
        "salary_min": None,
        "salary_max": None,
        "currency": None,
        "posted_on": None,
        "description": None,
        "notes": None,
        "tags": [],
    }


@pytest.mark.parametrize(
    "field", ["company_id", "title", "url", "source", "seniority", "work_mode"]
)
def test_create_requires_the_field(field: str) -> None:
    data = {key: value for key, value in REQUIRED.items() if key != field}

    assert _invalid_fields(JobOfferCreate, data) == {field}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "indeed"),
        ("source", "JUSTJOINIT"),
        ("seniority", "principal"),
        ("work_mode", "anywhere"),
        ("company_id", "not-a-uuid"),
    ],
    ids=["unknown-source", "member-name", "seniority", "work-mode", "company-id"],
)
def test_create_rejects_an_invalid_value(field: str, value: str) -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {field: value}) == {field}


@pytest.mark.parametrize("field", ["id", "created_at", "updated_at"])
def test_create_rejects_fields_the_client_must_not_set(field: str) -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {field: "x"}) == {field}


# --- Text ---------------------------------------------------------------------------------


def test_text_is_trimmed() -> None:
    offer = _create(title="  Python Developer  ", location="  Kraków ", notes=" Recruiter: Ola ")

    assert (offer.title, offer.location, offer.notes) == (
        "Python Developer",
        "Kraków",
        "Recruiter: Ola",
    )


@pytest.mark.parametrize("field", ["location", "description", "notes"])
def test_blank_optional_text_becomes_none(field: str) -> None:
    assert getattr(_create(**{field: "   "}), field) is None


def test_blank_title_is_rejected() -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {"title": "   "}) == {"title"}


@pytest.mark.parametrize(
    ("field", "max_length"),
    [("title", 200), ("location", 200), ("description", 20_000), ("notes", 2000)],
)
def test_text_longer_than_the_limit_is_rejected(field: str, max_length: int) -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {field: "x" * (max_length + 1)}) == {field}


@pytest.mark.parametrize(
    ("field", "max_length"),
    [("title", 200), ("location", 200), ("description", 20_000), ("notes", 2000)],
)
def test_text_at_the_limit_is_accepted(field: str, max_length: int) -> None:
    assert len(getattr(_create(**{field: "x" * max_length}), field)) == max_length


# --- URL (D-05) ---------------------------------------------------------------------------


def test_url_is_normalised() -> None:
    offer = _create(url=" HTTPS://JustJoin.IT/job-offer/acme/?utm_source=newsletter#apply ")

    assert offer.url == "https://justjoin.it/job-offer/acme"


@pytest.mark.parametrize(
    "url",
    [
        "http://justjoin.it/job-offer/acme",
        "ftp://acme.com/jobs",
        "justjoin.it/job-offer",
        "https://",
    ],
    ids=["http", "ftp", "no-scheme", "no-host"],
)
def test_url_that_is_not_https_with_a_host_is_rejected(url: str) -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {"url": url}) == {"url"}


def test_url_longer_than_the_limit_is_rejected() -> None:
    url = "https://acme.com/" + "x" * 2048

    assert _invalid_fields(JobOfferCreate, REQUIRED | {"url": url}) == {"url"}


# --- Salary (D-03) ------------------------------------------------------------------------


def test_complete_salary_is_accepted() -> None:
    offer = _create(**SALARY)

    assert (offer.salary_min, offer.salary_max, offer.currency) == (18_000, 24_000, Currency.PLN)


def test_salary_with_one_amount_for_both_bounds_is_accepted() -> None:
    offer = _create(salary_min=20_000, salary_max=20_000, currency="EUR")

    assert offer.salary_min == offer.salary_max == 20_000


@pytest.mark.parametrize(
    "salary",
    [
        {"salary_min": 18_000},
        {"salary_max": 24_000},
        {"currency": "PLN"},
        {"salary_min": 18_000, "salary_max": 24_000},
        {"salary_min": 18_000, "currency": "PLN"},
        {"salary_max": 24_000, "currency": "PLN"},
    ],
    ids=["only-min", "only-max", "only-currency", "no-currency", "no-max", "no-min"],
)
def test_incomplete_salary_is_rejected(salary: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        _create(**salary)


def test_minimum_above_maximum_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must not be greater than"):
        _create(salary_min=25_000, salary_max=20_000, currency="PLN")


@pytest.mark.parametrize("field", ["salary_min", "salary_max"])
@pytest.mark.parametrize("amount", [0, -1])
def test_amount_that_is_not_positive_is_rejected(field: str, amount: int) -> None:
    assert field in _invalid_fields(JobOfferCreate, REQUIRED | SALARY | {field: amount})


@pytest.mark.parametrize("amount", [18_000.5, "18k"])
def test_amount_that_is_not_a_whole_number_is_rejected(amount: object) -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | SALARY | {"salary_min": amount}) == {
        "salary_min"
    }


def test_unknown_currency_is_rejected() -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | SALARY | {"currency": "GBP"}) == {"currency"}


# --- posted_on (D-11) ---------------------------------------------------------------------


def test_posted_on_in_the_past_is_accepted() -> None:
    assert _create(posted_on="2026-10-30").posted_on == date(2026, 10, 30)


def test_posted_on_in_the_future_is_rejected() -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {"posted_on": FUTURE.isoformat()}) == {
        "posted_on"
    }


def test_posted_on_must_be_a_date_without_time() -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {"posted_on": "2026-10-30T12:30:00"}) == {
        "posted_on"
    }


# --- Tags (D-09) --------------------------------------------------------------------------


def test_tags_are_normalised() -> None:
    offer = _create(tags=["FastAPI", "  Machine Learning ", "C++"])

    assert offer.tags == ["fastapi", "machine-learning", "c++"]


def test_duplicate_tags_are_merged_keeping_the_first_occurrence() -> None:
    offer = _create(tags=["FastAPI", "python", "fastapi", " FASTAPI ", "Python"])

    assert offer.tags == ["fastapi", "python"]


def test_invalid_tag_is_rejected() -> None:
    assert _invalid_fields(JobOfferCreate, REQUIRED | {"tags": ["fastapi", "ci/cd"]}) == {"tags"}


def test_at_most_twenty_tags_are_accepted() -> None:
    assert len(_create(tags=[f"tag{n}" for n in range(20)]).tags) == 20


def test_more_than_twenty_tags_are_rejected() -> None:
    tags = [f"tag{n}" for n in range(21)]

    assert _invalid_fields(JobOfferCreate, REQUIRED | {"tags": tags}) == {"tags"}


# --- JobOfferUpdate (PATCH) ---------------------------------------------------------------


def test_empty_update_changes_nothing() -> None:
    assert _changes({}) == {}


def test_update_contains_only_the_fields_sent() -> None:
    assert _changes({"title": "  Senior Python Developer "}) == {"title": "Senior Python Developer"}


@pytest.mark.parametrize("field", ["location", "description", "notes", "posted_on"])
def test_update_with_null_clears_an_optional_field(field: str) -> None:
    assert _changes({field: None}) == {field: None}


@pytest.mark.parametrize("field", ["title", "url", "source", "seniority", "work_mode", "tags"])
def test_update_rejects_null_for_a_field_that_cannot_be_cleared(field: str) -> None:
    assert _invalid_fields(JobOfferUpdate, {field: None}) == {field}


def test_update_cannot_change_the_company() -> None:
    assert _invalid_fields(JobOfferUpdate, {"company_id": COMPANY_ID}) == {"company_id"}


def test_update_normalises_url_and_tags() -> None:
    changes = _changes({"url": "HTTPS://Acme.com/jobs/1/", "tags": ["FastAPI", "fastapi"]})

    assert changes == {"url": "https://acme.com/jobs/1", "tags": ["fastapi"]}


def test_update_with_an_empty_tag_list_removes_all_tags() -> None:
    assert _changes({"tags": []}) == {"tags": []}


def test_update_may_send_only_part_of_the_salary() -> None:
    # Completeness depends on the stored values, so the service checks it after merging.
    assert _changes({"salary_max": 30_000}) == {"salary_max": 30_000}


def test_update_rejects_minimum_above_maximum_when_both_are_sent() -> None:
    with pytest.raises(ValidationError, match="must not be greater than"):
        JobOfferUpdate.model_validate({"salary_min": 25_000, "salary_max": 20_000})


# --- JobOfferRead -------------------------------------------------------------------------


def _stored_offer(**fields: Any) -> SimpleNamespace:
    """An object shaped like a loaded ``JobOffer``: company and tags already loaded."""
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    values: dict[str, Any] = dict(
        id=uuid.uuid4(),
        company_id=uuid.UUID(COMPANY_ID),
        company=SimpleNamespace(
            id=uuid.UUID(COMPANY_ID), name="ACME", is_active=True, notes="internal note"
        ),
        title="Python Developer",
        url="https://justjoin.it/job-offer/acme",
        source=OfferSource.JUSTJOINIT,
        seniority=Seniority.MID_SENIOR,
        work_mode=WorkMode.HYBRID,
        location="Kraków",
        salary_min=18_000,
        salary_max=24_000,
        currency=Currency.PLN,
        posted_on=date(2026, 10, 30),
        description=None,
        notes=None,
        tags=[SimpleNamespace(name="fastapi"), SimpleNamespace(name="python")],
        created_at=now,
        updated_at=now,
    )
    return SimpleNamespace(**(values | fields))


def test_read_returns_tag_names_from_the_model() -> None:
    read = JobOfferRead.model_validate(_stored_offer())

    assert read.tags == ["fastapi", "python"]
    assert read.model_dump(mode="json")["seniority"] == "mid_senior"
    assert set(read.model_dump()) == {
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


def test_read_carries_a_summary_of_the_company() -> None:
    # D-21: enough to show the company without a second request, nothing more.
    read = JobOfferRead.model_validate(_stored_offer())

    assert read.model_dump(mode="json")["company"] == {
        "id": COMPANY_ID,
        "name": "ACME",
        "is_active": True,
    }


def test_read_sorts_tag_names() -> None:
    tags = [SimpleNamespace(name="python"), SimpleNamespace(name="aws")]

    assert JobOfferRead.model_validate(_stored_offer(tags=tags)).tags == ["aws", "python"]
