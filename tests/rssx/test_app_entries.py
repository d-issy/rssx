import sqlite3
from pathlib import Path

from factories import seed_entry, seed_feed
from fastapi.testclient import TestClient

from rssx.app import create_app
from rssx.config import Config
from rssx.lib.htmx import HtmxEvent, trigger_names


def make_client(db_path: Path) -> TestClient:
    return TestClient(create_app(Config(db_path=db_path), run_startup_fetch=False))


def test_entry_star_htmx_returns_updated_row_and_trigger(db_path: Path) -> None:
    entry_id = seed_entry(db_path)

    with make_client(db_path) as client:
        resp = client.post(f"/entries/{entry_id}/star", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert f'id="entry-{entry_id}"' in resp.text
    assert 'class="star on"' in resp.text
    assert HtmxEvent.COUNTS_CHANGED in trigger_names(resp.headers["HX-Trigger"])

    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT is_starred FROM entries WHERE id = ?", (entry_id,)).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_entry_read_htmx_returns_updated_row_and_trigger(db_path: Path) -> None:
    entry_id = seed_entry(db_path)

    with make_client(db_path) as client:
        resp = client.post(
            f"/entries/{entry_id}/read",
            params={"value": 1},
            headers={"HX-Request": "true"},
        )

    assert resp.status_code == 200
    assert f'id="entry-{entry_id}"' in resp.text
    assert 'class="entry read"' in resp.text
    assert HtmxEvent.COUNTS_CHANGED in trigger_names(resp.headers["HX-Trigger"])

    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT is_read FROM entries WHERE id = ?", (entry_id,)).fetchone()[0] == 1
        )
    finally:
        conn.close()


def test_entry_read_scope_marks_current_feed(db_path: Path) -> None:
    _, feed_id = seed_feed(db_path)
    entry_id = "entry-in-feed"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO entries (id, feed_id, guid, title, summary, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_id, feed_id, "entry-in-feed", "Entry", "Summary", "2024-01-15T09:30:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    with make_client(db_path) as client:
        resp = client.post(
            "/entries/read-all",
            params={"scope": "feed", "feed": feed_id},
            headers={"HX-Request": "true"},
        )

    assert resp.status_code == 204
    assert HtmxEvent.COUNTS_CHANGED in trigger_names(resp.headers["HX-Trigger"])

    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT is_read FROM entries WHERE id = ?", (entry_id,)).fetchone()[0] == 1
        )
    finally:
        conn.close()


def test_missing_entry_fragment_returns_404(client: TestClient) -> None:
    resp = client.get("/entries/9999")

    assert resp.status_code == 404
