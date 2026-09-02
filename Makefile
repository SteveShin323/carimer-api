.PHONY: install lint fmt type test live smoke health all

install:
	uv venv --python 3.12
	uv pip install -e ".[dev]"

lint:
	.venv/bin/ruff check src tests scripts examples
	.venv/bin/ruff format --check src tests scripts examples

fmt:
	.venv/bin/ruff format src tests scripts examples
	.venv/bin/ruff check --fix src tests scripts examples

type:
	.venv/bin/mypy

test:
	.venv/bin/pytest -m "not live" tests/unit

live:
	.venv/bin/pytest -m live tests/live

smoke:
	.venv/bin/pytest -m "live and smoke" tests/live

health:
	.venv/bin/python scripts/health_check.py

all: lint type test
