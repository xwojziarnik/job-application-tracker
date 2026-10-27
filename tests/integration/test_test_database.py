import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def test_template_database_is_migrated(template_db: str, postgres_url: str) -> None:
    engine = create_async_engine(make_url(postgres_url).set(database=template_db))
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
            version_table = result.scalar()
    finally:
        # Close the connection: a template with open connections cannot be cloned.
        await engine.dispose()

    assert version_table == "alembic_version"
