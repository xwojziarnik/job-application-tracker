"""Database engine and session factory, created once per application in its lifespan."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from job_tracker.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the async engine; ``pool_pre_ping`` replaces connections the server dropped."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        echo=settings.database_echo,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory; objects stay readable after a commit.

    ``expire_on_commit=False``: otherwise reading an attribute after a commit would reload
    it from the database, which async code cannot do implicitly.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
