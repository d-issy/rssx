# rssx

Self-hosted minimal RSS reader. Organize feeds in nested folders, navigate articles with the keyboard.

## Setup

```sh
nix develop
just run
```

Defaults to `http://localhost:8080`.

## Development

Common tasks are exposed via [`just`](https://github.com/casey/just):

| Recipe | Description |
| --- | --- |
| `just` | List available recipes |
| `just run` | Start the server |
| `just dev` | Start the dev server with hot reload |
| `just lint` | Run ruff check + format check + mypy |
| `just fmt` | Format code |
| `just fix` | Auto-fix lint issues and format |
| `just db [path]` | Open the SQLite database in `sqlite3` |

## Configuration

Optional `~/.config/rssx/config.toml`:

```toml
db_path = "~/.local/share/rssx/rssx.db"
host = "localhost"
port = 8080

[fetch]
min_interval_min = 10
max_interval_min = 1440
initial_interval_min = 30
scheduler_tick_min = 1
```

## Keybindings

| Key | Action |
| --- | --- |
| `j` / `k` | Select next / previous entry (expands inline) |
| `o` / Enter | Toggle expansion of the selected entry |
| `m` | Toggle read / unread |
| `f` | Toggle star |
| `v` | Open original article in a new tab |
| `r` | Refresh all feeds |
| `/` | Focus search box |
| `g` / `G` | Jump to first / last entry |
| `Esc` | Blur the search box |

An entry is marked read automatically after staying expanded for 2 seconds.
