.PHONY: install offline online run verify verify-one contract gen-web-api test lint web-install web-dev web-build

UV := UV_CACHE_DIR=.uv-cache uv
PYTHON := $(UV) run --python 3.12 python

install:
	$(UV) sync --extra dev

offline: verify

online: run

run:
	$(PYTHON) -m uvicorn app.main:app --reload

verify:
	$(PYTHON) main.py

verify-one:
	$(PYTHON) -m app.cli run-one --rule $(RULE) $(if $(SYSTEM),--system-id $(SYSTEM),)

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

test:
	$(PYTHON) -m pytest

lint:
	.venv/bin/ruff check app tests
	.venv/bin/ruff format --check app tests
