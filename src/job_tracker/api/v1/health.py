from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from job_tracker.api.deps import SessionDep
from job_tracker.core.exceptions import DatabaseUnavailableError

router = APIRouter(prefix="/health", tags=["health"])


class HealthRead(BaseModel):
    status: str


@router.get("", response_model=HealthRead)
async def liveness() -> HealthRead:
    """The process is up and serving requests."""
    return HealthRead(status="ok")


@router.get("/db", response_model=HealthRead)
async def readiness(session: SessionDep) -> HealthRead:
    """The database is reachable."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError() from exc
    return HealthRead(status="ok")
