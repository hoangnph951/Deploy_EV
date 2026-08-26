.PHONY: run test lint format typecheck check clean

run:
	uvicorn src.apps.api.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

lint:
	ruff check apps/ packages/ tests/

format:
	ruff format apps/ packages/ tests/

typecheck:
	mypy apps/ packages/

check: lint format test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
