"""The ``job_offers`` table as created by the migrations (decisions: "Job offer").

Each test runs on its own database cloned from the migrated template (D-12), so these
tests check the migration and the model together. Rules that the database must enforce on
its own, also for rows written with plain SQL, are tested with ``INSERT`` statements: the
``CHECK`` constraints of the enumerations (D-02), the salary rule (D-03), the unique URL
(D-05) and the foreign key to ``companies`` (D-04).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from job_tracker.db.errors import violated_constraint
from job_tracker.enums import Currency, OfferSource, Seniority, WorkMode
from job_tracker.models import Company, JobOffer

pytestmark = pytest.mark.integration

UNIQUE_URL = "uq_job_offers_url"
COMPANY_FOREIGN_KEY = "fk_job_offers_company_id_companies"
STRING_TOO_LONG = "22001"  # PostgreSQL error code string_data_right_truncation
OMITTED = object()  # Marks a column left out of a raw INSERT.


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for this test's migrated database, disposed so the database can be dropped."""
    engine = create_async_engine(make_url(test_db_url))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session on this test's migrated database."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
async def company(session: AsyncSession) -> Company:
    """A committed company the offers belong to."""
    company = Company(name="ACME")
    session.add(company)
    await session.commit()
    return company


def _offer(company: Company, **fields: Any) -> JobOffer:
    """A valid offer with only the required fields, overridden by ``fields``."""
    values: dict[str, Any] = {
        "company_id": company.id,
        "title": "Python Developer",
        "url": "https://justjoin.it/offers/acme-python-developer",
        "source": OfferSource.JUSTJOINIT,
        "seniority": Seniority.MID,
        "work_mode": WorkMode.REMOTE,
    }
    return JobOffer(**(values | fields))


async def _insert_raw(session: AsyncSession, company: Company, **overrides: object) -> None:
    """Insert an offer with plain SQL, bypassing the model and its Python types.

    Columns default to valid values; ``overrides`` replaces them, and ``OMITTED`` leaves a
    column out of the statement.
    """
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "company_id": company.id,
        "title": "Python Developer",
        "url": f"https://justjoin.it/offers/{uuid.uuid4().hex}",
        "source": "justjoinit",
        "seniority": "mid",
        "work_mode": "remote",
    } | overrides
    values = {column: value for column, value in values.items() if value is not OMITTED}
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    # Column names come from this test module only, never from outside input.
    await session.execute(
        text(f"INSERT INTO job_offers ({columns}) VALUES ({placeholders})"),  # noqa: S608
        values,
    )


# --- Defaults and types ------------------------------------------------------------------


async def test_new_offer_gets_id_and_timestamps(session: AsyncSession, company: Company) -> None:
    offer = _offer(company)
    session.add(offer)
    await session.commit()
    await session.refresh(offer)

    assert isinstance(offer.id, uuid.UUID)
    assert offer.created_at.tzinfo is not None
    assert offer.updated_at.tzinfo is not None


async def test_optional_fields_default_to_null(session: AsyncSession, company: Company) -> None:
    offer = _offer(company)
    session.add(offer)
    await session.commit()
    await session.refresh(offer)

    assert (
        offer.location,
        offer.salary_min,
        offer.salary_max,
        offer.currency,
        offer.posted_on,
        offer.description,
        offer.notes,
    ) == (None, None, None, None, None, None, None)


async def test_all_fields_are_stored_and_read_back(session: AsyncSession, company: Company) -> None:
    offer = _offer(
        company,
        seniority=Seniority.MID_SENIOR,
        work_mode=WorkMode.HYBRID,
        location="Kraków",
        salary_min=18_000,
        salary_max=24_000,
        currency=Currency.PLN,
        posted_on=date(2026, 10, 30),
        description="We are looking for a Python developer.",
        notes="Recruiter: Ola",
    )
    session.add(offer)
    await session.commit()
    session.expunge_all()

    stored = await session.get(JobOffer, offer.id)

    assert stored is not None
    assert stored.company_id == company.id
    assert stored.source is OfferSource.JUSTJOINIT
    assert stored.seniority is Seniority.MID_SENIOR
    assert stored.work_mode is WorkMode.HYBRID
    assert stored.currency is Currency.PLN
    assert (stored.salary_min, stored.salary_max) == (18_000, 24_000)
    assert stored.posted_on == date(2026, 10, 30)
    assert stored.location == "Kraków"


async def test_enumerations_are_stored_as_their_values(
    session: AsyncSession, company: Company
) -> None:
    # D-02: the database holds the values ("mid_senior"), not the member names
    # ("MID_SENIOR"), so SQL, the API and the code use the same strings.
    session.add(
        _offer(
            company,
            seniority=Seniority.MID_SENIOR,
            salary_min=1,
            salary_max=2,
            currency=Currency.EUR,
        )
    )
    await session.commit()

    row = (
        await session.execute(text("SELECT source, seniority, work_mode, currency FROM job_offers"))
    ).one()

    assert tuple(row) == ("justjoinit", "mid_senior", "remote", "EUR")


# --- Enumerations: CHECK constraints (D-02) ----------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("source", "indeed"),
        ("source", "JUSTJOINIT"),
        ("seniority", "principal"),
        ("work_mode", "anywhere"),
        ("currency", "GBP"),
    ],
    ids=["unknown-source", "member-name-instead-of-value", "seniority", "work-mode", "currency"],
)
async def test_database_rejects_a_value_outside_the_enumeration(
    session: AsyncSession, company: Company, column: str, value: str
) -> None:
    salary = {"salary_min": 1, "salary_max": 2} if column == "currency" else {}

    with pytest.raises(IntegrityError):
        await _insert_raw(session, company, **salary, **{column: value})


# --- Required columns --------------------------------------------------------------------


@pytest.mark.parametrize(
    "column", ["company_id", "title", "url", "source", "seniority", "work_mode"]
)
async def test_required_column_must_be_set(
    session: AsyncSession, company: Company, column: str
) -> None:
    with pytest.raises(IntegrityError):
        await _insert_raw(session, company, **{column: OMITTED})


# --- Salary: all or nothing, positive, ordered (D-03) ------------------------------------


@pytest.mark.parametrize(
    "salary",
    [
        {},
        {"salary_min": 20_000, "salary_max": 25_000, "currency": "PLN"},
        {"salary_min": 20_000, "salary_max": 20_000, "currency": "USD"},
    ],
    ids=["no-salary", "range", "single-amount"],
)
async def test_complete_salary_or_none_is_accepted(
    session: AsyncSession, company: Company, salary: dict[str, object]
) -> None:
    await _insert_raw(session, company, **salary)
    await session.commit()

    assert await session.scalar(text("SELECT count(*) FROM job_offers")) == 1


@pytest.mark.parametrize(
    "salary",
    [
        {"salary_min": 20_000},
        {"salary_max": 25_000},
        {"currency": "PLN"},
        {"salary_min": 20_000, "salary_max": 25_000},
        {"salary_min": 20_000, "currency": "PLN"},
        {"salary_min": 25_000, "salary_max": 20_000, "currency": "PLN"},
        {"salary_min": 0, "salary_max": 20_000, "currency": "PLN"},
        {"salary_min": -5, "salary_max": 20_000, "currency": "PLN"},
    ],
    ids=[
        "only-min",
        "only-max",
        "only-currency",
        "range-without-currency",
        "min-and-currency",
        "min-above-max",
        "zero",
        "negative",
    ],
)
async def test_incomplete_or_invalid_salary_is_rejected(
    session: AsyncSession, company: Company, salary: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        await _insert_raw(session, company, **salary)


# --- URL (D-05) ---------------------------------------------------------------------------


async def test_the_same_url_cannot_be_stored_twice(session: AsyncSession, company: Company) -> None:
    url = "https://justjoin.it/offers/acme-python-developer"
    session.add(_offer(company, url=url))
    await session.flush()

    session.add(_offer(company, url=url, title="Another title"))
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()

    # The service maps this name to 409 Conflict (D-07).
    assert violated_constraint(excinfo.value) == UNIQUE_URL


# --- Company (D-04) ----------------------------------------------------------------------


async def test_offer_of_an_unknown_company_is_rejected(
    session: AsyncSession, company: Company
) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        await _insert_raw(session, company, company_id=uuid.uuid4())

    assert violated_constraint(excinfo.value) == COMPANY_FOREIGN_KEY


async def test_company_with_offers_cannot_be_deleted(
    session: AsyncSession, company: Company
) -> None:
    # Companies are deactivated, never deleted; RESTRICT keeps their offers even if a
    # company row is deleted with plain SQL by mistake.
    session.add(_offer(company))
    await session.commit()

    with pytest.raises(IntegrityError) as excinfo:
        await session.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company.id})

    assert violated_constraint(excinfo.value) == COMPANY_FOREIGN_KEY


async def test_company_without_offers_can_still_be_deleted_with_sql(
    session: AsyncSession, company: Company
) -> None:
    # RESTRICT blocks only companies that have offers.
    await session.execute(text("DELETE FROM companies WHERE id = :id"), {"id": company.id})
    await session.commit()

    assert await session.scalar(text("SELECT count(*) FROM companies")) == 0


# --- Text limits -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "max_length"),
    [
        ("title", 200),
        ("url", 2048),
        ("location", 200),
        ("description", 20_000),
        ("notes", 2000),
    ],
)
async def test_text_longer_than_the_limit_is_rejected(
    session: AsyncSession, company: Company, field: str, max_length: int
) -> None:
    session.add(_offer(company, **{field: "x" * (max_length + 1)}))

    # SQLAlchemy's asyncpg adapter maps this error to the generic DBAPIError, so the
    # PostgreSQL error code is checked on the original asyncpg exception (see db/errors.py).
    with pytest.raises(DBAPIError) as excinfo:
        await session.flush()

    assert excinfo.value.orig is not None
    assert getattr(excinfo.value.orig.__cause__, "sqlstate", None) == STRING_TOO_LONG


@pytest.mark.parametrize(
    ("field", "max_length"),
    [("title", 200), ("url", 2048), ("location", 200), ("description", 20_000), ("notes", 2000)],
)
async def test_text_at_the_limit_is_accepted(
    session: AsyncSession, company: Company, field: str, max_length: int
) -> None:
    session.add(_offer(company, **{field: "x" * max_length}))
    await session.commit()

    assert await session.scalar(text("SELECT count(*) FROM job_offers")) == 1
