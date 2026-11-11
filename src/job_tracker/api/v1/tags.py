"""Tag list under ``/api/v1/tags`` (D-21).

Tags are created with the offers that use them; this endpoint only lists their names,
e.g. to suggest existing tags instead of new spellings when adding an offer.
"""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query

from job_tracker.api.deps import JobOfferServiceDep, PaginationDep
from job_tracker.core.exceptions import ErrorResponse
from job_tracker.core.tags import MAX_TAG_LENGTH
from job_tracker.schemas.pagination import Page

router: APIRouter = APIRouter(
    prefix="/tags",
    tags=["tags"],
    responses={
        HTTPStatus.UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "Invalid request data.",
        },
    },
)


@router.get(path="")
async def list_tags(
    pagination: PaginationDep,
    service: JobOfferServiceDep,
    search: Annotated[
        str | None,
        Query(
            max_length=MAX_TAG_LENGTH,
            description=(
                "Return only tags whose name contains this text, regardless of case; "
                "`%` and `_` are matched literally."
            ),
        ),
    ] = None,
) -> Page[str]:
    """Return tag names in alphabetical order, optionally only those containing `search`."""
    names, total = await service.list_tags(search, pagination.limit, pagination.offset)
    return Page[str](items=names, total=total, limit=pagination.limit, offset=pagination.offset)
