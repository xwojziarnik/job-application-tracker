"""Turning database constraint violations into domain errors (D-07).

Services flush before committing, so the database checks its constraints while the
service can still react: ``violated_constraint`` tells which constraint failed, so the
service can raise a matching domain error (e.g. ``ConflictError`` for a duplicate name).
Each test uses throwaway tables in its own database (D-12), named with the application's
naming convention, so the constraint names are the ones real models will have.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, MetaData, String, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from job_tracker.db.base import NAMING_CONVENTION, UUIDPrimaryKeyMixin
from job_tracker.db.errors import violated_constraint

pytestmark = pytest.mark.integration


class ScratchBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Thing(UUIDPrimaryKeyMixin, ScratchBase):
    __tablename__ = "things"
    __table_args__ = (CheckConstraint("quantity > 0", name="positive_quantity"),)

    name: Mapped[str] = mapped_column(String(50), unique=True)
    quantity: Mapped[int] = mapped_column(default=1)


class Part(UUIDPrimaryKeyMixin, ScratchBase):
    __tablename__ = "parts"

    thing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("things.id"))
    label: Mapped[str] = mapped_column(String(50))


@pytest.fixture
async def session(test_db_url: str) -> AsyncIterator[AsyncSession]:
    """Session on this test's database with the scratch tables created."""
    engine = create_async_engine(make_url(test_db_url))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(ScratchBase.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        # Close every connection, or the test database cannot be dropped.
        await engine.dispose()


async def _flush_error(session: AsyncSession, *objects: object) -> IntegrityError:
    """Add ``objects``, flush, and return the ``IntegrityError`` the flush raises."""
    session.add_all(objects)
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()
    await session.rollback()
    return excinfo.value


async def _count_things(session: AsyncSession) -> int | None:
    """Number of rows in ``things``."""
    return await session.scalar(select(func.count()).select_from(Thing))


async def test_unique_violation_names_the_unique_constraint(session: AsyncSession) -> None:
    error = await _flush_error(session, Thing(name="keyboard"), Thing(name="keyboard"))

    assert violated_constraint(error) == "uq_things_name"


async def test_check_violation_names_the_check_constraint(session: AsyncSession) -> None:
    error = await _flush_error(session, Thing(name="keyboard", quantity=0))

    assert violated_constraint(error) == "ck_things_positive_quantity"


async def test_foreign_key_violation_names_the_foreign_key(session: AsyncSession) -> None:
    error = await _flush_error(session, Part(thing_id=uuid.uuid4(), label="key"))

    assert violated_constraint(error) == "fk_parts_thing_id_things"


async def test_not_null_violation_has_no_constraint_name(session: AsyncSession) -> None:
    error = await _flush_error(session, Thing(name=None))

    assert violated_constraint(error) is None


async def test_session_is_usable_after_rolling_back_a_failed_flush(
    session: AsyncSession,
) -> None:
    # A failed flush leaves the transaction unusable until it is rolled back (D-07).
    await _flush_error(session, Thing(name="keyboard"), Thing(name="keyboard"))

    session.add(Thing(name="mouse"))
    await session.commit()

    assert await _count_things(session) == 1


async def test_savepoint_keeps_earlier_changes_of_the_transaction(
    session: AsyncSession,
) -> None:
    # The pattern for "insert, or use the existing row" (D-10): only the savepoint is
    # rolled back, the rest of the use case's transaction survives.
    session.add(Thing(name="keyboard"))
    await session.flush()

    with pytest.raises(IntegrityError) as excinfo:
        async with session.begin_nested():
            session.add(Thing(name="keyboard"))
    await session.commit()

    assert violated_constraint(excinfo.value) == "uq_things_name"
    assert await _count_things(session) == 1
