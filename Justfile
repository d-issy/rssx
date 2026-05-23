default:
    @just --list

# Start the dev server
run:
    uv run rssx

# Run all checks (lint + format check + typecheck)
lint:
    uv run ruff check
    uv run ruff format --check
    uv run mypy

# Format code
fmt:
    uv run ruff format

# Auto-fix lint issues and format
fix:
    uv run ruff check --fix
    uv run ruff format
