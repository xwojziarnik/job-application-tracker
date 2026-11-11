"""The schema created by the migrations, as a whole.

- Every foreign key is indexed: PostgreSQL does not index the referencing columns on its
  own, and without an index filtering by the parent (offers of a company, offers with a
  tag) and the ``RESTRICT``/``CASCADE`` checks on delete scan the whole table.
- The migrations create exactly what the models describe, so ``alembic revision
  --autogenerate`` has nothing to add and the two cannot drift apart unnoticed.

Each test runs on its own database cloned from the migrated template (D-12).
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from job_tracker.models import Base

pytestmark: pytest.MarkDecorator = pytest.mark.integration


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for this test's migrated database, disposed so the database can be dropped."""
    engine = create_async_engine(make_url(test_db_url))
    yield engine
    await engine.dispose()


def _unindexed_foreign_keys(connection: Connection) -> list[str]:
    """Foreign keys whose columns do not start any index (the primary key included)."""
    inspector = inspect(connection)
    missing: list[str] = []
    for table in inspector.get_table_names():
        if table == "alembic_version":
            continue
        # Columns of each index; None stands for an expression, e.g. lower(name).
        leading_columns: list[Sequence[str | None]] = [
            index["column_names"] for index in inspector.get_indexes(table)
        ]
        leading_columns.append(inspector.get_pk_constraint(table)["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys(table):
            columns = foreign_key["constrained_columns"]
            if not any(index[: len(columns)] == columns for index in leading_columns):
                missing.append(f"{table}({', '.join(columns)})")
    return missing


def _differences_from_models(connection: Connection) -> list[Any]:
    """What autogenerate would add to make the database match the models."""
    context = MigrationContext.configure(connection)
    return list(compare_metadata(context, Base.metadata))


async def test_every_foreign_key_is_indexed(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        assert await connection.run_sync(_unindexed_foreign_keys) == []


async def test_migrations_match_the_models(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        assert await connection.run_sync(_differences_from_models) == []
