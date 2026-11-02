"""Company endpoints under ``/api/v1/companies`` (D-04, D-05, D-08, D-10).

The endpoints are thin: they validate the input with the schemas, call
``CompanyService`` and turn its result into ``CompanyRead``. Domain errors raised by the
service (404, 409) and validation errors (422) are rendered in the shared error format by
the application's exception handlers (D-13). Companies are never deleted, only
deactivated, so there is no ``DELETE`` endpoint (D-04).

The docstrings of the endpoints are shown as their descriptions in the OpenAPI docs.
"""

from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response

from job_tracker.api.deps import CompanyServiceDep, PaginationDep
from job_tracker.core.exceptions import ErrorResponse
from job_tracker.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate
from job_tracker.schemas.pagination import Page

router = APIRouter(
    prefix="/companies",
    tags=["companies"],
    responses={
        HTTPStatus.UNPROCESSABLE_ENTITY: {
            "model": ErrorResponse,
            "description": "Invalid request data.",
        },
    },
)

NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    HTTPStatus.NOT_FOUND: {
        "model": ErrorResponse,
        "description": "There is no company with this ID.",
    },
}


@router.post(
    path="",
    status_code=HTTPStatus.CREATED,
    responses={
        HTTPStatus.CONFLICT: {
            "model": ErrorResponse,
            "description": "Company with the same name already exists.",
        },
    },
)
async def create_company(
    data: CompanyCreate,
    service: CompanyServiceDep,
) -> CompanyRead:
    """Create an active company.

    Text fields are trimmed and blank optional fields are stored as `null`; `website` must
    be an `https` URL. The name must be unique regardless of case: a taken name returns
    `409 company_already_exists`. The client cannot set `id`, `is_active` or the
    timestamps.
    """
    company = await service.create_company(data)
    return CompanyRead.model_validate(company)


@router.post(
    path="/get-or-create",
    responses={
        HTTPStatus.CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "A company with this name exists but is inactive; reactivate it with "
                "PATCH first (company_inactive)."
            ),
        },
        HTTPStatus.CREATED: {
            "model": CompanyRead,
            "description": "There was no company with this name; it has been created.",
        },
    },
)
async def get_or_create_company(
    data: CompanyCreate,
    service: CompanyServiceDep,
    response: Response,
) -> CompanyRead:
    """Return the company with this name, or create it if there is none.

    The name is matched regardless of case. An existing company is returned unchanged with
    `200`: the other fields in the request are ignored. A new company is created and
    returned with `201`. Calling this endpoint again with the same name never creates a
    second company. An inactive company is not reactivated: the request fails with
    `409 company_inactive`.
    """
    company, is_created = await service.get_or_create_company(data)
    if is_created:
        response.status_code = HTTPStatus.CREATED
    return CompanyRead.model_validate(company)


@router.get(
    path="/{company_id}",
    responses=NOT_FOUND_RESPONSE,
)
async def get_company(
    company_id: UUID,
    service: CompanyServiceDep,
) -> CompanyRead:
    """Return the company with this ID, whether it is active or not."""
    company = await service.get_company(company_id)
    return CompanyRead.model_validate(company)


@router.get(
    path="",
)
async def list_companies(
    service: CompanyServiceDep,
    pagination: PaginationDep,
    search: Annotated[
        str | None,
        Query(
            max_length=200,
            description=(
                "Return only companies whose name contains this text, regardless of case; "
                "`%` and `_` are matched literally."
            ),
        ),
    ] = None,
    include_inactive: Annotated[
        bool, Query(description="Also return inactive companies (hidden by default).")
    ] = False,
) -> Page[CompanyRead]:
    """Return one page of companies, sorted by name regardless of case.

    Inactive companies are left out unless `include_inactive` is set. `total` is the
    number of all matching companies, not only those on this page.
    """
    companies, total = await service.list_companies(
        search=search,
        include_inactive=include_inactive,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page[CompanyRead](
        items=[CompanyRead.model_validate(company) for company in companies],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.patch(
    path="/{company_id}",
    responses={
        HTTPStatus.CONFLICT: {
            "model": ErrorResponse,
            "description": "Company with the same name already exists.",
        },
    }
    | NOT_FOUND_RESPONSE,
)
async def update_company(
    company_id: UUID,
    data: CompanyUpdate,
    service: CompanyServiceDep,
) -> CompanyRead:
    """Change the fields sent in the request; omitted fields stay unchanged.

    `null` clears an optional field; `name` and `is_active` cannot be cleared. Set
    `is_active` to `false` to deactivate a company (companies are never deleted) and to
    `true` to reactivate it. A name taken by another company, regardless of case, returns
    `409 company_already_exists`.
    """
    company = await service.update_company(company_id, data)
    return CompanyRead.model_validate(company)
