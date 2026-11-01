"""``CompanyRepository``: database access for companies (D-07, D-08).

The repository adds and flushes but never commits; the service decides when to commit.
Lists are sorted by name regardless of case, hide inactive companies unless asked, and
search for a fragment of the name. Each test runs on its own migrated database (D-12).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from job_tracker.db.errors import violated_constraint
from job_tracker.models import Company
from job_tracker.repositories.company import CompanyRepository

pytestmark = pytest.mark.integration

LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def session(test_db_url: str) -> AsyncIterator[AsyncSession]:
    """Session on this test's migrated database."""
    engine = create_async_engine(make_url(test_db_url))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
def repository(session: AsyncSession) -> CompanyRepository:
    """Repository working in the test's session."""
    return CompanyRepository(session)


async def _add_companies(session: AsyncSession, *names: str, is_active: bool = True) -> None:
    """Insert companies with the given names and commit them."""
    session.add_all(Company(name=name, is_active=is_active) for name in names)
    await session.commit()


async def _count(session: AsyncSession) -> int | None:
    """Number of companies in the database."""
    return await session.scalar(select(func.count()).select_from(Company))


async def _names(
    repository: CompanyRepository,
    *,
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    include_inactive: bool = False,
) -> tuple[list[str], int]:
    """Names of the companies on the page returned by ``list_companies``, and the total."""
    companies, total = await repository.list_companies(
        limit=limit, offset=offset, search=search, include_inactive=include_inactive
    )
    return [company.name for company in companies], total


# --- add_company -------------------------------------------------------------------------


async def test_add_flushes_so_the_id_is_known(repository: CompanyRepository) -> None:
    company = await repository.add_company(Company(name="ACME"))

    assert company.id is not None


async def test_add_does_not_commit(repository: CompanyRepository, session: AsyncSession) -> None:
    await repository.add_company(Company(name="ACME"))
    assert await _count(session) == 1

    await session.rollback()

    assert await _count(session) == 0


async def test_add_leaves_duplicates_to_the_database(repository: CompanyRepository) -> None:
    await repository.add_company(Company(name="ACME"))

    with pytest.raises(IntegrityError) as excinfo:
        await repository.add_company(Company(name="acme"))

    assert violated_constraint(excinfo.value) == "uq_companies_lower_name"


# --- get_company, get_by_name ------------------------------------------------------------


async def test_get_returns_the_company(repository: CompanyRepository) -> None:
    company = await repository.add_company(Company(name="ACME"))

    assert await repository.get_company(company.id) is company


async def test_get_returns_none_for_an_unknown_id(repository: CompanyRepository) -> None:
    assert await repository.get_company(uuid.uuid4()) is None


async def test_get_by_name_ignores_case(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "ACME")

    company = await repository.get_by_name("acme")

    assert company is not None
    assert company.name == "ACME"


async def test_get_by_name_finds_inactive_companies(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    # "Get or create" must see an inactive company to refuse it with 409 (D-10).
    await _add_companies(session, "ACME", is_active=False)

    company = await repository.get_by_name("ACME")

    assert company is not None
    assert company.is_active is False


async def test_get_by_name_returns_none_when_missing(repository: CompanyRepository) -> None:
    assert await repository.get_by_name("ACME") is None


# --- list_companies ----------------------------------------------------------------------


async def test_list_is_sorted_by_name_regardless_of_case(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "beta", "Alpha", "Gamma")

    assert await _names(repository) == (["Alpha", "beta", "Gamma"], 3)


async def test_pages_follow_the_sort_order(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    # Inserted in reverse order: the database must sort before it takes a page.
    await _add_companies(session, "gamma", "beta", "Alpha")

    assert await _names(repository, limit=1) == (["Alpha"], 3)
    assert await _names(repository, limit=1, offset=2) == (["gamma"], 3)


async def test_list_returns_the_requested_page_with_the_total(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "Alpha", "beta", "gamma")

    assert await _names(repository, limit=2, offset=1) == (["beta", "gamma"], 3)


async def test_offset_past_the_end_returns_no_items_but_the_total(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "Alpha", "beta")

    assert await _names(repository, offset=10) == ([], 2)


async def test_list_hides_inactive_companies_by_default(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "Alpha", "gamma")
    await _add_companies(session, "beta", is_active=False)

    assert await _names(repository) == (["Alpha", "gamma"], 2)


async def test_list_can_include_inactive_companies(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "Alpha")
    await _add_companies(session, "beta", is_active=False)

    assert await _names(repository, include_inactive=True) == (["Alpha", "beta"], 2)


async def test_search_finds_a_fragment_of_the_name_regardless_of_case(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "ACME", "ACME Labs", "Globex")

    assert await _names(repository, search="cme") == (["ACME", "ACME Labs"], 2)


@pytest.mark.parametrize(
    ("names", "search", "expected"),
    [
        (["100% Remote", "1000 Remote"], "100%", ["100% Remote"]),
        (["a_b", "axb"], "a_b", ["a_b"]),
    ],
)
async def test_search_treats_like_wildcards_as_plain_characters(
    repository: CompanyRepository,
    session: AsyncSession,
    names: list[str],
    search: str,
    expected: list[str],
) -> None:
    await _add_companies(session, *names)

    assert await _names(repository, search=search) == (expected, len(expected))


async def test_search_respects_the_inactive_filter(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    await _add_companies(session, "ACME")
    await _add_companies(session, "ACME Labs", is_active=False)

    assert await _names(repository, search="acme") == (["ACME"], 1)
    assert await _names(repository, search="acme", include_inactive=True) == (
        ["ACME", "ACME Labs"],
        2,
    )


# --- update_company ----------------------------------------------------------------------


async def test_update_applies_the_changes(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    company = await repository.add_company(Company(name="ACME", website="https://acme.com"))

    await repository.update_company(
        company, {"industry": "fintech", "website": None, "is_active": False}
    )

    assert (company.industry, company.website, company.is_active) == ("fintech", None, False)


async def test_update_refreshes_updated_at(
    repository: CompanyRepository, session: AsyncSession
) -> None:
    company = Company(name="ACME", created_at=LONG_AGO, updated_at=LONG_AGO)
    session.add(company)
    await session.commit()

    await repository.update_company(company, {"name": "ACME Labs"})

    # Read without a refresh: the new value must already be loaded, because a lazy load
    # of an expired attribute fails in async code (MissingGreenlet).
    assert company.updated_at > LONG_AGO
    assert company.created_at == LONG_AGO
