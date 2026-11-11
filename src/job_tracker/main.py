"""Application factory and the ASGI application run by uvicorn."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from job_tracker import __version__
from job_tracker.api.v1.router import api_router
from job_tracker.core.config import Settings, get_settings
from job_tracker.core.exceptions import register_exception_handlers
from job_tracker.db.session import create_engine, create_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application; tests pass their own ``settings`` (e.g. their own database)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Create the database engine on startup and close its connections on shutdown."""
        engine = create_engine(settings)
        app.state.sessionmaker = create_sessionmaker(engine)
        yield
        await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app: FastAPI = create_app()
