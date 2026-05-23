import sqlite3
from pathlib import Path

from factories import seed_entry
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


def test_missing_entry_fragment_returns_404(client: TestClient) -> None:
    resp = client.get("/entries/9999")

    assert resp.status_code == 404
