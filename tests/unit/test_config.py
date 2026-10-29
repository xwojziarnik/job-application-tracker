from pathlib import Path

import pytest
from pydantic import ValidationError

from job_tracker.core.config import Settings

PRODUCTION_DB_URL = "postgresql+asyncpg://app:secret@db.internal:5432/tracker"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Keep the developer's shell and .env file out of these tests.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.chdir(tmp_path)


def test_production_without_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="DATABASE_URL must be set explicitly"):
        Settings()


def test_production_accepts_database_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", PRODUCTION_DB_URL)

    assert Settings().database_url == PRODUCTION_DB_URL


def test_local_falls_back_to_default_database_url() -> None:
    assert Settings().database_url.startswith("postgresql+asyncpg://")


def test_production_with_debug_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", PRODUCTION_DB_URL)
    monkeypatch.setenv("DEBUG", "true")

    with pytest.raises(ValidationError, match="DEBUG must not be enabled in production"):
        Settings()


def test_local_allows_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBUG", "true")

    assert Settings().debug is True
