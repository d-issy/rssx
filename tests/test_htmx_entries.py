import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from rssx import queries as q
from rssx.app import create_app
from rssx.config import Config
from rssx.db import connect, init_schema


def seed_entry(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        init_schema(conn)
        feed_id = q.add_feed(
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


def make_client(db_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr("rssx.app.fetch_all", lambda *_args, **_kwargs: 0)
    return TestClient(create_app(Config(db_path=db_path)))


def hx_triggers(value: str) -> set[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(parsed, dict):
        return set(parsed)
    return set()


def test_entry_star_htmx_returns_updated_row_and_trigger(db_path: Path, monkeypatch) -> None:
    entry_id = seed_entry(db_path)

    with make_client(db_path, monkeypatch) as client:
        resp = client.post(f"/entries/{entry_id}/star", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert f'id="entry-{entry_id}"' in resp.text
    assert 'class="star on"' in resp.text
    assert "rssx:counts-changed" in hx_triggers(resp.headers["HX-Trigger"])

    conn = sqlite3.connect(db_path)
    try:
        assert (
            conn.execute("SELECT is_starred FROM entries WHERE id = ?", (entry_id,)).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_entry_read_htmx_returns_updated_row_and_trigger(db_path: Path, monkeypatch) -> None:
    entry_id = seed_entry(db_path)

    with make_client(db_path, monkeypatch) as client:
        resp = client.post(
            f"/entries/{entry_id}/read",
            params={"value": 1},
            headers={"HX-Request": "true"},
        )

    assert resp.status_code == 200
    assert f'id="entry-{entry_id}"' in resp.text
    assert 'class="entry read"' in resp.text
    assert "rssx:counts-changed" in hx_triggers(resp.headers["HX-Trigger"])

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
