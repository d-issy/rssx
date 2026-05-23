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


def build_sidebar_tree(
    folders: list[sqlite3.Row], feeds: list[sqlite3.Row]
) -> tuple[list[dict], list[sqlite3.Row], int]:
    by_id: dict[int, dict] = {
        f["id"]: {
            "id": f["id"],
            "name": f["name"],
            "parent_id": f["parent_id"],
            "children": [],
            "feeds": [],
            "unread_count": 0,
        }
        for f in folders
    }

    def in_cycle(nid: int) -> bool:
        seen: set[int] = set()
        cur: int | None = nid
        while cur is not None and cur in by_id:
            if cur in seen:
                return True
            seen.add(cur)
            cur = by_id[cur]["parent_id"]
        return False

    roots: list[dict] = []
    for node in by_id.values():
        parent = node["parent_id"]
        if parent is None or parent not in by_id or in_cycle(node["id"]):
            roots.append(node)
        else:
            by_id[parent]["children"].append(node)

    orphan_feeds: list[sqlite3.Row] = []
    for feed in feeds:
        fid = feed["folder_id"]
        if fid is not None and fid in by_id:
            by_id[fid]["feeds"].append(feed)
        else:
            orphan_feeds.append(feed)

    def aggregate(node: dict) -> int:
        total: int = sum(int(f["unread_count"]) for f in node["feeds"])
        for child in node["children"]:
            total += aggregate(child)
        node["unread_count"] = total
        return total

    for root in roots:
        aggregate(root)

    orphan_unread = sum(int(f["unread_count"]) for f in orphan_feeds)
    return roots, orphan_feeds, orphan_unread


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
        rows = conn.execute("SELECT id FROM folders WHERE parent_id = ?", (current,)).fetchall()
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
    elif scope == "orphan":
        where.append("f.folder_id IS NULL")
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
    row: sqlite3.Row | None = conn.execute(
        """
        SELECT e.*, f.title AS feed_title
        FROM entries e JOIN feeds f ON f.id = e.feed_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    return row


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
    assert cur.lastrowid is not None
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
    assert cur.lastrowid is not None
    return cur.lastrowid


def delete_feed(conn: sqlite3.Connection, feed_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))


def update_feed_title(conn: sqlite3.Connection, feed_id: int, title: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE feeds SET title = ? WHERE id = ?", (title.strip(), feed_id))


def update_feed_folder(conn: sqlite3.Connection, feed_id: int, folder_id: int | None) -> None:
    with transaction(conn):
        conn.execute("UPDATE feeds SET folder_id = ? WHERE id = ?", (folder_id, feed_id))


def search_entries(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[sqlite3.Row]:
    q = query.strip()
    if not q:
        return []
    if len(q) < 3:
        pat = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        return conn.execute(
            """
            SELECT e.id, e.feed_id, e.title, e.url, e.summary, e.published_at,
                   e.is_read, e.is_starred, f.title AS feed_title
            FROM entries e
            JOIN feeds f ON f.id = e.feed_id
            WHERE e.title LIKE ? ESCAPE '\\'
               OR e.summary LIKE ? ESCAPE '\\'
               OR e.content LIKE ? ESCAPE '\\'
            ORDER BY COALESCE(e.published_at, e.fetched_at) DESC
            LIMIT ?
            """,
            (pat, pat, pat, limit),
        ).fetchall()
    phrase = '"' + q.replace('"', '""') + '"'
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
        (phrase, limit),
    ).fetchall()
