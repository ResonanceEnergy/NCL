# NCL Brain — developer experience targets.
#
# Quick reference:
#   make setup           # create venv + install editable + dev extras
#   make test            # run pytest suite (fail-fast)
#   make run             # start the FastAPI service on :8800 (prod-style bind)
#   make dev             # uvicorn --reload on 127.0.0.1:8800 (DEV; no prod IP)
#   make lint            # ruff check + ruff format --check (CI-equivalent)
#   make format          # ruff autoformat (writes)
#   make smoke           # curl /health on the running dev brain
#   make smoke-council   # quick council-pack smoke (python script)
#   make openapi-export  # dump openapi.json from running brain
#   make restart-brain   # kickstart the macOS LaunchAgent
#   make tail-log        # tail brain stderr

.PHONY: setup test run dev lint format smoke smoke-council openapi-export restart-brain tail-log

setup:
	python3 -m venv venv && ./venv/bin/pip install -e ".[dev]"

test:
	pytest -x tests/

run:
	./venv/bin/python -m uvicorn runtime.api.routes:versioned_app --host 0.0.0.0 --port 8800

# W8-A11 #3: dev-loop on loopback with --reload. Uses dev port (8800 here is OK
# because the production LaunchAgent binds 100.72.223.123:8800 — different
# interface, no conflict). For an isolated port use scripts/launch-brain-dev.sh
# which binds 127.0.0.1:8801.
dev:
	uvicorn runtime.api.routes:versioned_app --host 127.0.0.1 --port 8800 --reload

lint:
	ruff check runtime/ && ruff format --check runtime/

format:
	ruff format runtime/ tests/ scripts/

# W8-A11 #4: lightweight health probe. Assumes `make dev` (or launch-brain-dev.sh
# on 8801) is up. Override port via: make smoke PORT=8801
PORT ?= 8800
smoke:
	curl -s http://127.0.0.1:$(PORT)/health

smoke-council:
	python3 scripts/smoke_council_pack.py

# W8-A11 #5 (missing #12): export the live OpenAPI schema to openapi.json.
# Not committed — gitignore handles it. Override token if endpoint is gated:
#   make openapi-export TOKEN=xxx
PORT ?= 8800
TOKEN ?=
openapi-export:
	@if [ -n "$(TOKEN)" ]; then \
	    curl -sf -H "Authorization: Bearer $(TOKEN)" http://127.0.0.1:$(PORT)/openapi.json -o openapi.json; \
	else \
	    curl -sf http://127.0.0.1:$(PORT)/openapi.json -o openapi.json; \
	fi
	@echo "Wrote openapi.json ($$(wc -c < openapi.json) bytes)"

restart-brain:
	launchctl kickstart -k "gui/$(shell id -u)/com.resonanceenergy.ncl-brain"

tail-log:
	tail -f /Users/natrix/dev/NCL/logs/ncl-brain-stderr.log
