"""Shared pagination of list endpoints (D-08).

List endpoints take ``PaginationParams`` as query parameters (through ``PaginationDep``)
and return a ``Page`` of items together with the total number of matching items.
"""

from pydantic import BaseModel, Field

MAX_LIMIT: int = 100
DEFAULT_LIMIT: int = 20


class PaginationParams(BaseModel):
    limit: int = Field(
        default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Number of items to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip before starting to collect the result set",
    )


class Page[T](BaseModel):
    items: list[T] = Field(..., description="List of items on the current page")
    total: int = Field(..., ge=0, description="Total number of items available")
    limit: int = Field(..., ge=1, le=MAX_LIMIT, description="Number of items per page")
    offset: int = Field(..., ge=0, description="Number of items skipped before the current page")
