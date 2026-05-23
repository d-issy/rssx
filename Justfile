default:
    @just --list

# Start the server
run:
    uv run rssx

# Start the dev server with hot reload (server restart + browser auto-reload)
dev:
    RSSX_DEV=1 uv run rssx

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

# Connect to the SQLite database
db db_path="${XDG_DATA_HOME:-$HOME/.local/share}/rssx/rssx.db":
    sqlite3 {{db_path}}
