"""``CompanyService``: the company use cases (D-04, D-05, D-07, D-10).

Each method is one use case and one transaction: the service commits, and turns database
errors into domain errors (duplicate name → 409, unknown company → 404, inactive company
in "get or create" → 409). Commits are checked from a second session, which sees only
committed data. Each test runs on its own migrated database (D-12).
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from job_tracker.core.exceptions import (
    CompanyAlreadyExistsError,
    CompanyInactiveError,
    NotFoundError,
)
from job_tracker.models import Company
from job_tracker.schemas.company import CompanyCreate, CompanyUpdate
from job_tracker.services.company import CompanyService

pytestmark = pytest.mark.integration

LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for this test's migrated database, disposed so the database can be dropped."""
    engine = create_async_engine(make_url(test_db_url))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """The session the service works in, as in one request."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def service(session: AsyncSession) -> CompanyService:
    """Service working in the test's session."""
    return CompanyService(session)


async def _stored(engine: AsyncEngine) -> dict[str, Company]:
    """Committed companies by name, read in a separate session."""
    async with AsyncSession(engine) as other:
        companies = (await other.scalars(select(Company))).all()
    return {company.name: company for company in companies}


async def _insert(engine: AsyncEngine, *companies: Company) -> None:
    """Commit ``companies`` from a separate session, as another request would."""
    async with AsyncSession(engine) as other:
        other.add_all(companies)
        await other.commit()


def _create(name: str, **fields: str) -> CompanyCreate:
    """Validated create schema, as the endpoint would pass it."""
    return CompanyCreate.model_validate({"name": name, **fields})


def _update(**fields: object) -> CompanyUpdate:
    """Validated update schema with only the given fields set."""
    return CompanyUpdate.model_validate(fields)


# --- create_company ----------------------------------------------------------------------


async def test_create_commits_the_company(service: CompanyService, engine: AsyncEngine) -> None:
    company = await service.create_company(_create("ACME", website="https://acme.com"))

    stored = await _stored(engine)
    assert stored["ACME"].id == company.id
    assert stored["ACME"].website == "https://acme.com"
    assert company.is_active is True


async def test_create_rejects_a_duplicate_name_regardless_of_case(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await service.create_company(_create("ACME"))

    with pytest.raises(CompanyAlreadyExistsError) as excinfo:
        await service.create_company(_create("acme"))

    assert (excinfo.value.status_code, excinfo.value.code) == (409, "company_already_exists")
    assert set(await _stored(engine)) == {"ACME"}


async def test_service_is_usable_after_a_rejected_duplicate(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await service.create_company(_create("ACME"))
    with pytest.raises(CompanyAlreadyExistsError):
        await service.create_company(_create("ACME"))

    await service.create_company(_create("Globex"))

    assert set(await _stored(engine)) == {"ACME", "Globex"}


# --- get_company, list_companies ---------------------------------------------------------


async def test_get_returns_the_company(service: CompanyService) -> None:
    created = await service.create_company(_create("ACME"))

    company = await service.get_company(created.id)

    assert company.id == created.id


async def test_get_raises_not_found_for_an_unknown_id(service: CompanyService) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        await service.get_company(uuid.uuid4())

    assert excinfo.value.status_code == 404


async def test_list_returns_a_page_and_the_total(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await _insert(engine, Company(name="beta"), Company(name="Alpha"))
    await _insert(engine, Company(name="gamma", is_active=False))

    companies, total = await service.list_companies(limit=20, offset=0)

    assert ([c.name for c in companies], total) == (["Alpha", "beta"], 2)


# --- update_company ----------------------------------------------------------------------


async def test_update_changes_only_the_given_fields_and_commits(
    service: CompanyService, engine: AsyncEngine
) -> None:
    created = await service.create_company(_create("ACME", website="https://acme.com"))

    await service.update_company(created.id, _update(industry="fintech"))

    stored = (await _stored(engine))["ACME"]
    assert (stored.industry, stored.website) == ("fintech", "https://acme.com")


async def test_update_clears_a_field_set_to_null(
    service: CompanyService, engine: AsyncEngine
) -> None:
    created = await service.create_company(_create("ACME", website="https://acme.com"))

    await service.update_company(created.id, _update(website=None))

    assert (await _stored(engine))["ACME"].website is None


async def test_update_can_deactivate_a_company(
    service: CompanyService, engine: AsyncEngine
) -> None:
    created = await service.create_company(_create("ACME"))

    company = await service.update_company(created.id, _update(is_active=False))

    assert company.is_active is False
    assert (await _stored(engine))["ACME"].is_active is False


async def test_update_returns_the_new_updated_at(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await _insert(engine, Company(name="ACME", created_at=LONG_AGO, updated_at=LONG_AGO))
    stored = (await _stored(engine))["ACME"]

    company = await service.update_company(stored.id, _update(notes="Met at a meetup"))

    assert company.updated_at > LONG_AGO


async def test_update_can_change_the_case_of_its_own_name(
    service: CompanyService, engine: AsyncEngine
) -> None:
    created = await service.create_company(_create("ACME"))

    await service.update_company(created.id, _update(name="Acme"))

    assert set(await _stored(engine)) == {"Acme"}


async def test_update_rejects_the_name_of_another_company(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await service.create_company(_create("ACME"))
    globex = await service.create_company(_create("Globex"))

    with pytest.raises(CompanyAlreadyExistsError):
        await service.update_company(globex.id, _update(name="acme"))

    assert set(await _stored(engine)) == {"ACME", "Globex"}


async def test_update_raises_not_found_for_an_unknown_id(service: CompanyService) -> None:
    with pytest.raises(NotFoundError):
        await service.update_company(uuid.uuid4(), _update(notes="x"))


# --- get_or_create_company ---------------------------------------------------------------


async def test_get_or_create_creates_a_missing_company(
    service: CompanyService, engine: AsyncEngine
) -> None:
    company, created = await service.get_or_create_company(_create("ACME", industry="fintech"))

    assert created is True
    assert (await _stored(engine))["ACME"].id == company.id
    assert company.industry == "fintech"


async def test_get_or_create_returns_the_existing_company_regardless_of_case(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await _insert(engine, Company(name="ACME", website="https://acme.com"))

    company, created = await service.get_or_create_company(
        _create("acme", website="https://other.example")
    )

    assert created is False
    assert (company.name, company.website) == ("ACME", "https://acme.com")
    assert set(await _stored(engine)) == {"ACME"}


async def test_get_or_create_refuses_an_inactive_company(
    service: CompanyService, engine: AsyncEngine
) -> None:
    await _insert(engine, Company(name="ACME", is_active=False))

    with pytest.raises(CompanyInactiveError) as excinfo:
        await service.get_or_create_company(_create("ACME"))

    assert (excinfo.value.status_code, excinfo.value.code) == (409, "company_inactive")


async def test_get_or_create_returns_a_company_created_concurrently(
    service: CompanyService, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another request commits the same name between the lookup and the insert: the insert
    # fails on the unique index, and the service must return that company instead.
    lookup: Callable[[str], Awaitable[Company | None]] = service.repository.get_by_name
    calls = 0

    async def lookup_that_misses_first(name: str) -> Company | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            await _insert(engine, Company(name="ACME"))
            return None
        return await lookup(name)

    monkeypatch.setattr(service.repository, "get_by_name", lookup_that_misses_first)

    company, created = await service.get_or_create_company(_create("acme"))

    assert created is False
    assert company.name == "ACME"
    assert set(await _stored(engine)) == {"ACME"}
