"""Job offer endpoints under ``/api/v1/job-offers`` (D-21).

The endpoints are thin: they validate the input with the schemas, call
``JobOfferService`` and turn its result into ``JobOfferRead``, which carries a summary of
the company. Domain errors from the service (404, 409, 422 ``invalid_salary``) and
validation errors (422) are rendered in the shared error format (D-13). The list of offers
comes with the next pull request.

The docstrings of the endpoints are shown as their descriptions in the OpenAPI docs.
"""

from http import HTTPStatus
from typing import Any
from uuid import UUID

from fastapi import APIRouter

from job_tracker.api.deps import JobOfferFiltersDep, JobOfferServiceDep, PaginationDep
from job_tracker.core.exceptions import ErrorResponse
from job_tracker.schemas.job_offer import JobOfferCreate, JobOfferRead, JobOfferUpdate
from job_tracker.schemas.pagination import Page

router: APIRouter = APIRouter(
    prefix="/job-offers",
    tags=["job-offers"],
    responses={
        HTTPStatus.UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "Invalid request data.",
        }
    },
)

NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    HTTPStatus.NOT_FOUND: {
        "model": ErrorResponse,
        "description": "There is no job offer with this ID (or, when creating, no such company).",
    },
}

ALREADY_EXISTS_RESPONSE: dict[int | str, dict[str, Any]] = {
    HTTPStatus.CONFLICT: {
        "model": ErrorResponse,
        "description": (
            "A job offer with this URL already exists (job_offer_already_exists), or, when "
            "creating, the company is inactive (company_inactive)."
        ),
    }
}


@router.post(
    path="",
    responses=NOT_FOUND_RESPONSE | ALREADY_EXISTS_RESPONSE,
    status_code=HTTPStatus.CREATED,
)
async def create_job_offer(data: JobOfferCreate, service: JobOfferServiceDep) -> JobOfferRead:
    """Create a job offer of an active company.

    The URL is normalised and must not be stored yet in any spelling; tags are normalised,
    created when missing and returned in alphabetical order. The salary is a B2B net amount
    per month: `salary_min`, `salary_max` and `currency` are sent together or not at all.
    """
    job_offer = await service.create_offer(data)
    return JobOfferRead.model_validate(job_offer)


@router.get(path="")
async def list_job_offers(
    filters: JobOfferFiltersDep,
    pagination: PaginationDep,
    service: JobOfferServiceDep,
) -> Page[JobOfferRead]:
    """Return one page of job offers, the newest first unless `sort` says otherwise.

    Filters are combined with AND. Repeated `work_mode` and `source` match any of the given
    values; repeated `tag` requires all of them. `seniority=mid` also matches `junior_mid`
    and `mid_senior`. `min_salary` (with `currency`) keeps offers whose maximum reaches it.
    Offers of inactive companies are hidden unless `include_inactive=true`.
    """
    offers, total = await service.list_offers(filters, pagination.limit, pagination.offset)
    return Page[JobOfferRead](
        items=[JobOfferRead.model_validate(offer) for offer in offers],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(path="/{job_offer_id}", responses=NOT_FOUND_RESPONSE)
async def get_job_offer(job_offer_id: UUID, service: JobOfferServiceDep) -> JobOfferRead:
    """Return the job offer with this ID, also when its company is inactive."""
    job_offer = await service.get_offer(job_offer_id)
    return JobOfferRead.model_validate(job_offer)


@router.patch(
    path="/{job_offer_id}",
    responses=NOT_FOUND_RESPONSE | ALREADY_EXISTS_RESPONSE,
)
async def update_job_offer(
    job_offer_id: UUID, data: JobOfferUpdate, service: JobOfferServiceDep
) -> JobOfferRead:
    """Change the fields sent; omitted fields stay unchanged.

    `null` clears an optional field; `tags` replaces the whole list (`[]` removes all).
    The company of an offer cannot be changed. If the salary would be incomplete or have
    the minimum above the maximum after the change, the request fails with
    `422 invalid_salary`.
    """
    job_offer = await service.update_offer(job_offer_id, data)
    return JobOfferRead.model_validate(job_offer)


@router.delete(
    path="/{job_offer_id}", responses=NOT_FOUND_RESPONSE, status_code=HTTPStatus.NO_CONTENT
)
async def delete_job_offer(job_offer_id: UUID, service: JobOfferServiceDep) -> None:
    """Delete the job offer; its tags stay, as other offers may use them."""
    await service.delete_offer(job_offer_id)
