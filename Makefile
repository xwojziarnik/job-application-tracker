# Development tasks. Run `make` (or `make help`) to list them.
# Commands run in the active Python environment (the pyenv virtualenv of this project).

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Optional test selection for the test targets:
#   t = a test file, directory or single test, e.g. t=tests/unit/test_tags.py
#   k = a pytest -k expression matching test names, e.g. k="salary and not update"
t ?=
k ?=
PYTEST_SELECT = $(if $(k),-k "$(k)")

# uv works on the active Python environment instead of creating a .venv (D-22). pyenv
# resolves `python` to the project's virtualenv even when $VIRTUAL_ENV is not set.
export UV_PROJECT_ENVIRONMENT := $(shell python -c 'import sys; print(sys.prefix)')
export UV_PYTHON := $(UV_PROJECT_ENVIRONMENT)/bin/python

.PHONY: help install lock format lint typecheck test test-unit test-integration audit check ci \
	db migrate migration downgrade run

help: ## List the available tasks
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Install the locked app and dev tools (uv.lock) and the pre-commit hook
	@python -c 'import sys; sys.exit(sys.prefix == sys.base_prefix)' \
		|| { echo "Activate the project's virtualenv first"; exit 1; }
	uv sync --locked --inexact
	pre-commit install

lock: ## Update uv.lock after changing dependencies in pyproject.toml
	uv lock

format: ## Format the code and fix lint errors that can be fixed automatically
	ruff format . && ruff check --fix .

lint: ## Check formatting and lint rules without changing files (as in CI)
	ruff format --check . && ruff check .

typecheck: ## Strict type checking
	mypy

test: ## All tests, or a selection: make test t=<file or dir> k=<name filter>
	pytest -q -rs $(t) $(PYTEST_SELECT)

test-unit: ## Unit tests only (no Docker needed); k=<name filter> narrows them
	pytest tests/unit -q $(PYTEST_SELECT)

test-integration: ## Integration tests only (need Docker); k=<name filter> narrows them
	pytest tests/integration -q -rs $(PYTEST_SELECT)

audit: ## Known vulnerabilities in the locked packages (uv.lock)
	@set -o pipefail; \
	uv export --locked --all-groups --no-emit-project --format requirements-txt --quiet \
		| pip-audit -r /dev/stdin --disable-pip --require-hashes --progress-spinner off

check: format typecheck test ## Before a commit: format, type check and test

ci: lint typecheck test audit ## The checks CI runs, without changing files

db: ## Start PostgreSQL for local development
	docker compose up -d db

migrate: ## Apply all migrations to the local database
	alembic upgrade head

migration: ## Create a numbered migration from the models: make migration m="create offers"
	@test -n "$(m)" || { echo 'Usage: make migration m="describe the change"'; exit 1; }
	alembic revision --autogenerate -m "$(m)"

downgrade: ## Roll back the last migration
	alembic downgrade -1

run: ## Run the API with live reload
	uvicorn job_tracker.main:app --reload
