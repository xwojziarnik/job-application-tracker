"""``UUIDPrimaryKeyMixin`` against a real PostgreSQL database (D-01).

Each test creates a throwaway table in its own database (D-12), so nothing has to be
cleaned up and the application's migrations are not involved.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import String, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from job_tracker.db.base import UUIDPrimaryKeyMixin

pytestmark = pytest.mark.integration


class ScratchBase(DeclarativeBase):
    pass


class Thing(UUIDPrimaryKeyMixin, ScratchBase):
    __tablename__ = "things"

    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
async def session(test_db_url: str) -> AsyncIterator[AsyncSession]:
    """Session on this test's database with the ``things`` table created."""
    engine = create_async_engine(make_url(test_db_url))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(ScratchBase.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        # Close every connection, or the test database cannot be dropped.
        await engine.dispose()


async def test_ids_are_generated_on_flush_as_distinct_uuid4(session: AsyncSession) -> None:
    first, second = Thing(name="first"), Thing(name="second")
    session.add_all([first, second])
    await session.flush()

    assert isinstance(first.id, uuid.UUID)
    assert first.id.version == 4
    assert second.id.version == 4
    assert first.id != second.id


async def test_id_survives_a_round_trip(session: AsyncSession) -> None:
    thing = Thing(name="keyboard")
    session.add(thing)
    await session.commit()
    session.expunge_all()

    loaded = await session.scalar(select(Thing).where(Thing.id == thing.id))

    assert loaded is not None
    assert loaded.id == thing.id
    assert loaded.name == "keyboard"


async def test_explicit_id_is_kept(session: AsyncSession) -> None:
    explicit = uuid.uuid4()
    session.add(Thing(id=explicit, name="imported"))
    await session.commit()

    stored = await session.scalar(select(Thing.id).where(Thing.name == "imported"))

    assert stored == explicit


async def test_id_column_is_stored_as_native_uuid(session: AsyncSession) -> None:
    data_type = await session.scalar(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'things' AND column_name = 'id'"
        )
    )

    assert data_type == "uuid"
