import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id);

CREATE TABLE IF NOT EXISTS feeds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT    NOT NULL UNIQUE,
    title           TEXT    NOT NULL,
    site_url        TEXT,
    folder_id       INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    etag            TEXT,
    last_modified   TEXT,
    last_fetched_at TEXT,
    next_fetch_at   TEXT,
    fetch_interval_sec INTEGER NOT NULL DEFAULT 1800,
    consecutive_empty  INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feeds_folder ON feeds(folder_id);
CREATE INDEX IF NOT EXISTS idx_feeds_next_fetch ON feeds(next_fetch_at);

CREATE TABLE IF NOT EXISTS entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id      INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid         TEXT    NOT NULL,
    title        TEXT    NOT NULL DEFAULT '',
    url          TEXT,
    author       TEXT,
    content      TEXT    NOT NULL DEFAULT '',
    summary      TEXT    NOT NULL DEFAULT '',
    published_at TEXT,
    fetched_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    is_read      INTEGER NOT NULL DEFAULT 0,
    is_starred   INTEGER NOT NULL DEFAULT 0,
    read_at      TEXT,
    starred_at   TEXT,
    UNIQUE(feed_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_entries_feed_published ON entries(feed_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_entries_is_read ON entries(is_read);
CREATE INDEX IF NOT EXISTS idx_entries_is_starred ON entries(is_starred);
CREATE INDEX IF NOT EXISTS idx_entries_published ON entries(published_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, content, summary,
    content='entries',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, content, summary)
    VALUES (new.id, new.title, new.content, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, content, summary)
    VALUES ('delete', old.id, old.title, old.content, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, content, summary)
    VALUES ('delete', old.id, old.title, old.content, old.summary);
    INSERT INTO entries_fts(rowid, title, content, summary)
    VALUES (new.id, new.title, new.content, new.summary);
END;
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_fts_trigram(conn)


def _ensure_fts_trigram(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries_fts'"
    ).fetchone()
    if not row or "tokenize='trigram'" in (row[0] or ""):
        return
    with transaction(conn):
        conn.execute("DROP TABLE entries_fts")
        conn.execute(
            """
            CREATE VIRTUAL TABLE entries_fts USING fts5(
                title, content, summary,
                content='entries',
                content_rowid='id',
                tokenize='trigram'
            )
            """
        )
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
