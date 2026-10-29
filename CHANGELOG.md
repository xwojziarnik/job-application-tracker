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

- Docker Compose override for development: mounted sources and live reload.
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

### Deprecated

### Removed

### Fixed

- Running migrations inside the application's process no longer disables the
  application's loggers.

### Security

- Request validation errors no longer echo the rejected input back in the response.
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

[Unreleased]: https://github.com/xwojziarnik/job-application-tracker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/xwojziarnik/job-application-tracker/releases/tag/v0.1.0
