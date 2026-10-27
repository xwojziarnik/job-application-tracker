import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import docker
import pytest
from alembic import command
from alembic.config import Config
from docker.errors import DockerException
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from job_tracker.core.config import Settings
from job_tracker.main import create_app

# The fixture below stops its own container, so the Ryuk reaper is not needed.
# On Docker Desktop it also tends to fail with "port 8080 is not available".
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

TEMPLATE_DB_NAME = "template_tracker"


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
    except DockerException:
        return False
    return True


@pytest.fixture(scope="session")
def alembic_ini() -> Path:
    return Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A throwaway PostgreSQL in Docker; integration tests are skipped without Docker."""
    if not _docker_available():
        if os.environ.get("CI"):
            pytest.fail("Docker is required for integration tests in CI")
        pytest.skip("Docker is not running")

    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


def make_settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url)


@pytest.fixture
def unreachable_db_settings() -> Settings:
    # Nothing listens on port 1, so every connection attempt fails fast.
    return make_settings("postgresql+asyncpg://user:pass@127.0.0.1:1/none")


async def _client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # ASGITransport does not run lifespan events, so enter the lifespan explicitly.
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def client(unreachable_db_settings: Settings) -> AsyncIterator[AsyncClient]:
    async for c in _client_for(create_app(unreachable_db_settings)):
        yield c


@pytest.fixture
async def db_client(postgres_url: str) -> AsyncIterator[AsyncClient]:
    async for c in _client_for(create_app(make_settings(postgres_url))):
        yield c


@pytest.fixture(scope="session")
async def template_db(postgres_url: str, alembic_ini: Path) -> AsyncIterator[str]:
    """A throwaway PostgreSQL database created from the template database."""
    base_url = make_url(postgres_url)

    # 1. Create the database from the always-present "postgres" database.
    #    CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    admin_engine = create_async_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as conn:
        # The name is our own constant, so formatting it into SQL is safe.
        await conn.execute(text(f'CREATE DATABASE "{TEMPLATE_DB_NAME}"'))
    await admin_engine.dispose()

    # 2. Point Alembic at the new database. Alembic needs a string with the
    #    real password; str(url) would mask it as "***".
    template_url = base_url.set(database=TEMPLATE_DB_NAME)
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", template_url.render_as_string(hide_password=False))

    # 3. Migrate. env.py calls asyncio.run(), which cannot run inside this
    #    fixture's event loop, so run Alembic in a separate thread.
    await asyncio.to_thread(command.upgrade, config, "head")
    yield TEMPLATE_DB_NAME
