import logging
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from rssx.config import Config
from rssx.db import connect, init_schema
from rssx.lib.feeds.scheduling import FetchConfig
from rssx.usecases.feed_sync import fetch_all, fetch_due_feeds, fetch_feed

log = logging.getLogger(__name__)


class SyncKind(StrEnum):
    ALL = "all"
    DUE = "due"
    FEED = "feed"


@dataclass(frozen=True)
class SyncRequest:
    kind: SyncKind
    feed_id: str | None = None


@dataclass(frozen=True)
class SyncEvent:
    message: str
    error: str | None = None
    new_count: int = 0


class SyncWorker:
    def __init__(self, config: Config, fetch_cfg: FetchConfig) -> None:
        self.config = config
        self.fetch_cfg = fetch_cfg
        self.requests: queue.Queue[SyncRequest] = queue.Queue()
        self.events: queue.Queue[SyncEvent] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="rssx-sync")

    def start(self) -> None:
        self._thread.start()
        self.refresh_all()

    def stop(self) -> None:
        self._stop.set()
        self.requests.put(SyncRequest(SyncKind.DUE))
        self._thread.join(timeout=2)

    def refresh_all(self) -> None:
        self.requests.put(SyncRequest(SyncKind.ALL))

    def refresh_feed(self, feed_id: str) -> None:
        self.requests.put(SyncRequest(SyncKind.FEED, feed_id))

    def poll_events(self) -> list[SyncEvent]:
        items: list[SyncEvent] = []
        while True:
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                return items

    def _connect(self) -> sqlite3.Connection:
        conn = connect(self.config.db_path)
        init_schema(conn)
        return conn

    def _run(self) -> None:
        next_due = 0.0
        while not self._stop.is_set():
            timeout = max(0.0, next_due - time.monotonic()) if next_due else 0.0
            try:
                req = self.requests.get(timeout=timeout if timeout else 0.1)
            except queue.Empty:
                req = SyncRequest(SyncKind.DUE)
            if self._stop.is_set():
                break
            if req.kind is SyncKind.DUE and next_due and time.monotonic() < next_due:
                continue
            try:
                conn = self._connect()
                try:
                    if req.kind is SyncKind.ALL:
                        count = fetch_all(conn, self.fetch_cfg)
                        self.events.put(SyncEvent(f"全フィード更新完了: +{count}", new_count=count))
                    elif req.kind is SyncKind.FEED and req.feed_id:
                        count = fetch_feed(conn, req.feed_id, self.fetch_cfg)
                        self.events.put(SyncEvent(f"フィード更新完了: +{count}", new_count=count))
                    else:
                        count = fetch_due_feeds(conn, self.fetch_cfg)
                        if count:
                            self.events.put(SyncEvent(f"定期更新完了: +{count}", new_count=count))
                finally:
                    conn.close()
            except Exception as e:
                log.exception("sync failed")
                self.events.put(SyncEvent("更新に失敗しました", error=str(e)))
            next_due = time.monotonic() + self.config.scheduler_tick_min * 60
