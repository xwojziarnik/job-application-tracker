"""The salary rule of a job offer (D-03), shared by the schemas and the service.

A salary is a B2B net amount per month: ``salary_min``, ``salary_max`` and ``currency``
are set together or not at all, and the minimum is not above the maximum. The database
enforces the same rule with ``ck_job_offers_salary_range``.
"""


def ensure_valid_salary(
    salary_min: int | None, salary_max: int | None, currency: str | None
) -> None:
    """Raise ``ValueError`` if the salary is incomplete or its minimum exceeds the maximum.

    Positive amounts are not checked here: ``SalaryAmount`` in the schemas does that.
    """
    given = [element for element in (salary_min, salary_max, currency) if element is not None]
    if 0 < len(given) < 3:
        raise ValueError("salary_min, salary_max and currency must be set together")
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise ValueError("salary_min must not be greater than salary_max")
