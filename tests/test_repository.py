from pathlib import Path

from rssx import repository as repo
from rssx.db import connect, init_schema


def setup_content(db_path: Path) -> tuple[int, int, int, int, int]:
    conn = connect(db_path)
    try:
        init_schema(conn)
        parent_id = repo.add_folder(conn, "Parent")
        child_id = repo.add_folder(conn, "Child", parent_id)
        parent_feed_id = repo.add_feed(
            conn,
            url="https://example.com/parent.xml",
            title="Parent Feed",
            site_url=None,
            folder_id=parent_id,
        )
        child_feed_id = repo.add_feed(
            conn,
            url="https://example.com/child.xml",
            title="Child Feed",
            site_url=None,
            folder_id=child_id,
        )
        orphan_feed_id = repo.add_feed(
            conn,
            url="https://example.com/orphan.xml",
            title="Orphan Feed",
            site_url=None,
            folder_id=None,
        )
        conn.executemany(
            """
            INSERT INTO entries (feed_id, guid, title, summary, published_at, is_read)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (parent_feed_id, "p1", "Parent unread", "alpha", "2024-01-15T10:00:00+00:00", 0),
                (parent_feed_id, "p2", "Parent read", "beta", "2024-01-14T10:00:00+00:00", 1),
                (child_feed_id, "c1", "Child unread", "gamma", "2024-01-16T10:00:00+00:00", 0),
                (orphan_feed_id, "o1", "Orphan unread", "delta", "2024-01-17T10:00:00+00:00", 0),
            ],
        )
        return parent_id, child_id, parent_feed_id, child_feed_id, orphan_feed_id
    finally:
        conn.close()


def test_sidebar_tree_aggregates_nested_unread_counts(db_path: Path) -> None:
    parent_id, child_id, _, _, orphan_feed_id = setup_content(db_path)
    conn = connect(db_path)
    try:
        tree, orphan_feeds, orphan_unread = repo.build_sidebar_tree(
            repo.list_folders(conn), repo.list_feeds(conn)
        )
    finally:
        conn.close()

    assert len(tree) == 1
    parent = tree[0]
    assert parent["id"] == parent_id
    assert parent["unread_count"] == 2
    assert parent["children"][0]["id"] == child_id
    assert parent["children"][0]["unread_count"] == 1
    assert [f["id"] for f in orphan_feeds] == [orphan_feed_id]
    assert orphan_unread == 1


def test_list_entries_filters_by_folder_descendants_and_unread(db_path: Path) -> None:
    parent_id, _, parent_feed_id, child_feed_id, orphan_feed_id = setup_content(db_path)
    conn = connect(db_path)
    try:
        rows = repo.list_entries(conn, scope="folder", folder_id=parent_id, unread_only=True)
    finally:
        conn.close()

    assert [row["feed_id"] for row in rows] == [child_feed_id, parent_feed_id]
    assert orphan_feed_id not in [row["feed_id"] for row in rows]


def test_list_feeds_filtered_can_select_only_orphans(db_path: Path) -> None:
    *_, orphan_feed_id = setup_content(db_path)
    conn = connect(db_path)
    try:
        rows = repo.list_feeds_filtered(conn, folder_ids=[], include_orphan=True)
    finally:
        conn.close()

    assert [row["id"] for row in rows] == [orphan_feed_id]


def test_mark_read_and_toggle_star_update_entry_state(db_path: Path) -> None:
    setup_content(db_path)
    conn = connect(db_path)
    try:
        entry = conn.execute("SELECT id FROM entries WHERE guid = 'p1'").fetchone()
        entry_id = entry["id"]

        repo.mark_read(conn, entry_id, True)
        assert (
            conn.execute(
                "SELECT is_read, read_at FROM entries WHERE id = ?", (entry_id,)
            ).fetchone()["is_read"]
            == 1
        )

        assert repo.toggle_star(conn, entry_id) is True
        row = conn.execute(
            "SELECT is_starred, starred_at FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        assert row["is_starred"] == 1
        assert row["starred_at"] is not None
    finally:
        conn.close()


def test_search_entries_falls_back_to_like_for_short_queries(db_path: Path) -> None:
    setup_content(db_path)
    conn = connect(db_path)
    try:
        rows = repo.search_entries(conn, "ga")
    finally:
        conn.close()

    assert [row["title"] for row in rows] == ["Child unread"]
