import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_readiness_returns_ok_when_database_is_up(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_migrations_upgrade_and_downgrade(postgres_url: str, alembic_ini: Path) -> None:
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", postgres_url)

    # env.py calls asyncio.run(), so run Alembic outside the test's event loop.
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "base")
