import logging
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from rssx import repository as repo
from rssx.lib.feeds.client import fetch_url
from rssx.lib.feeds.parser import parse_feed
from rssx.lib.feeds.scheduling import FetchConfig, compute_next_interval

log = logging.getLogger(__name__)


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def probe_feed_title(url: str) -> tuple[str, str | None]:
    resp = fetch_url(url)
    resp.raise_for_status()
    parsed = parse_feed(resp.text, fallback_title=url, source_url=url)
    return parsed.title, parsed.site_url


def fetch_feed(conn: sqlite3.Connection, feed_id: int, cfg: FetchConfig | None = None) -> int:
    cfg = cfg or FetchConfig()
    feed = repo.get_feed_fetch_state(conn, feed_id)
    if feed is None:
        return 0

    try:
        resp = fetch_url(feed.url, feed.etag, feed.last_modified)
    except Exception as e:
        log.warning("fetch failed for feed %s: %s", feed.url, e)
        repo.record_feed_fetch_failure(
            conn,
            feed_id,
            error=str(e),
            fetched_at=to_iso(now_utc()) or "",
            next_fetch_at=to_iso(now_utc() + timedelta(minutes=cfg.min_interval_min)) or "",
        )
        return 0

    new_count = 0
    if resp.status_code == 304:
        log.info("not modified: %s", feed.url)
    else:
        parsed = parse_feed(resp.text, fallback_title=feed.url, source_url=feed.url)
        new_count = repo.store_fetched_entries(
            conn,
            feed_id,
            parsed.entries,
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
        )

    pub_times: list[datetime] = []
    for published_at in repo.list_recent_published_at(conn, feed_id, limit=cfg.history_window):
        try:
            pub_times.append(datetime.fromisoformat(published_at))
        except TypeError, ValueError:
            continue

    consecutive_empty = 0 if new_count > 0 else repo.get_consecutive_empty(conn, feed_id) + 1
    next_interval = compute_next_interval(pub_times, consecutive_empty, cfg)
    next_at = now_utc() + timedelta(seconds=next_interval)

    repo.record_feed_fetch_success(
        conn,
        feed_id,
        fetched_at=to_iso(now_utc()) or "",
        next_fetch_at=to_iso(next_at) or "",
        fetch_interval_sec=next_interval,
        consecutive_empty=consecutive_empty,
    )

    log.info(
        "feed %s: +%d entries, next in %ds (empty streak %d)",
        feed.url,
        new_count,
        next_interval,
        consecutive_empty,
    )
    return new_count


def fetch_due_feeds(conn: sqlite3.Connection, cfg: FetchConfig | None = None) -> int:
    total_new = 0
    for feed_id in repo.list_due_feed_ids(conn, now=to_iso(now_utc()) or ""):
        total_new += fetch_feed(conn, feed_id, cfg)
    return total_new


def fetch_all(conn: sqlite3.Connection, cfg: FetchConfig | None = None) -> int:
    total = 0
    for feed_id in repo.list_feed_ids(conn):
        total += fetch_feed(conn, feed_id, cfg)
    return total


def fetch_feed_ids(
    conn: sqlite3.Connection, feed_ids: Iterable[int], cfg: FetchConfig | None = None
) -> int:
    total = 0
    for feed_id in feed_ids:
        total += fetch_feed(conn, feed_id, cfg)
    return total
