from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from job_tracker.schemas.pagination import PaginationParams


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a database session for one request and close it afterwards."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Query() spreads the model into separate query parameters (?limit=...&offset=...);
# without it FastAPI would expect the model as the request body.
PaginationDep = Annotated[PaginationParams, Query()]
