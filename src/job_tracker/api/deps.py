from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_tracker.schemas.pagination import PaginationParams
from job_tracker.services.company import CompanyService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for one request and close it afterwards."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_company_service(session: SessionDep) -> CompanyService:
    """Return a ``CompanyService`` working in this request's session.

    The service lives as long as the request: it commits its own transaction (D-07), and
    the session is closed by ``get_session`` when the request ends.
    """
    return CompanyService(session)


CompanyServiceDep = Annotated[CompanyService, Depends(get_company_service)]

# Query() spreads the model into separate query parameters (?limit=...&offset=...);
# without it FastAPI would expect the model as the request body.
PaginationDep = Annotated[PaginationParams, Query()]
