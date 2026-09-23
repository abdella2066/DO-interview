UV ?= uv
PY := .venv/bin/python

.PHONY: install up down logs run test lint format migrate

install: ## Create .venv (Python 3.12) and install dev dependencies
	$(UV) venv --python 3.12 .venv
	$(UV) pip install --python $(PY) -r requirements-dev.txt

up: ## Start Postgres, Valkey, and the API in containers (OrbStack)
	docker compose up -d --build

down: ## Stop containers (docker compose down -v also wipes the database)
	docker compose down

logs: ## Follow API container logs
	docker compose logs -f api

run: ## Run the API on the host with auto-reload (needs `make up` for Postgres/Valkey)
	$(PY) -m uvicorn app.main:create_app --factory --reload --port 8000

test: ## Run the test suite with coverage (needs `make up` for Postgres/Valkey)
	$(PY) -m pytest --cov=app --cov-report=term-missing

lint: ## Lint and check formatting
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format: ## Auto-fix lint issues and format code
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

migrate: ## Apply database migrations to DATABASE_URL
	$(PY) -m alembic upgrade head
