# rssx

Terminal RSS reader. Organize feeds in folders, sync them in the background, and read articles from a keyboard-first TUI.

## Setup

```sh
nix develop
just run
```

## Development

Common tasks are exposed via [`just`](https://github.com/casey/just):

| Recipe | Description |
| --- | --- |
| `just` | List available recipes |
| `just run` | Start the TUI |
| `just test` | Run unit tests |
| `just lint` | Run golangci-lint and formatting checks |
| `just fmt` | Format code |
| `just db [path]` | Open the SQLite database in `sqlite3` |

## Configuration

Optional `~/.config/rssx/config.toml`:

```toml
db_path = "~/.local/share/rssx/rssx.db"
state_path = "~/.local/state/rssx/state.toml"
timezone = "local"

[fetch]
min_interval_min = 10
max_interval_min = 1440
initial_interval_min = 30
scheduler_tick_min = 1
```

TUI state such as folder open/closed state is written to `state_path`.

## Keybindings

Press `?` in the TUI to view the keyboard shortcut list.
