from pathlib import Path

import pytest
from factories import seed_feed

from rssx.db import connect, init_schema
from rssx.domain.events import DomainEvent
from rssx.lib.feeds.scheduling import FetchConfig
from rssx.usecases.manage_feeds import FeedManagementUseCases
from rssx.usecases.results import ApplicationError


def fetch_cfg() -> FetchConfig:
    return FetchConfig(min_interval_min=1, max_interval_min=2, initial_interval_min=1)


def test_create_feed_with_new_folder_is_unit_testable_without_http(db_path: Path) -> None:
    conn = connect(db_path)
    fetched: list[str] = []
    try:
        init_schema(conn)
        service = FeedManagementUseCases(
            conn,
            fetch_cfg(),
            fetch_feed_fn=lambda _conn, feed_id, _cfg: fetched.append(feed_id),
        )

        result = service.create_feed(
            url="https://example.com/new.xml",
            title="New Feed",
            folder_id="__new",
            new_folder_name="News",
        )

        assert result.feed_id
        assert fetched == [result.feed_id]
        assert result.events == (
            DomainEvent.FEED_ADDED,
            DomainEvent.COUNTS_CHANGED,
            DomainEvent.FEED_FOLDER_CHANGED,
        )
        assert conn.execute("SELECT name FROM folders").fetchone()["name"] == "News"
    finally:
        conn.close()


def test_duplicate_feed_does_not_create_requested_new_folder(db_path: Path) -> None:
    seed_feed(db_path, url="https://example.com/existing.xml")
    conn = connect(db_path)
    try:
        service = FeedManagementUseCases(conn, fetch_cfg(), fetch_feed_fn=lambda *_args: None)

        with pytest.raises(ApplicationError):
            service.create_feed(
                url="https://example.com/existing.xml",
                title="Duplicate",
                folder_id="__new",
                new_folder_name="Should Not Exist",
            )

        folder_names = [row["name"] for row in conn.execute("SELECT name FROM folders")]
        assert "Should Not Exist" not in folder_names
    finally:
        conn.close()


def test_edit_feed_reports_folder_changed_event_only_when_folder_changes(db_path: Path) -> None:
    folder_id, feed_id = seed_feed(db_path)
    assert folder_id is not None
    conn = connect(db_path)
    try:
        service = FeedManagementUseCases(conn, fetch_cfg(), fetch_feed_fn=lambda *_args: None)

        title_only = service.edit_feed(feed_id, title="Renamed")
        folder_edit = service.edit_feed(feed_id, folder_id="__none")

        assert title_only.events == (DomainEvent.COUNTS_CHANGED,)
        assert folder_edit.events == (DomainEvent.COUNTS_CHANGED, DomainEvent.FEED_FOLDER_CHANGED)
    finally:
        conn.close()
