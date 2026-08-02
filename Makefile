.DEFAULT_GOAL := help
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv install test test-fast goldens lint fmt up down logs plan sim clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtualenv
	python3 -m venv .venv && $(PIP) install -q --upgrade pip

install: venv ## Install the project and dev dependencies
	$(PIP) install -q -e ".[dev]"

test: ## Run the full test suite
	$(PY) -m pytest

test-fast: ## Run everything except the golden regressions
	$(PY) -m pytest -m "not golden"

goldens: ## Regenerate golden trajectories (review the summary before committing)
	PYTHONPATH=packages:. $(PY) -m tests.generate_goldens

lint: ## Lint
	$(PY) -m ruff check packages tests

fmt: ## Format
	$(PY) -m ruff format packages tests

up: ## Start Mosquitto, Redis and TimescaleDB
	docker compose up -d

down: ## Stop the infrastructure
	docker compose down

logs: ## Tail infrastructure logs
	docker compose logs -f

plan: ## Print a trajectory, e.g. make plan SLOT=B2 OP=retrieve
	@PYTHONPATH=packages $(PY) -c "\
from stf_layout import get_layout; \
import stf_kernel as k; \
L = get_layout(); \
op = '$(or $(OP),retrieve)'; \
t = (k.plan_retrieve if op == 'retrieve' else k.plan_store)(L, '$(or $(SLOT),B2)'); \
print(t.describe())"

sim: ## Watch the kernel run live, e.g. make sim SLOT=B2 OP=retrieve [FAST=1]
	@PYTHONPATH=packages:. $(PY) -m services.sim.live \
		--slot $(or $(SLOT),B2) --op $(or $(OP),retrieve) $(if $(FAST),--fast,)

clean: ## Remove caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
