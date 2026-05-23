import json
from pathlib import Path

from fastapi.testclient import TestClient

from rssx import queries as q
from rssx.app import create_app
from rssx.config import Config
from rssx.db import connect, init_schema


def seed_feed(db_path: Path) -> tuple[int, int]:
    conn = connect(db_path)
    try:
        init_schema(conn)
        folder_id = q.add_folder(conn, "Tech")
        feed_id = q.add_feed(
            conn,
            url="https://example.com/feed.xml",
            title="Example Feed",
            site_url="https://example.com",
            folder_id=folder_id,
        )
        return folder_id, feed_id
    finally:
        conn.close()


def test_manage_htmx_returns_dialog_fragment(client: TestClient) -> None:
    resp = client.get("/manage", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "管理" in resp.text
    assert 'id="manage-search-input"' in resp.text
    assert 'hx-get="/manage/feeds"' in resp.text
    assert 'hx-target="#manage-feed-list"' in resp.text


def test_manage_feed_list_contains_htmx_edit_contract(db_path: Path, monkeypatch) -> None:
    folder_id, feed_id = seed_feed(db_path)
    monkeypatch.setattr("rssx.app.fetch_all", lambda *_args, **_kwargs: 0)
    app = create_app(Config(db_path=db_path))

    with TestClient(app) as client:
        resp = client.get("/manage/feeds", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert f'id="manage-feed-{feed_id}"' in resp.text
    assert f'hx-post="/feeds/{feed_id}/edit"' in resp.text
    assert f'hx-target="#manage-feed-{feed_id}"' in resp.text
    assert 'hx-swap="outerHTML"' in resp.text
    assert f'<option value="{folder_id}" selected>Tech</option>' in resp.text


def test_feed_folder_edit_returns_row_and_hx_triggers(db_path: Path, monkeypatch) -> None:
    _, feed_id = seed_feed(db_path)
    monkeypatch.setattr("rssx.app.fetch_all", lambda *_args, **_kwargs: 0)
    app = create_app(Config(db_path=db_path))

    with TestClient(app) as client:
        resp = client.post(
            f"/feeds/{feed_id}/edit",
            data={"folder_id": "__none"},
            headers={"HX-Request": "true"},
        )

    assert resp.status_code == 200
    assert f'id="manage-feed-{feed_id}"' in resp.text
    assert f'hx-post="/feeds/{feed_id}/edit"' in resp.text
    triggers = json.loads(resp.headers["HX-Trigger"])
    assert "rssx:counts-changed" in triggers
    assert "rssx:feed-folder-changed" in triggers


def test_folder_create_htmx_returns_folder_list_and_trigger(client: TestClient) -> None:
    resp = client.post(
        "/folders",
        data={"name": "News"},
        headers={"HX-Request": "true"},
    )

    assert resp.status_code == 200
    assert "News" in resp.text
    assert 'class="manage-folder-row"' in resp.text
    triggers = json.loads(resp.headers["HX-Trigger"])
    assert "rssx:counts-changed" in triggers
