.PHONY: install offline online run verify verify-one contract gen-web-api test lint web-install web-dev web-build e2e-install e2e

UV := UV_CACHE_DIR=.uv-cache uv
PYTHON := $(UV) run --python 3.12 python

install:
	$(UV) sync --extra dev

offline: verify

online: run

run:
	$(PYTHON) run_online.py

verify:
	$(PYTHON) main.py

verify-one:
	$(PYTHON) -m app.cli run-one --rule $(RULE)

contract:
	$(PYTHON) -m app.contract.export

gen-web-api:
	cd web && npx openapi-typescript ../docs/api/openapi.yaml -o src/api/client.ts

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

e2e-install:
	cd web && npm install
	cd web && npx playwright install chromium

e2e:
	cd web && npm run e2e

test:
	$(PYTHON) -m pytest

lint:
	.venv/bin/ruff check app tests
	.venv/bin/ruff format --check app tests
