import sqlite3
from dataclasses import dataclass, field

from rssx.lib.feeds.models import ParsedEntry

from .db import transaction

SqlParam = str | int | float | bytes | None


@dataclass
class FolderTreeNode:
    id: int
    name: str
    parent_id: int | None
    children: list[FolderTreeNode] = field(default_factory=list)
    feeds: list[sqlite3.Row] = field(default_factory=list)
    unread_count: int = 0

    def __getitem__(self, key: str) -> object:
        """Compatibility for older tests/call sites that used dict-style nodes."""
        return getattr(self, key)


@dataclass(frozen=True)
class FeedFetchState:
    id: int
    url: str
    etag: str | None
    last_modified: str | None


def list_folders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, parent_id, position FROM folders ORDER BY parent_id, position, name"
    ).fetchall()


def build_folder_tree(folders: list[sqlite3.Row]) -> list[FolderTreeNode]:
    by_id = {
        f["id"]: FolderTreeNode(id=f["id"], name=f["name"], parent_id=f["parent_id"])
        for f in folders
    }
    roots: list[FolderTreeNode] = []
    for node in by_id.values():
        parent = node.parent_id
        if parent is None or parent not in by_id:
            roots.append(node)
        else:
            by_id[parent].children.append(node)
    return roots


def build_sidebar_tree(
    folders: list[sqlite3.Row],
    feeds: list[sqlite3.Row],
) -> tuple[list[FolderTreeNode], list[sqlite3.Row], int]:
    by_id = {
        f["id"]: FolderTreeNode(id=f["id"], name=f["name"], parent_id=f["parent_id"])
        for f in folders
    }

    def in_cycle(nid: int) -> bool:
        seen: set[int] = set()
        cur: int | None = nid
        while cur is not None and cur in by_id:
            if cur in seen:
                return True
            seen.add(cur)
            cur = by_id[cur].parent_id
        return False

    roots: list[FolderTreeNode] = []
    for node in by_id.values():
        parent = node.parent_id
        if parent is None or parent not in by_id or in_cycle(node.id):
            roots.append(node)
        else:
            by_id[parent].children.append(node)

    orphan_feeds: list[sqlite3.Row] = []
    for feed in feeds:
        fid = feed["folder_id"]
        if fid is not None and fid in by_id:
            by_id[fid].feeds.append(feed)
        else:
            orphan_feeds.append(feed)

    def aggregate(node: FolderTreeNode) -> int:
        total: int = sum(int(f["unread_count"]) for f in node.feeds)
        for child in node.children:
            total += aggregate(child)
        node.unread_count = total
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


def list_feeds_filtered(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    folder_ids: list[int] | None = None,
    include_orphan: bool = True,
) -> list[sqlite3.Row]:
    where: list[str] = []
    params: list[SqlParam] = []

    # folder_ids is None means "no folder filter applied at all" (show every feed).
    # Only when folder_ids is given do we narrow by folder / orphan.
    if folder_ids is not None:
        folder_clauses: list[str] = []
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            folder_clauses.append(f"f.folder_id IN ({placeholders})")
            params.extend(folder_ids)
        if include_orphan:
            folder_clauses.append("f.folder_id IS NULL")
        if folder_clauses:
            where.append("(" + " OR ".join(folder_clauses) + ")")
        else:
            where.append("1 = 0")

    q = query.strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(
            "(LOWER(f.title) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(f.url) LIKE LOWER(?) ESCAPE '\\' "
            "OR LOWER(COALESCE(f.site_url, '')) LIKE LOWER(?) ESCAPE '\\')"
        )
        params.extend([like, like, like])

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"""
        SELECT f.id, f.url, f.title, f.site_url, f.folder_id, f.last_fetched_at,
               f.next_fetch_at, f.last_error,
               COALESCE(u.unread, 0) AS unread_count
        FROM feeds f
        LEFT JOIN (
            SELECT feed_id, COUNT(*) AS unread
            FROM entries WHERE is_read = 0 GROUP BY feed_id
        ) u ON u.feed_id = f.id
        {where_sql}
        ORDER BY f.id DESC
    """
    return conn.execute(sql, params).fetchall()


def list_folders_with_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT fo.id, fo.name, fo.parent_id, fo.position,
               COALESCE(fc.cnt, 0) AS feed_count
        FROM folders fo
        LEFT JOIN (
            SELECT folder_id, COUNT(*) AS cnt FROM feeds
            WHERE folder_id IS NOT NULL
            GROUP BY folder_id
        ) fc ON fc.folder_id = fo.id
        ORDER BY LOWER(fo.name)
        """
    ).fetchall()


def get_folder(conn: sqlite3.Connection, folder_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        """
        SELECT fo.id, fo.name, fo.parent_id, fo.position,
               COALESCE((SELECT COUNT(*) FROM feeds WHERE folder_id = fo.id), 0) AS feed_count
        FROM folders fo WHERE fo.id = ?
        """,
        (folder_id,),
    ).fetchone()
    return row


def get_feed(conn: sqlite3.Connection, feed_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        """
        SELECT f.id, f.url, f.title, f.site_url, f.folder_id, f.last_fetched_at,
               f.next_fetch_at, f.last_error,
               COALESCE((SELECT COUNT(*) FROM entries WHERE feed_id = f.id AND is_read = 0), 0)
                   AS unread_count
        FROM feeds f WHERE f.id = ?
        """,
        (feed_id,),
    ).fetchone()
    return row


def get_feed_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, title FROM feeds WHERE url = ?",
        (url,),
    ).fetchone()
    return row


def get_feed_fetch_state(conn: sqlite3.Connection, feed_id: int) -> FeedFetchState | None:
    row = conn.execute(
        "SELECT id, url, etag, last_modified FROM feeds WHERE id = ?",
        (feed_id,),
    ).fetchone()
    if row is None:
        return None
    return FeedFetchState(
        id=row["id"],
        url=row["url"],
        etag=row["etag"],
        last_modified=row["last_modified"],
    )


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
    params: list[SqlParam] = []

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


def delete_folder_cascade(conn: sqlite3.Connection, folder_id: int) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM feeds WHERE folder_id = ?", (folder_id,))
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))


def rename_folder(conn: sqlite3.Connection, folder_id: int, name: str) -> None:
    with transaction(conn):
        conn.execute("UPDATE folders SET name = ? WHERE id = ?", (name.strip(), folder_id))


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


def record_feed_fetch_failure(
    conn: sqlite3.Connection,
    feed_id: int,
    *,
    error: str,
    fetched_at: str,
    next_fetch_at: str,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE feeds SET last_error = ?, last_fetched_at = ?, next_fetch_at = ? WHERE id = ?",
            (error, fetched_at, next_fetch_at, feed_id),
        )


def insert_parsed_entry(conn: sqlite3.Connection, feed_id: int, entry: ParsedEntry) -> bool:
    try:
        cur = conn.execute(
            """
            INSERT INTO entries
                (feed_id, guid, title, url, author, content, summary, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feed_id,
                entry.guid,
                entry.title,
                entry.url,
                entry.author,
                entry.content,
                entry.summary,
                entry.published_at,
            ),
        )
    except sqlite3.IntegrityError:
        return False
    return cur.rowcount > 0


def update_feed_cache_headers(
    conn: sqlite3.Connection,
    feed_id: int,
    *,
    etag: str | None,
    last_modified: str | None,
) -> None:
    if etag or last_modified:
        conn.execute(
            "UPDATE feeds SET etag = ?, last_modified = ? WHERE id = ?",
            (etag, last_modified, feed_id),
        )


def store_fetched_entries(
    conn: sqlite3.Connection,
    feed_id: int,
    entries: list[ParsedEntry],
    *,
    etag: str | None,
    last_modified: str | None,
) -> int:
    new_count = 0
    with transaction(conn):
        for entry in entries:
            if insert_parsed_entry(conn, feed_id, entry):
                new_count += 1
        update_feed_cache_headers(conn, feed_id, etag=etag, last_modified=last_modified)
    return new_count


def list_recent_published_at(conn: sqlite3.Connection, feed_id: int, *, limit: int) -> list[str]:
    rows = conn.execute(
        "SELECT published_at FROM entries WHERE feed_id = ? AND published_at IS NOT NULL "
        "ORDER BY published_at DESC LIMIT ?",
        (feed_id, limit),
    ).fetchall()
    return [row["published_at"] for row in rows]


def get_consecutive_empty(conn: sqlite3.Connection, feed_id: int) -> int:
    row = conn.execute(
        "SELECT consecutive_empty FROM feeds WHERE id = ?",
        (feed_id,),
    ).fetchone()
    if row is None:
        return 0
    return int(row["consecutive_empty"] or 0)


def record_feed_fetch_success(
    conn: sqlite3.Connection,
    feed_id: int,
    *,
    fetched_at: str,
    next_fetch_at: str,
    fetch_interval_sec: int,
    consecutive_empty: int,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE feeds SET last_fetched_at = ?, next_fetch_at = ?, "
            "fetch_interval_sec = ?, consecutive_empty = ?, last_error = NULL "
            "WHERE id = ?",
            (fetched_at, next_fetch_at, fetch_interval_sec, consecutive_empty, feed_id),
        )


def list_due_feed_ids(conn: sqlite3.Connection, *, now: str) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM feeds WHERE next_fetch_at IS NULL OR next_fetch_at <= ?",
        (now,),
    ).fetchall()
    return [row["id"] for row in rows]


def list_feed_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT id FROM feeds").fetchall()
    return [row["id"] for row in rows]


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
