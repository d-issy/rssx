import sqlite3
from collections.abc import Callable

from rssx.lib.feeds.scheduling import FetchConfig
from rssx.usecases.feed_sync import fetch_feed, probe_feed_title
from rssx.usecases.manage_feeds import FeedManagementUseCases
from rssx.usecases.manage_folders import FolderManagementUseCases
from rssx.usecases.results import FeedCreateResult, OperationResult


class ManageUseCases:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fetch_cfg: FetchConfig,
        *,
        probe_feed_title_fn: Callable[[str], tuple[str, str | None]] = probe_feed_title,
        fetch_feed_fn: Callable[[sqlite3.Connection, int, FetchConfig], object] = fetch_feed,
    ) -> None:
        self.folders = FolderManagementUseCases(conn)
        self.feeds = FeedManagementUseCases(
            conn,
            fetch_cfg,
            probe_feed_title_fn=probe_feed_title_fn,
            fetch_feed_fn=fetch_feed_fn,
        )

    def create_folder(self, name: str) -> OperationResult:
        return self.folders.create_folder(name)

    def rename_folder(self, folder_id: int, name: str) -> OperationResult:
        return self.folders.rename_folder(folder_id, name)

    def delete_folder(self, folder_id: int, mode: str) -> OperationResult:
        return self.folders.delete_folder(folder_id, mode)

    def create_feed(
        self,
        *,
        url: str,
        title: str = "",
        folder_id: str | None = None,
        new_folder_name: str | None = None,
    ) -> FeedCreateResult:
        return self.feeds.create_feed(
            url=url,
            title=title,
            folder_id=folder_id,
            new_folder_name=new_folder_name,
        )

    def delete_feed(self, feed_id: int) -> OperationResult:
        return self.feeds.delete_feed(feed_id)

    def edit_feed(
        self,
        feed_id: int,
        *,
        title: str | None = None,
        folder_id: str = "__unchanged",
    ) -> OperationResult:
        return self.feeds.edit_feed(feed_id, title=title, folder_id=folder_id)


# Temporary compatibility alias while call sites/tests migrate terminology.
ManageService = ManageUseCases
