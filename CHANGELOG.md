# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Describe every change under `[Unreleased]`, in one of these subsections:
`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
Empty subsections are dropped when a version is released.

A push to `main` releases a new version when a commit subject ends with `[major]`,
`[minor]` or `[fix]`: CI bumps the version with `hatch version`, turns `[Unreleased]` into
the new version section, updates the links below and tags the commit.

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.5.0] - 2026-11-11

### Added

- `job_offers` table: company, title, URL, source, seniority, work mode, location,
  salary range with currency, posting date, description and notes. The database itself
  rejects values outside the enumerations, an incomplete or invalid salary range (all of
  `salary_min`, `salary_max` and `currency`, or none; positive; minimum not above the
  maximum), a URL stored twice and deleting a company that has offers.
- Enumerations of offer sources (LinkedIn, Pracuj.pl, Just Join IT, Bulldogjob, No Fluff
  Jobs, Rocket Jobs, Joobie, company website), seniority levels including combined ones
  such as `mid_senior`, work modes and currencies.
- Normalisation of offer URLs, so one offer is stored under one spelling: scheme and host
  in lower case, no credentials, default port, fragment, trailing slashes, tracking
  parameters (`utm_*`, `gclid`, `fbclid`, LinkedIn's `refId`, `trackingId`, `trk`) or
  empty parameters. It is applied whenever an offer is created or its URL changed.
- Normalisation of tag names, so one tag has one spelling: trimmed, lower-case, whitespace
  replaced with `-`; only `a-z`, `0-9`, `.`, `+`, `#` and `-`, at most 50 characters (so
  `C++`, `C#`, `.NET` and `Node.js` work), with at least one letter or digit. Names with
  other characters or only punctuation are rejected.
- `tags` and `job_offer_tags` tables: an offer can have many tags and a tag many offers,
  each tag at most once per offer. The database rejects tag names that are not normalised,
  keeps tags when an offer is deleted and refuses to delete a tag that is still in use.
- Job offer schemas for creating, updating and reading an offer: text is trimmed, blank
  optional text is stored as `null`, the URL must be `https` and is normalised, tags are
  normalised with duplicates merged (at most 20), the salary is all or nothing with the
  minimum not above the maximum, and the posting date cannot be in the future (in the
  `Europe/Warsaw` calendar). An update changes only the fields sent; the company of an
  offer cannot be changed.
- Job offer repository: offers are read with their company and tags, and tags are created
  on the fly without failing when another request stores the same name at the same time.
- Job offer use cases: create, read, update and delete. An unknown company or offer
  returns `404`, adding an offer to an inactive company `409 company_inactive`, and a URL
  already stored (in any spelling) `409 job_offer_already_exists`. An update that would
  leave the salary incomplete or with the minimum above the maximum returns
  `422 invalid_salary`. A rejected change stores nothing, not even new tags.
- Tags of an offer are always returned in alphabetical order.
- Job offer endpoints under `/api/v1/job-offers`:
  - `POST /job-offers` creates an offer (`201`; `404` for an unknown company,
    `409 company_inactive`, `409 job_offer_already_exists` for a URL already stored in any
    spelling);
  - `GET /job-offers/{job_offer_id}` returns an offer, also of an inactive company (`404` if
    unknown);
  - `PATCH /job-offers/{job_offer_id}` changes only the fields sent (`422 invalid_salary`,
    `409 job_offer_already_exists`);
  - `DELETE /job-offers/{job_offer_id}` deletes an offer (`204`); its tags stay.
  Every offer response carries a summary of its company (`id`, `name`, `is_active`).
- Offer list `GET /api/v1/job-offers` with pagination and filters: `company_id`,
  `work_mode` and `source` (repeatable, any of), `seniority` (`mid` also matches
  `junior_mid` and `mid_senior`), `tag` (repeatable, all of), `min_salary` with `currency`
  (offers whose maximum reaches it), `search` in the title and `include_inactive` (offers
  of inactive companies are hidden by default). `sort` is `newest` (default), `salary` or
  `title`.
- Tag list `GET /api/v1/tags`: tag names in alphabetical order, with `search` and pagination.

### Changed

- `make test`, `make test-unit` and `make test-integration` accept `t=` (a test file,
  directory or single test) and `k=` (a filter on test names) to run only some tests.

### Security

- The database URL, which contains the password, is no longer shown when the settings
  are printed or logged.

## [0.4.0] - 2026-11-02

### Added

- `companies` table: name (unique regardless of case), website, location, industry, notes
  and an `is_active` flag; companies are deactivated instead of deleted.
- Test that fails when the models and the migrations differ.
- Company use cases: create, read, list, update and an idempotent "get or create" by
  name; a duplicate name returns `409 company_already_exists`, and "get or create" for an
  inactive company returns `409 company_inactive`.
- `Makefile` with development tasks: `make check` before a commit, `make ci` for the CI
  checks, plus formatting, tests, migrations and running the API.
- Company schemas for creating, updating and reading a company: text is trimmed, blank
  optional text is stored as `null`, `website` must be an `https` URL, and unknown fields
  (including `id`, `is_active` on creation and the timestamps) are rejected.
- Company endpoints under `/api/v1/companies`:
  - `POST /companies` creates a company (`201`; `409 company_already_exists` for a name
    taken regardless of case);
  - `GET /companies` returns a page of companies sorted by name, with `search` (a
    fragment of the name, regardless of case) and `include_inactive` (inactive companies
    are hidden by default);
  - `GET /companies/{company_id}` returns a company, active or not (`404` if unknown);
  - `PATCH /companies/{company_id}` changes only the fields sent; `null` clears an
    optional field, and `is_active` deactivates or reactivates the company;
  - `POST /companies/get-or-create` returns the company with this name (`200`) or creates
    it (`201`); an inactive company is refused with `409 company_inactive`.
  Companies cannot be deleted (`405`). All errors, including `422`, are documented in the
  OpenAPI docs in the shared error format.

### Changed

- Migrations are numbered `001`, `002`, ... and their files are named
  `<number>_<slug>.py`.

## [0.3.0] - 2026-10-30

### Added

- Shared pagination for list endpoints: `limit` (default 20, at most 100) and `offset`
  query parameters, and a `{"items", "total", "limit", "offset"}` response shape.
- UUID v4 primary key mixin for models, generated by the application.
- Helper that reads the name of the violated constraint from a database integrity error,
  so services can turn constraint violations into domain errors such as `409 Conflict`.

## [0.2.0] - 2026-10-30

### Added

- Domain errors `ConflictError` (`409`, `conflict`), `ServiceUnavailableError` (`503`,
  `service_unavailable`) and `DatabaseUnavailableError` (`503`, `database_unavailable`).
- Default messages for domain errors, so they can be raised without a message.
- Server-side domain errors (`5xx`) are logged with their traceback and original cause;
  the response contains only the error code and message.

### Changed

- `GET /api/v1/health/db` returns errors in the shared format:
  `{"error": {"code": "database_unavailable", "message": "Database unavailable"}}`
  instead of `{"detail": "Database unavailable"}`.
- HTTP errors, including `404` for unknown routes and `405` for unsupported methods, use
  the shared error format. The `code` is derived from the status phrase (`not_found`,
  `method_not_allowed`, `too_many_requests`, ...; `http_error` for non-standard statuses),
  headers such as `Allow` are kept, and a non-string `detail` is not exposed.
- Request validation errors (`422`) use the shared error format with the code
  `validation_error` and one `details` entry per invalid field. `field` is the path to the
  value without its source (`tags.1.name`, `limit`), or `body` for invalid JSON.
- Unhandled exceptions return `500` in the shared error format with the code
  `internal_server_error` (the same code as an explicit `HTTPException(500)`) instead of a
  plain-text body. The exception is logged with its traceback, the request method and path.

### Fixed

- Running migrations inside the application's process no longer disables the
  application's loggers.

### Security

- Request validation errors no longer echo the rejected input back in the response.
- The application refuses to start in production with `DEBUG` enabled, which would answer
  unhandled exceptions with a traceback page instead of the generic error response.

## [0.1.1] - 2026-10-27

### Added

- Docker Compose override for development: mounted sources and live reload.

### Security

- Docker Compose publishes the API and database ports on `127.0.0.1` only
  (configurable with `BIND_HOST`), so they are not reachable from the local network.

## [0.1.0] - 2026-10-26

### Added

- FastAPI application skeleton with an app factory and a lifespan-managed async database engine.
- Health check endpoints: `GET /api/v1/health` (liveness) and `GET /api/v1/health/db` (readiness).
- Async SQLAlchemy 2.0 setup with deterministic constraint naming and a timestamp mixin.
- Alembic migrations configured for async PostgreSQL.
- Settings from environment variables; `DATABASE_URL` is required in production.
- Consistent JSON format for domain errors.
- Docker image (non-root) and Docker Compose with PostgreSQL 17 and configurable host ports.
- Unit tests and integration tests against PostgreSQL with testcontainers.
- CI: dependency audit, linting, strict type checking and tests.
- Security tooling: `pip-audit`, ruff security rules, Dependabot for pip and GitHub Actions,
  GitHub Actions pinned to commit SHAs.
- Automated releases: version bump with hatch and changelog update on `main`.

[Unreleased]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xwojziarnik/job-application-tracker/releases/tag/v0.1.0
