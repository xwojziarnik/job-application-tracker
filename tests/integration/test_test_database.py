import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def test_template_database_is_migrated(template_db: str, postgres_url: str) -> None:
    engine = create_async_engine(make_url(postgres_url).set(database=template_db))
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
            version_table = result.scalar()
    finally:
        # Close the connection: a template with open connections cannot be cloned.
        await engine.dispose()

    assert version_table == "alembic_version"


@pytest.mark.parametrize("run", [1, 2])
async def test_each_test_gets_a_fresh_database(run: int, test_db_url: str) -> None:
    engine = create_async_engine(make_url(test_db_url))
    try:
        async with engine.begin() as conn:
            before = await conn.execute(text("SELECT to_regclass('public.isolation_check')"))
            assert before.scalar() is None
            await conn.execute(text("CREATE TABLE isolation_check (id integer PRIMARY KEY)"))
    finally:
        await engine.dispose()
