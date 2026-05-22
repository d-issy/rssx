# rssx

Self-hosted minimal RSS reader. Organize feeds in nested folders, navigate articles with the keyboard.

## Setup

```sh
nix develop
uv run rssx
```

Defaults to `http://0.0.0.0:8080`.

## Configuration

Optional `~/.config/rssx/config.toml`:

```toml
db_path = "~/.local/share/rssx/rssx.db"
host = "0.0.0.0"
port = 8080

[fetch]
min_interval_sec = 600
max_interval_sec = 86400
initial_interval_sec = 1800
scheduler_tick_sec = 60
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

## Fetching

On startup all feeds are fetched once. After that, each feed's next fetch time is derived from the average interval of its recent entries, clamped to `[min_interval_sec, max_interval_sec]`. Empty fetches back off exponentially. Manual refresh buttons are available in the top bar and per-feed on `/manage`.
