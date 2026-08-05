set quiet

default:
    @just --list

# Start the TUI
run:
    go run -tags libsqlite3 ./cmd/rssx

# Run unit tests
test:
    go test -tags libsqlite3 ./...

# Run static analysis and formatting checks
lint:
    golangci-lint run ./...
    treefmt --fail-on-change

# Auto-format Go and Nix
fmt:
    treefmt

# Connect to the SQLite database
db db_path="${XDG_DATA_HOME:-$HOME/.local/share}/rssx/rssx.db":
    sqlite3 {{db_path}}
