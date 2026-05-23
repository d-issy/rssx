default:
    @just --list

# Start the server (expects the frontend bundle to already exist)
run:
    uv run rssx

# Start the dev server: server reload + frontend watch, in parallel
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT INT TERM
    RSSX_DEV=1 uv run rssx &
    pnpm dev &
    wait -n

# Lint everything (backend + frontend)
lint: lint-backend lint-frontend

# Lint backend: ruff + mypy
lint-backend:
    uv run ruff check
    uv run ruff format --check
    uv run mypy

# Lint frontend: oxlint + tsc
lint-frontend:
    pnpm exec oxlint
    pnpm typecheck

# Auto-format and auto-fix everything (Python + TS + JSON + Nix)
fmt:
    treefmt

# Connect to the SQLite database
db db_path="${XDG_DATA_HOME:-$HOME/.local/share}/rssx/rssx.db":
    sqlite3 {{db_path}}
