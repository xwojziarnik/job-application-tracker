"""Request and response schemas of a company (decisions: "Company").

- Text is trimmed; blank text in an optional field becomes ``None``.
- ``website`` must be an ``https`` URL and is kept as entered (trimmed).
- Unknown fields are rejected, so a client cannot set ``id``, ``is_active`` on creation
  or the timestamps.
- In an update, an omitted field is not set at all (``exclude_unset``), ``None`` clears an
  optional field, and ``None`` for ``name`` or ``is_active`` is rejected.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from job_tracker.models import Company
from job_tracker.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate

OPTIONAL_TEXT_LIMITS = [("location", 200), ("industry", 100), ("notes", 2000)]


def _invalid_fields(schema: type[CompanyCreate | CompanyUpdate], data: dict[str, Any]) -> set[str]:
    """Validate ``data`` and return the names of the fields that failed."""
    with pytest.raises(ValidationError) as excinfo:
        schema.model_validate(data)
    return {str(error["loc"][0]) for error in excinfo.value.errors()}


def _changes(data: dict[str, Any]) -> dict[str, Any]:
    """Fields an update with ``data`` would change."""
    return CompanyUpdate.model_validate(data).model_dump(exclude_unset=True)


# --- CompanyCreate -----------------------------------------------------------------------


def test_create_needs_only_a_name() -> None:
    company = CompanyCreate.model_validate({"name": "ACME"})

    assert company.model_dump() == {
        "name": "ACME",
        "website": None,
        "location": None,
        "industry": None,
        "notes": None,
    }


def test_create_requires_a_name() -> None:
    assert _invalid_fields(CompanyCreate, {}) == {"name"}


def test_name_is_trimmed() -> None:
    assert CompanyCreate.model_validate({"name": "  ACME  "}).name == "ACME"


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_is_rejected(name: str) -> None:
    assert _invalid_fields(CompanyCreate, {"name": name}) == {"name"}


def test_name_of_200_characters_is_accepted() -> None:
    assert len(CompanyCreate.model_validate({"name": "x" * 200}).name) == 200


def test_name_longer_than_200_characters_is_rejected() -> None:
    assert _invalid_fields(CompanyCreate, {"name": "x" * 201}) == {"name"}


@pytest.mark.parametrize(("field", "_limit"), OPTIONAL_TEXT_LIMITS)
def test_optional_text_is_trimmed(field: str, _limit: int) -> None:
    company = CompanyCreate.model_validate({"name": "ACME", field: "  value  "})

    assert getattr(company, field) == "value"


@pytest.mark.parametrize(("field", "_limit"), [*OPTIONAL_TEXT_LIMITS, ("website", 2048)])
@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_optional_text_becomes_none(field: str, _limit: int, blank: str) -> None:
    company = CompanyCreate.model_validate({"name": "ACME", field: blank})

    assert getattr(company, field) is None


@pytest.mark.parametrize(("field", "limit"), OPTIONAL_TEXT_LIMITS)
def test_optional_text_longer_than_the_limit_is_rejected(field: str, limit: int) -> None:
    assert _invalid_fields(CompanyCreate, {"name": "ACME", field: "x" * (limit + 1)}) == {field}


@pytest.mark.parametrize(
    "website", ["https://acme.com", "https://acme.com/careers?team=backend", "https://acme.com/"]
)
def test_website_is_kept_as_entered(website: str) -> None:
    assert CompanyCreate.model_validate({"name": "ACME", "website": website}).website == website


def test_website_is_trimmed() -> None:
    company = CompanyCreate.model_validate({"name": "ACME", "website": "  https://acme.com  "})

    assert company.website == "https://acme.com"


@pytest.mark.parametrize(
    "website", ["http://acme.com", "acme.com", "ftp://acme.com", "not a url", "https://"]
)
def test_website_must_be_an_https_url(website: str) -> None:
    assert _invalid_fields(CompanyCreate, {"name": "ACME", "website": website}) == {"website"}


def test_website_longer_than_2048_characters_is_rejected() -> None:
    website = "https://acme.com/" + "x" * 2032

    assert len(website) == 2049
    assert _invalid_fields(CompanyCreate, {"name": "ACME", "website": website}) == {"website"}


@pytest.mark.parametrize("field", ["is_active", "id", "created_at", "updated_at", "unknown_field"])
def test_create_rejects_fields_it_does_not_accept(field: str) -> None:
    assert _invalid_fields(CompanyCreate, {"name": "ACME", field: "value"}) == {field}


# --- CompanyUpdate -----------------------------------------------------------------------


def test_empty_update_changes_nothing() -> None:
    assert _changes({}) == {}


def test_update_changes_only_the_given_fields() -> None:
    assert _changes({"industry": "fintech", "is_active": False}) == {
        "industry": "fintech",
        "is_active": False,
    }


def test_update_trims_the_name() -> None:
    assert _changes({"name": "  ACME Labs "}) == {"name": "ACME Labs"}


@pytest.mark.parametrize("field", ["website", "location", "industry", "notes"])
@pytest.mark.parametrize("empty", [None, "", "  "])
def test_null_or_blank_clears_an_optional_field(field: str, empty: str | None) -> None:
    assert _changes({field: empty}) == {field: None}


@pytest.mark.parametrize("field", ["name", "is_active"])
def test_null_is_rejected_for_required_fields(field: str) -> None:
    assert _invalid_fields(CompanyUpdate, {field: None}) == {field}


def test_update_rejects_a_blank_name() -> None:
    assert _invalid_fields(CompanyUpdate, {"name": "  "}) == {"name"}


def test_update_validates_the_website() -> None:
    assert _invalid_fields(CompanyUpdate, {"website": "http://acme.com"}) == {"website"}


@pytest.mark.parametrize("field", ["id", "created_at", "updated_at", "unknown_field"])
def test_update_rejects_fields_it_does_not_accept(field: str) -> None:
    assert _invalid_fields(CompanyUpdate, {field: "value"}) == {field}


# --- CompanyRead -------------------------------------------------------------------------


def test_read_is_built_from_the_model() -> None:
    now = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)
    company = Company(
        id=uuid.uuid4(),
        name="ACME",
        website="https://acme.com",
        location="Warsaw, Poland",
        industry=None,
        notes=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    read = CompanyRead.model_validate(company)

    assert read.model_dump() == {
        "id": company.id,
        "name": "ACME",
        "website": "https://acme.com",
        "location": "Warsaw, Poland",
        "industry": None,
        "notes": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def test_read_does_not_validate_stored_values_again() -> None:
    # A value stored before a rule was tightened (or inserted with SQL) must still be
    # readable: the response schema returns data, it does not validate input.
    now = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)
    company = Company(
        id=uuid.uuid4(),
        name="ACME",
        website="http://acme.com",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    assert CompanyRead.model_validate(company).website == "http://acme.com"
