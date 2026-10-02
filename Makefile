.DEFAULT_GOAL := help
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv install install-api test test-fast goldens lint fmt up down logs plan sim api web share pages sil vision aas opcua opcua-check audit clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtualenv
	python3 -m venv .venv && $(PIP) install -q --upgrade pip

install: venv ## Install the project with dev + api dependencies
	$(PIP) install -q -e ".[dev,api]"

install-api: venv ## Install just the API/runtime dependencies
	$(PIP) install -q -e ".[api]"

test: ## Run the full test suite
	$(PY) -m pytest

test-fast: ## Run everything except the golden regressions
	$(PY) -m pytest -m "not golden"

goldens: ## Regenerate golden trajectories (review the summary before committing)
	PYTHONPATH=packages:. $(PY) -m tests.generate_goldens

lint: ## Lint
	$(PY) -m ruff check packages services tests

fmt: ## Format
	$(PY) -m ruff format packages services tests

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

sim: ## Watch the kernel run live in the terminal, e.g. make sim SLOT=B2 OP=retrieve [FAST=1]
	@PYTHONPATH=packages:. $(PY) -m services.sim.live \
		--slot $(or $(SLOT),B2) --op $(or $(OP),retrieve) $(if $(FAST),--fast,)

api: ## Run the live twin backend (FastAPI + WebSocket) on :8000
	PYTHONPATH=packages $(PY) -m uvicorn services.api.app:app --host 127.0.0.1 --port 8000 --reload

web: ## Run the 3D frontend dev server on localhost:5173 (needs `make api` running)
	cd web && npm install && npm run dev

share: ## Serve the PRODUCTION build on localhost:4173 - the one to tunnel (never the dev server)
	cd web && npm run build && npm run preview

pages: ## Build the standalone site as GitHub Pages serves it (no API), on localhost:4180/stf-hw/
	cd web && STF_BASE=/stf-hw/ npm run build:pages
	mkdir -p .cache/pages && ln -sfn ../../web/dist-pages .cache/pages/stf-hw
	@echo "http://localhost:4180/stf-hw/"
	python3 -m http.server 4180 --bind 127.0.0.1 --directory .cache/pages

sil: ## Upgrade 13: compile the PLC program (MatIEC -> WebAssembly) and prove it against the plant
	cd stf-cad/hbw && STF_VARIANT=up12 PYTHONPATH=. ../../$(PY) -m sil.run

vision: ## Upgrade 15: render the training images, train the inspection CNN, export it (ONNX + browser)
	cd stf-cad/hbw && PYTHONPATH=. ../../$(PY) -m vision.train

aas: ## Upgrade 14: generate and verify the Asset Administration Shells (needs the [aas] extra)
	cd stf-cad/hbw && PYTHONPATH=. ../../$(PY) -m aas.build

opcua: ## Upgrade 14: the cell as an OPC UA server on 127.0.0.1:4840 (needs [opcua], STF_OPCUA_USER/PASSWORD)
	cd stf-cad/hbw && PYTHONPATH=. ../../$(PY) -m opcua.server --speed 1

opcua-check: ## Upgrade 14: prove the OPC UA server (mapping, types, Machinery, NodeSet, security, live, mutants)
	cd stf-cad/hbw && PYTHONPATH=. ../../$(PY) -m opcua.check

audit: ## Dependency vulnerability scan (Python and npm)
	$(PY) -m pip_audit
	cd web && npm audit

clean: ## Remove caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
