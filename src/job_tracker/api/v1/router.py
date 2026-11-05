from fastapi import APIRouter

from job_tracker.api.v1 import health
from job_tracker.api.v1.companies import router as companies_router

api_router: APIRouter = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(companies_router)
