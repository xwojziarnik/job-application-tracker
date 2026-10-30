"""Reading database errors, so services can turn them into domain errors (D-07).

A service flushes before it commits, so a constraint violation surfaces while it can still
react. It rolls back, looks at the violated constraint and raises a matching domain error::

    try:
        await repository.add(company)  # add() + flush()
    except IntegrityError as exc:
        await session.rollback()
        if violated_constraint(exc) == "uq_companies_name":
            raise ConflictError("A company with this name already exists") from exc
        raise

Constraint names are predictable thanks to the naming convention in ``db/base.py``:
``uq_<table>_<column>``, ``ck_<table>_<name>`` and ``fk_<table>_<column>_<referred table>``.
"""

from sqlalchemy.exc import IntegrityError


def violated_constraint(error: IntegrityError) -> str | None:
    """Return the name of the constraint whose violation raised ``error``.

    The name is read from the original asyncpg exception, two levels down::

        IntegrityError                  SQLAlchemy's error, caught by the service
         └─ .orig                       SQLAlchemy's DB-API adapter: only the message
             └─ .__cause__              asyncpg's exception, e.g. UniqueViolationError
                 └─ .constraint_name    "uq_companies_name"

    The message is not parsed: its wording depends on the PostgreSQL version and the
    server's language.

    Returns ``None`` when the constraint has no name (``NOT NULL``) or the error does not
    come from asyncpg; the caller should then re-raise the original error.
    """
    driver_error: BaseException | None = error.orig.__cause__ if error.orig is not None else None
    name: str | None = getattr(driver_error, "constraint_name", None)
    return name if isinstance(name, str) else None
