import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from rssx import repository as repo
from rssx.domain.errors import DomainError
from rssx.domain.events import DomainEvent
from rssx.domain.value_objects import FeedUrl, FolderSelection
from rssx.lib.feeds.scheduling import FetchConfig
from rssx.usecases.feed_sync import fetch_feed, probe_feed_title
from rssx.usecases.results import ApplicationError, FeedCreateResult, OperationResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _FeedCreateData:
    url: FeedUrl
    title: str
    site_url: str | None
    folder_selection: FolderSelection

    @property
    def normalized_title(self) -> str:
        return self.title.strip()


class FeedManagementUseCases:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fetch_cfg: FetchConfig,
        *,
        probe_feed_title_fn: Callable[[str], tuple[str, str | None]] = probe_feed_title,
        fetch_feed_fn: Callable[[sqlite3.Connection, int, FetchConfig], object] = fetch_feed,
    ) -> None:
        self.conn = conn
        self.fetch_cfg = fetch_cfg
        self.probe_feed_title = probe_feed_title_fn
        self.fetch_feed = fetch_feed_fn

    def create_feed(
        self,
        *,
        url: str,
        title: str = "",
        folder_id: str | None = None,
        new_folder_name: str | None = None,
    ) -> FeedCreateResult:
        data = self._build_feed_create_data(
            url=url,
            title=title,
            folder_id=folder_id,
            new_folder_name=new_folder_name,
        )

        existing = repo.get_feed_by_url(self.conn, data.url.value)
        if existing:
            raise ApplicationError(f"このURLは既に登録されています: {existing['title']}")

        try:
            feed_id = repo.add_feed(
                self.conn,
                url=data.url.value,
                title=data.normalized_title,
                site_url=data.site_url,
                folder_id=data.folder_selection.folder_id,
            )
        except sqlite3.IntegrityError as e:
            raise ApplicationError("このURLは既に登録されています") from e

        if data.folder_selection.new_folder_name is not None:
            target_folder_id = repo.add_folder(
                self.conn,
                data.folder_selection.new_folder_name.value,
                None,
            )
            repo.update_feed_folder(self.conn, feed_id, target_folder_id)

        try:
            self.fetch_feed(self.conn, feed_id, self.fetch_cfg)
        except Exception:
            log.exception("initial fetch failed for new feed %s", data.url.value)

        return FeedCreateResult(
            events=(
                DomainEvent.FEED_ADDED,
                DomainEvent.COUNTS_CHANGED,
                DomainEvent.FEED_FOLDER_CHANGED,
            ),
            feed_id=feed_id,
        )

    def delete_feed(self, feed_id: int) -> OperationResult:
        repo.delete_feed(self.conn, feed_id)
        return OperationResult((DomainEvent.COUNTS_CHANGED, DomainEvent.FEED_FOLDER_CHANGED))

    def edit_feed(
        self,
        feed_id: int,
        *,
        title: str | None = None,
        folder_id: str = "__unchanged",
    ) -> OperationResult:
        events = [DomainEvent.COUNTS_CHANGED]
        if title is not None:
            repo.update_feed_title(self.conn, feed_id, title)
        if folder_id != "__unchanged":
            new_folder = None if folder_id == "__none" else int(folder_id)
            repo.update_feed_folder(self.conn, feed_id, new_folder)
            events.append(DomainEvent.FEED_FOLDER_CHANGED)
        return OperationResult(tuple(events))

    def _build_feed_create_data(
        self,
        *,
        url: str,
        title: str,
        folder_id: str | None,
        new_folder_name: str | None,
    ) -> _FeedCreateData:
        feed_url = self._to_application_error(lambda: FeedUrl.from_raw(url))
        selection = self._to_application_error(
            lambda: FolderSelection.from_form(folder_id, new_folder_name)
        )

        site_url: str | None = None
        resolved_title = title
        if not resolved_title.strip():
            try:
                resolved_title, site_url = self.probe_feed_title(feed_url.value)
            except Exception as e:
                raise ApplicationError(f"フィードを読み込めませんでした: {e}") from e

        return _FeedCreateData(
            url=feed_url,
            title=resolved_title,
            site_url=site_url,
            folder_selection=selection,
        )

    def _to_application_error[T](self, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except DomainError as e:
            raise ApplicationError(e.message) from e
