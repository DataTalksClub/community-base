.PHONY: install lint format check test migrate-fresh

install:
	uv sync --all-extras

lint:
	uv run ruff check .

format:
	uv run ruff format .

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run python testproject/manage.py check
	uv run python testproject/manage.py makemigrations --check --dry-run
	uv run python testproject/manage.py openapi --check --output community_base/api/openapi.json

test:
	uv run pytest

migrate-fresh:
	rm -f testproject/db.sqlite3
	uv run python testproject/manage.py migrate
