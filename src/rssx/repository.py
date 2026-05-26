import sqlite3

from rssx.dto import (
    EntryDetail,
    EntryListItem,
    FeedFetchState,
    FeedListItem,
    FeedRef,
    FolderRow,
    FolderTreeNode,
    FolderWithCount,
)
from rssx.lib.feeds.models import ParsedEntry
from rssx.lib.time import parse_stored_datetime

from .db import transaction

SqlParam = str | int | float | bytes | None


def _folder_row(row: sqlite3.Row) -> FolderRow:
    return FolderRow(
        id=row["id"],
        name=row["name"],
        parent_id=row["parent_id"],
        position=row["position"],
    )


def _folder_with_count(row: sqlite3.Row) -> FolderWithCount:
    return FolderWithCount(
        id=row["id"],
        name=row["name"],
        parent_id=row["parent_id"],
        position=row["position"],
        feed_count=row["feed_count"],
    )


def _feed_list_item(row: sqlite3.Row) -> FeedListItem:
    return FeedListItem(
        id=row["id"],
        url=row["url"],
        title=row["title"],
        site_url=row["site_url"],
        folder_id=row["folder_id"],
        last_fetched_at=parse_stored_datetime(row["last_fetched_at"]),
        next_fetch_at=parse_stored_datetime(row["next_fetch_at"]),
        last_error=row["last_error"],
        unread_count=row["unread_count"],
    )


def _entry_list_item(row: sqlite3.Row) -> EntryListItem:
    return EntryListItem(
        id=row["id"],
        feed_id=row["feed_id"],
        title=row["title"],
        url=row["url"],
        author=row["author"],
        summary=row["summary"],
        published_at=parse_stored_datetime(row["published_at"]),
        is_read=bool(row["is_read"]),
        is_starred=bool(row["is_starred"]),
        feed_title=row["feed_title"],
    )


def _entry_detail(row: sqlite3.Row) -> EntryDetail:
    return EntryDetail(
        id=row["id"],
        feed_id=row["feed_id"],
        guid=row["guid"],
        title=row["title"],
        url=row["url"],
        author=row["author"],
        content=row["content"],
        summary=row["summary"],
        published_at=parse_stored_datetime(row["published_at"]),
        fetched_at=parse_stored_datetime(row["fetched_at"]),
        is_read=bool(row["is_read"]),
        is_starred=bool(row["is_starred"]),
        read_at=parse_stored_datetime(row["read_at"]),
        starred_at=parse_stored_datetime(row["starred_at"]),
        feed_title=row["feed_title"],
    )


def list_folders(conn: sqlite3.Connection) -> list[FolderRow]:
    rows = conn.execute(
        "SELECT id, name, parent_id, position FROM folders ORDER BY parent_id, position, name"
    ).fetchall()
    return [_folder_row(r) for r in rows]


def build_folder_tree(folders: list[FolderRow]) -> list[FolderTreeNode]:
    by_id = {f.id: FolderTreeNode(id=f.id, name=f.name, parent_id=f.parent_id) for f in folders}
    roots: list[FolderTreeNode] = []
    for node in by_id.values():
        parent = node.parent_id
        if parent is None or parent not in by_id:
            roots.append(node)
        else:
            by_id[parent].children.append(node)
    return roots


def build_sidebar_tree(
    folders: list[FolderRow],
    feeds: list[FeedListItem],
) -> tuple[list[FolderTreeNode], list[FeedListItem], int]:
    by_id = {f.id: FolderTreeNode(id=f.id, name=f.name, parent_id=f.parent_id) for f in folders}

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

    orphan_feeds: list[FeedListItem] = []
    for feed in feeds:
        fid = feed.folder_id
        if fid is not None and fid in by_id:
            by_id[fid].feeds.append(feed)
        else:
            orphan_feeds.append(feed)

    def aggregate(node: FolderTreeNode) -> int:
        total = sum(f.unread_count for f in node.feeds)
        for child in node.children:
            total += aggregate(child)
        node.unread_count = total
        return total

    for root in roots:
        aggregate(root)

    orphan_unread = sum(f.unread_count for f in orphan_feeds)
    return roots, orphan_feeds, orphan_unread


def list_feeds(conn: sqlite3.Connection) -> list[FeedListItem]:
    rows = conn.execute(
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
    return [_feed_list_item(r) for r in rows]


def list_feeds_filtered(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    folder_ids: list[int] | None = None,
    include_orphan: bool = True,
) -> list[FeedListItem]:
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
    rows = conn.execute(sql, params).fetchall()
    return [_feed_list_item(r) for r in rows]


def list_folders_with_counts(conn: sqlite3.Connection) -> list[FolderWithCount]:
    rows = conn.execute(
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
    return [_folder_with_count(r) for r in rows]


def get_folder(conn: sqlite3.Connection, folder_id: int) -> FolderWithCount | None:
    row = conn.execute(
        """
        SELECT fo.id, fo.name, fo.parent_id, fo.position,
               COALESCE((SELECT COUNT(*) FROM feeds WHERE folder_id = fo.id), 0) AS feed_count
        FROM folders fo WHERE fo.id = ?
        """,
        (folder_id,),
    ).fetchone()
    return _folder_with_count(row) if row else None


def get_feed(conn: sqlite3.Connection, feed_id: int) -> FeedListItem | None:
    row = conn.execute(
        """
        SELECT f.id, f.url, f.title, f.site_url, f.folder_id, f.last_fetched_at,
               f.next_fetch_at, f.last_error,
               COALESCE((SELECT COUNT(*) FROM entries WHERE feed_id = f.id AND is_read = 0), 0)
                   AS unread_count
        FROM feeds f WHERE f.id = ?
        """,
        (feed_id,),
    ).fetchone()
    return _feed_list_item(row) if row else None


def get_feed_by_url(conn: sqlite3.Connection, url: str) -> FeedRef | None:
    row = conn.execute(
        "SELECT id, title FROM feeds WHERE url = ?",
        (url,),
    ).fetchone()
    return FeedRef(id=row["id"], title=row["title"]) if row else None


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
) -> list[EntryListItem]:
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
    rows = conn.execute(sql, params).fetchall()
    return [_entry_list_item(r) for r in rows]


def get_entry(conn: sqlite3.Connection, entry_id: int) -> EntryDetail | None:
    row = conn.execute(
        """
        SELECT e.*, f.title AS feed_title
        FROM entries e JOIN feeds f ON f.id = e.feed_id
        WHERE e.id = ?
        """,
        (entry_id,),
    ).fetchone()
    return _entry_detail(row) if row else None


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
            "UPDATE entries SET is_starred = :new_val, "
            "starred_at = CASE WHEN :new_val THEN datetime('now') ELSE NULL END "
            "WHERE id = :entry_id",
            {"new_val": new_val, "entry_id": entry_id},
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
            VALUES (:url, :title, :site_url, :folder_id)
            """,
            {
                "url": url.strip(),
                "title": title.strip(),
                "site_url": site_url,
                "folder_id": folder_id,
            },
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
            "UPDATE feeds SET last_error = :error, "
            "last_fetched_at = :fetched_at, next_fetch_at = :next_fetch_at "
            "WHERE id = :feed_id",
            {
                "error": error,
                "fetched_at": fetched_at,
                "next_fetch_at": next_fetch_at,
                "feed_id": feed_id,
            },
        )


def insert_parsed_entry(conn: sqlite3.Connection, feed_id: int, entry: ParsedEntry) -> bool:
    try:
        cur = conn.execute(
            """
            INSERT INTO entries
                (feed_id, guid, title, url, author, content, summary, published_at)
            VALUES
                (:feed_id, :guid, :title, :url, :author, :content, :summary, :published_at)
            """,
            {
                "feed_id": feed_id,
                "guid": entry.guid,
                "title": entry.title,
                "url": entry.url,
                "author": entry.author,
                "content": entry.content,
                "summary": entry.summary,
                "published_at": entry.published_at,
            },
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
            "UPDATE feeds SET etag = :etag, last_modified = :last_modified WHERE id = :feed_id",
            {"etag": etag, "last_modified": last_modified, "feed_id": feed_id},
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
            "UPDATE feeds SET last_fetched_at = :fetched_at, "
            "next_fetch_at = :next_fetch_at, "
            "fetch_interval_sec = :fetch_interval_sec, "
            "consecutive_empty = :consecutive_empty, "
            "last_error = NULL "
            "WHERE id = :feed_id",
            {
                "fetched_at": fetched_at,
                "next_fetch_at": next_fetch_at,
                "fetch_interval_sec": fetch_interval_sec,
                "consecutive_empty": consecutive_empty,
                "feed_id": feed_id,
            },
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


def search_entries(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[EntryListItem]:
    q = query.strip()
    if not q:
        return []
    if len(q) < 3:
        like_pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = conn.execute(
            """
            SELECT e.id, e.feed_id, e.title, e.url, e.author, e.summary, e.published_at,
                   e.is_read, e.is_starred, f.title AS feed_title
            FROM entries e
            JOIN feeds f ON f.id = e.feed_id
            WHERE e.title LIKE :like_pattern ESCAPE '\\'
               OR e.summary LIKE :like_pattern ESCAPE '\\'
               OR e.content LIKE :like_pattern ESCAPE '\\'
            ORDER BY COALESCE(e.published_at, e.fetched_at) DESC
            LIMIT :limit
            """,
            {"like_pattern": like_pattern, "limit": limit},
        ).fetchall()
        return [_entry_list_item(r) for r in rows]
    phrase = '"' + q.replace('"', '""') + '"'
    rows = conn.execute(
        """
        SELECT e.id, e.feed_id, e.title, e.url, e.author, e.summary, e.published_at,
               e.is_read, e.is_starred, f.title AS feed_title
        FROM entries_fts
        JOIN entries e ON e.id = entries_fts.rowid
        JOIN feeds f ON f.id = e.feed_id
        WHERE entries_fts MATCH :phrase
        ORDER BY COALESCE(e.published_at, e.fetched_at) DESC
        LIMIT :limit
        """,
        {"phrase": phrase, "limit": limit},
    ).fetchall()
    return [_entry_list_item(r) for r in rows]
