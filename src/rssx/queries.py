from __future__ import annotations

import sqlite3
from typing import Any

from .db import transaction


def list_folders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, parent_id, position FROM folders ORDER BY parent_id, position, name"
    ).fetchall()


def build_folder_tree(folders: list[sqlite3.Row]) -> list[dict]:
    by_id: dict[int, dict] = {
        f["id"]: {"id": f["id"], "name": f["name"], "parent_id": f["parent_id"], "children": []}
        for f in folders
    }
    roots: list[dict] = []
    for node in by_id.values():
        parent = node["parent_id"]
        if parent is None or parent not in by_id:
            roots.append(node)
        else:
            by_id[parent]["children"].append(node)
    return roots


def list_feeds(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT f.id, f.url, f.title, f.site_url, f.folder_id, f.last_fetched_at,
               f.next_fetch_at, f.last_error,
               COALESCE(u.unread, 0) AS unread_count
        FROM feeds f
        LEFT JOIN (
            SELECT feed_id, COUNT(*) AS unread
            FROM entries WHERE is_read = 0 GROUP BY feed_id
        ) u ON u.feed_id = f.id
        ORDER BY LOWER(f.title)
        """
    ).fetchall()


def descendant_folder_ids(conn: sqlite3.Connection, folder_id: int) -> list[int]:
    ids = [folder_id]
    stack = [folder_id]
    while stack:
        current = stack.pop()
        rows = conn.execute(
            "SELECT id FROM folders WHERE parent_id = ?", (current,)
        ).fetchall()
        for r in rows:
            ids.append(r["id"])
            stack.append(r["id"])
    return ids


def get_unread_total(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM entries WHERE is_read = 0").fetchone()
    return row["c"] if row else 0


def get_starred_total(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM entries WHERE is_starred = 1").fetchone()
    return row["c"] if row else 0


def list_entries(
    conn: sqlite3.Connection,
    *,
    scope: str = "all",
    folder_id: int | None = None,
    feed_id: int | None = None,
    unread_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[sqlite3.Row]:
    where: list[str] = []
    params: list[Any] = []

    if scope == "starred":
        where.append("e.is_starred = 1")
    elif scope == "folder" and folder_id is not None:
        ids = descendant_folder_ids(conn, folder_id)
        placeholders = ",".join("?" for _ in ids)
        where.append(f"f.folder_id IN ({placeholders})")
        params.extend(ids)
    elif scope == "feed" and feed_id is not None:
        where.append("e.feed_id = ?")
        params.append(feed_id)

    if unread_only and scope != "starred":
        where.append("e.is_read = 0")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT e.id, e.feed_id, e.title, e.url, e.author, e.summary, e.published_at,
               e.is_read, e.is_starred, f.title AS feed_title
        FROM entries e
        JOIN feeds f ON f.id = e.feed_id
        {where_sql}
        ORDER BY COALESCE(e.published_at, e.fetched_at) DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return conn.execute(sql, params).fetchall()


def get_entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT e.*, f.title AS feed_title
        FROM entries e JOIN feeds f ON f.id = e.feed_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()


def mark_read(conn: sqlite3.Connection, entry_id: int, value: bool) -> None:
    with transaction(conn):
        if value:
            conn.execute(
                "UPDATE entries SET is_read = 1, read_at = datetime('now') WHERE id = ?",
                (entry_id,),
            )
        else:
            conn.execute(
                "UPDATE entries SET is_read = 0, read_at = NULL WHERE id = ?",
                (entry_id,),
            )


def toggle_star(conn: sqlite3.Connection, entry_id: int) -> bool:
    row = conn.execute("SELECT is_starred FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return False
    new_val = 0 if row["is_starred"] else 1
    with transaction(conn):
        conn.execute(
            "UPDATE entries SET is_starred = ?, starred_at = CASE WHEN ? THEN datetime('now') ELSE NULL END WHERE id = ?",
            (new_val, new_val, entry_id),
        )
    return bool(new_val)


def add_folder(conn: sqlite3.Connection, name: str, parent_id: int | None = None) -> int:
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO folders (name, parent_id) VALUES (?, ?)",
            (name.strip(), parent_id),
        )
    return cur.lastrowid


def delete_folder(conn: sqlite3.Connection, folder_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))


def add_feed(
    conn: sqlite3.Connection,
    *,
    url: str,
    title: str,
    site_url: str | None,
    folder_id: int | None,
) -> int:
    with transaction(conn):
        cur = conn.execute(
            """
            INSERT INTO feeds (url, title, site_url, folder_id)
            VALUES (?, ?, ?, ?)
            """,
            (url.strip(), title.strip(), site_url, folder_id),
        )
    return cur.lastrowid


def delete_feed(conn: sqlite3.Connection, feed_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))


def update_feed(
    conn: sqlite3.Connection,
    feed_id: int,
    *,
    title: str | None = None,
    folder_id: int | None = ...,  # sentinel: ... = don't change
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        sets.append("title = ?")
        params.append(title.strip())
    if folder_id is not ...:
        sets.append("folder_id = ?")
        params.append(folder_id)
    if not sets:
        return
    params.append(feed_id)
    with transaction(conn):
        conn.execute(f"UPDATE feeds SET {', '.join(sets)} WHERE id = ?", params)


def search_entries(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[sqlite3.Row]:
    if not query.strip():
        return []
    return conn.execute(
        """
        SELECT e.id, e.feed_id, e.title, e.url, e.summary, e.published_at,
               e.is_read, e.is_starred, f.title AS feed_title
        FROM entries_fts
        JOIN entries e ON e.id = entries_fts.rowid
        JOIN feeds f ON f.id = e.feed_id
        WHERE entries_fts MATCH ?
        ORDER BY COALESCE(e.published_at, e.fetched_at) DESC
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
