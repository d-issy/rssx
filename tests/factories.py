from pathlib import Path

from rssx import repository as repo
from rssx.db import connect, init_schema


def seed_feed(
    db_path: Path,
    *,
    folder_name: str | None = "Tech",
    url: str = "https://example.com/feed.xml",
    title: str = "Example Feed",
) -> tuple[int | None, int]:
    conn = connect(db_path)
    try:
        init_schema(conn)
        folder_id = repo.add_folder(conn, folder_name) if folder_name is not None else None
        feed_id = repo.add_feed(
            conn,
            url=url,
            title=title,
            site_url="https://example.com",
            folder_id=folder_id,
        )
        return folder_id, feed_id
    finally:
        conn.close()


def seed_entry(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        init_schema(conn)
        feed_id = repo.add_feed(
            conn,
            url="https://example.com/feed.xml",
            title="Example Feed",
            site_url=None,
            folder_id=None,
        )
        cur = conn.execute(
            """
            INSERT INTO entries (feed_id, guid, title, url, summary, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                feed_id,
                "entry-1",
                "Entry title",
                "https://example.com/entry",
                "Entry summary",
                "2024-01-15T09:30:00+00:00",
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid
    finally:
        conn.close()
