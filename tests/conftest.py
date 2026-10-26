import os
from collections.abc import AsyncIterator, Iterator

import docker
import pytest
from docker.errors import DockerException
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from job_tracker.core.config import Settings
from job_tracker.main import create_app

# The fixture below stops its own container, so the Ryuk reaper is not needed.
# On Docker Desktop it also tends to fail with "port 8080 is not available".
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
    except DockerException:
        return False
    return True


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
