.PHONY: install up down test lint eval-smoke eval-full demo

install:
	uv sync --group dev --no-cache

up:
	docker compose up -d

down:
	docker compose down

test:
	uv run pytest

lint:
	uv run ruff check src/
	uv run ruff format --check src/
	uv run mypy src/

eval-smoke:
	OFFLINE=1 uv run python evals/run.py

eval-full:
	uv run python evals/run.py

demo:
	OFFLINE=1 uv run python -m resolute.graph.build --demo
