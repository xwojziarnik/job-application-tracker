"""The ``companies`` table as created by the migrations (decisions: "Company").

Each test runs on its own database cloned from the migrated template (D-12), so these
tests check the migration and the model together.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from job_tracker.db.errors import violated_constraint
from job_tracker.models import Base, Company

pytestmark = pytest.mark.integration

UNIQUE_NAME_INDEX = "uq_companies_lower_name"
STRING_TOO_LONG = "22001"  # PostgreSQL error code string_data_right_truncation


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


async def test_new_company_gets_id_timestamps_and_is_active(session: AsyncSession) -> None:
    company = Company(name="ACME")
    session.add(company)
    await session.commit()
    await session.refresh(company)

    assert isinstance(company.id, uuid.UUID)
    assert company.is_active is True
    assert company.created_at.tzinfo is not None
    assert company.updated_at.tzinfo is not None


async def test_optional_fields_default_to_null(session: AsyncSession) -> None:
    company = Company(name="ACME")
    session.add(company)
    await session.commit()
    await session.refresh(company)

    assert (company.website, company.location, company.industry, company.notes) == (
        None,
        None,
        None,
        None,
    )


async def test_database_defaults_apply_to_rows_inserted_with_sql(session: AsyncSession) -> None:
    # is_active and the timestamps come from the database, not only from the ORM.
    await session.execute(
        text("INSERT INTO companies (id, name) VALUES (:id, 'ACME')"), {"id": uuid.uuid4()}
    )

    row = (
        await session.execute(text("SELECT is_active, created_at, updated_at FROM companies"))
    ).one()

    assert row.is_active is True
    assert row.created_at is not None
    assert row.updated_at is not None


async def test_names_differing_only_in_case_are_duplicates(session: AsyncSession) -> None:
    session.add(Company(name="ACME"))
    await session.flush()

    session.add(Company(name="acme"))
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()

    assert violated_constraint(excinfo.value) == UNIQUE_NAME_INDEX


async def test_different_names_are_allowed(session: AsyncSession) -> None:
    session.add_all([Company(name="ACME"), Company(name="ACME Labs")])
    await session.commit()

    names = (await session.scalars(select(Company.name).order_by(Company.name))).all()

    assert names == ["ACME", "ACME Labs"]


@pytest.mark.parametrize(
    ("field", "max_length"),
    [("name", 200), ("website", 2048), ("location", 200), ("industry", 100), ("notes", 2000)],
)
async def test_text_longer_than_the_limit_is_rejected(
    session: AsyncSession, field: str, max_length: int
) -> None:
    values = {"name": "ACME", field: "x" * (max_length + 1)}
    session.add(Company(**values))

    # SQLAlchemy's asyncpg adapter maps this error to the generic DBAPIError, so the
    # PostgreSQL error code is checked on the original asyncpg exception (see db/errors.py).
    with pytest.raises(DBAPIError) as excinfo:
        await session.flush()

    assert excinfo.value.orig is not None
    assert getattr(excinfo.value.orig.__cause__, "sqlstate", None) == STRING_TOO_LONG


async def test_name_is_required(session: AsyncSession) -> None:
    session.add(Company(name=None))

    with pytest.raises(IntegrityError):
        await session.flush()


def _differences(connection: Connection) -> list[object]:
    """Differences between the models and the migrated schema, as Alembic sees them."""
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


async def test_migrations_match_the_models(engine: AsyncEngine) -> None:
    # Fails when a model changes without a migration (or the other way round).
    async with engine.connect() as conn:
        differences = await conn.run_sync(_differences)

    assert differences == []
