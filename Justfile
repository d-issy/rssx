default:
    @just --list

# Start the TUI
run:
    uv run rssx

# Run unit tests
test:
    uv run pytest

cov:
    uv run pytest --cov

# Lint TUI
lint:
    uv run ruff check
    uv run ruff format --check
    uv run mypy

# Auto-format and auto-fix Python + JSON + Nix
fmt:
    treefmt

# Connect to the SQLite database
db db_path="${XDG_DATA_HOME:-$HOME/.local/share}/rssx/rssx.db":
    sqlite3 {{db_path}}
