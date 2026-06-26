# Makefile — convenience targets for the Zapp Global Philosophy School platform.
# Run `make help` to list available targets.

.PHONY: help smoke up down logs test lint fmt typecheck

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Compose smoke check (Task 18 / platform-scaffold-004,005,006)
# Boots db+backend, asserts GET /health=200 + vector extension, then tears down.
# ---------------------------------------------------------------------------
smoke: ## Run compose smoke check (boots db+backend, /health=200, vector ext, teardown)
	@chmod +x scripts/smoke.sh
	./scripts/smoke.sh

# ---------------------------------------------------------------------------
# Local dev helpers
# ---------------------------------------------------------------------------
up: ## Start db + backend (and frontend if built)
	docker compose up -d --build db backend

down: ## Tear down all services and remove volumes
	docker compose down -v --remove-orphans

logs: ## Tail backend logs
	docker compose logs -f backend

# ---------------------------------------------------------------------------
# Backend quality gates (requires uv / backend venv active)
# ---------------------------------------------------------------------------
lint: ## Run ruff linter
	cd backend && uv run ruff check .

fmt: ## Run ruff formatter check
	cd backend && uv run ruff format --check .

typecheck: ## Run mypy
	cd backend && uv run mypy

test: ## Run pytest
	cd backend && uv run pytest
