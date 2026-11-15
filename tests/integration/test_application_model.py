"""The ``applications`` table as created by the migrations (decisions: "Application").

Each test runs on its own database cloned from the migrated template (D-12), so these
tests check the migration and the model together. Rules the database must enforce on its
own, also for rows written with plain SQL, are tested with ``INSERT`` statements: the
status and currency ``CHECK`` constraints (D-02, D-16), no sent date for a draft, the
expected salary all or nothing (D-03), one active application per offer (D-06) and the
foreign key to ``job_offers`` with ``ON DELETE CASCADE`` (D-04).
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
from job_tracker.enums import ApplicationStatus, Currency, OfferSource, Seniority, WorkMode
from job_tracker.models import Application, Company, JobOffer

pytestmark: pytest.MarkDecorator = pytest.mark.integration

ONE_ACTIVE_PER_OFFER: str = "uq_applications_active_job_offer_id"
OFFER_FOREIGN_KEY: str = "fk_applications_job_offer_id_job_offers"
DRAFT_NOT_SENT: str = "ck_applications_draft_not_sent"
EXPECTED_SALARY: str = "ck_applications_expected_salary"
STRING_TOO_LONG: str = "22001"  # PostgreSQL error code string_data_right_truncation
OMITTED: object = object()  # Marks a column left out of a raw INSERT.

ACTIVE: list[ApplicationStatus] = [s for s in ApplicationStatus if not s.is_final]
FINAL: list[ApplicationStatus] = ApplicationStatus.final()


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


async def _new_offer(session: AsyncSession, slug: str = "python-developer") -> JobOffer:
    """A committed offer of a committed company."""
    company = Company(name=f"ACME {slug}")
    session.add(company)
    await session.flush()
    offer = JobOffer(
        company_id=company.id,
        title="Python Developer",
        url=f"https://justjoin.it/offers/{slug}",
        source=OfferSource.JUSTJOINIT,
        seniority=Seniority.MID,
        work_mode=WorkMode.REMOTE,
    )
    session.add(offer)
    await session.commit()
    return offer


@pytest.fixture
async def offer(session: AsyncSession) -> JobOffer:
    """A committed offer the applications belong to."""
    return await _new_offer(session)


def _application(offer: JobOffer, **fields: Any) -> Application:
    """A valid application with only the required field, overridden by ``fields``."""
    return Application(**({"job_offer_id": offer.id} | fields))


async def _insert_raw(session: AsyncSession, offer: JobOffer, **overrides: object) -> None:
    """Insert an application with plain SQL, bypassing the model and its Python types.

    Columns default to valid values; ``overrides`` replaces them, and ``OMITTED`` leaves a
    column out of the statement.
    """
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "job_offer_id": offer.id,
        "status": "applied",
    } | overrides
    values = {column: value for column, value in values.items() if value is not OMITTED}
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    # Column names come from this test module only, never from outside input.
    await session.execute(
        text(f"INSERT INTO applications ({columns}) VALUES ({placeholders})"),  # noqa: S608
        values,
    )


async def _count(session: AsyncSession) -> int:
    """Number of applications visible in ``session``."""
    count: int = await session.scalar(text("SELECT count(*) FROM applications"))
    return count


# --- Defaults and types ------------------------------------------------------------------


async def test_new_application_gets_id_timestamps_and_applied_status(
    session: AsyncSession, offer: JobOffer
) -> None:
    application = _application(offer)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    assert isinstance(application.id, uuid.UUID)
    assert application.created_at.tzinfo is not None
    assert application.updated_at.tzinfo is not None
    assert application.status is ApplicationStatus.APPLIED


async def test_optional_fields_default_to_null(session: AsyncSession, offer: JobOffer) -> None:
    application = _application(offer)
    session.add(application)
    await session.commit()
    await session.refresh(application)

    assert (
        application.sent_on,
        application.expected_salary,
        application.currency,
        application.notes,
    ) == (None, None, None, None)


async def test_all_fields_are_stored_and_read_back(session: AsyncSession, offer: JobOffer) -> None:
    application = _application(
        offer,
        status=ApplicationStatus.TECHNICAL,
        sent_on=date(2026, 11, 2),
        expected_salary=22_000,
        currency=Currency.PLN,
        notes="Referred by Ola",
    )
    session.add(application)
    await session.commit()
    session.expunge_all()

    stored = await session.get(Application, application.id)

    assert stored is not None
    assert stored.job_offer_id == offer.id
    assert stored.status is ApplicationStatus.TECHNICAL
    assert stored.sent_on == date(2026, 11, 2)
    assert (stored.expected_salary, stored.currency) == (22_000, Currency.PLN)
    assert stored.notes == "Referred by Ola"


async def test_enumerations_are_stored_as_their_values(
    session: AsyncSession, offer: JobOffer
) -> None:
    # D-02: the database holds the values ("on_hold"), not the member names ("ON_HOLD").
    session.add(
        _application(
            offer, status=ApplicationStatus.ON_HOLD, expected_salary=1, currency=Currency.EUR
        )
    )
    await session.commit()

    row = (await session.execute(text("SELECT status, currency FROM applications"))).one()

    assert tuple(row) == ("on_hold", "EUR")


# --- Enumerations: CHECK constraints (D-02, D-16) ----------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [("status", "interview"), ("status", "ON_HOLD"), ("currency", "GBP")],
    ids=["unknown-status", "member-name-instead-of-value", "currency"],
)
async def test_database_rejects_a_value_outside_the_enumeration(
    session: AsyncSession, offer: JobOffer, column: str, value: str
) -> None:
    salary = {"expected_salary": 1} if column == "currency" else {}

    with pytest.raises(IntegrityError):
        await _insert_raw(session, offer, **salary, **{column: value})


# --- Required columns --------------------------------------------------------------------


@pytest.mark.parametrize("column", ["job_offer_id", "status"])
async def test_required_column_must_be_set(
    session: AsyncSession, offer: JobOffer, column: str
) -> None:
    with pytest.raises(IntegrityError):
        await _insert_raw(session, offer, **{column: OMITTED})


# --- Sent date: a draft has none ---------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "draft"},
        {"status": "applied"},
        {"status": "applied", "sent_on": date(2026, 11, 2)},
        {"status": "rejected", "sent_on": date(2026, 1, 15)},
    ],
    ids=["draft", "sent-date-unknown", "sent", "past-application"],
)
async def test_sent_date_is_optional_except_for_a_draft(
    session: AsyncSession, offer: JobOffer, fields: dict[str, object]
) -> None:
    await _insert_raw(session, offer, **fields)
    await session.commit()

    assert await _count(session) == 1


async def test_draft_with_a_sent_date_is_rejected(session: AsyncSession, offer: JobOffer) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        await _insert_raw(session, offer, status="draft", sent_on=date(2026, 11, 2))

    assert violated_constraint(excinfo.value) == DRAFT_NOT_SENT


# --- Expected salary: all or nothing, positive (D-03) ------------------------------------


@pytest.mark.parametrize(
    "salary",
    [{}, {"expected_salary": 22_000, "currency": "PLN"}],
    ids=["no-salary", "amount-with-currency"],
)
async def test_complete_expected_salary_or_none_is_accepted(
    session: AsyncSession, offer: JobOffer, salary: dict[str, object]
) -> None:
    await _insert_raw(session, offer, **salary)
    await session.commit()

    assert await _count(session) == 1


@pytest.mark.parametrize(
    "salary",
    [
        {"expected_salary": 22_000},
        {"currency": "PLN"},
        {"expected_salary": 0, "currency": "PLN"},
        {"expected_salary": -5, "currency": "PLN"},
    ],
    ids=["amount-without-currency", "currency-without-amount", "zero", "negative"],
)
async def test_incomplete_or_invalid_expected_salary_is_rejected(
    session: AsyncSession, offer: JobOffer, salary: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        await _insert_raw(session, offer, **salary)

    assert violated_constraint(excinfo.value) == EXPECTED_SALARY


# --- One active application per offer (D-06, D-16) ---------------------------------------


@pytest.mark.parametrize("active", ACTIVE, ids=str)
async def test_second_active_application_to_an_offer_is_rejected(
    session: AsyncSession, offer: JobOffer, active: ApplicationStatus
) -> None:
    await _insert_raw(session, offer, status="applied")

    with pytest.raises(IntegrityError) as excinfo:
        await _insert_raw(session, offer, status=active.value)

    # The service maps this name to 409 application_already_active.
    assert violated_constraint(excinfo.value) == ONE_ACTIVE_PER_OFFER


@pytest.mark.parametrize("final", FINAL, ids=str)
async def test_offer_can_be_applied_to_again_after_a_final_status(
    session: AsyncSession, offer: JobOffer, final: ApplicationStatus
) -> None:
    await _insert_raw(session, offer, status=final.value)
    await _insert_raw(session, offer, status="applied")
    await session.commit()

    assert await _count(session) == 2


async def test_an_offer_can_have_many_finished_applications(
    session: AsyncSession, offer: JobOffer
) -> None:
    for status in ("rejected", "rejected", "ghosted"):
        await _insert_raw(session, offer, status=status)
    await session.commit()

    assert await _count(session) == 3


async def test_different_offers_can_each_have_an_active_application(
    session: AsyncSession, offer: JobOffer
) -> None:
    other = await _new_offer(session, slug="backend-developer")

    await _insert_raw(session, offer, status="applied")
    await _insert_raw(session, other, status="applied")
    await session.commit()

    assert await _count(session) == 2


# --- Offer (D-04) ------------------------------------------------------------------------


async def test_application_to_an_unknown_offer_is_rejected(
    session: AsyncSession, offer: JobOffer
) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        await _insert_raw(session, offer, job_offer_id=uuid.uuid4())

    assert violated_constraint(excinfo.value) == OFFER_FOREIGN_KEY


async def test_deleting_an_offer_deletes_its_applications(
    session: AsyncSession, offer: JobOffer
) -> None:
    await _insert_raw(session, offer, status="rejected")
    await _insert_raw(session, offer, status="applied")
    await session.commit()

    await session.execute(text("DELETE FROM job_offers WHERE id = :id"), {"id": offer.id})
    await session.commit()

    assert await _count(session) == 0


# --- Text limits -------------------------------------------------------------------------


async def test_notes_longer_than_the_limit_are_rejected(
    session: AsyncSession, offer: JobOffer
) -> None:
    session.add(_application(offer, notes="x" * 2001))

    # asyncpg errors arrive as the generic DBAPIError; the code is on the original error.
    with pytest.raises(DBAPIError) as excinfo:
        await session.flush()

    assert excinfo.value.orig is not None
    assert getattr(excinfo.value.orig.__cause__, "sqlstate", None) == STRING_TOO_LONG


async def test_notes_at_the_limit_are_accepted(session: AsyncSession, offer: JobOffer) -> None:
    session.add(_application(offer, notes="x" * 2000))
    await session.commit()

    assert await _count(session) == 1
