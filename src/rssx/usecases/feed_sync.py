import logging
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from rssx.db import transaction
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
    parsed = parse_feed(resp.text, fallback_title=url)
    return parsed.title, parsed.site_url


def fetch_feed(conn: sqlite3.Connection, feed_id: int, cfg: FetchConfig | None = None) -> int:
    cfg = cfg or FetchConfig()
    row = conn.execute(
        "SELECT id, url, etag, last_modified FROM feeds WHERE id = ?", (feed_id,)
    ).fetchone()
    if not row:
        return 0

    try:
        resp = fetch_url(row["url"], row["etag"], row["last_modified"])
    except Exception as e:
        log.warning("fetch failed for feed %s: %s", row["url"], e)
        with transaction(conn):
            conn.execute(
                "UPDATE feeds SET last_error = ?, last_fetched_at = ?, "
                "next_fetch_at = ? WHERE id = ?",
                (
                    str(e),
                    to_iso(now_utc()),
                    to_iso(now_utc() + timedelta(minutes=cfg.min_interval_min)),
                    feed_id,
                ),
            )
        return 0

    new_count = 0
    if resp.status_code == 304:
        log.info("not modified: %s", row["url"])
    else:
        parsed = parse_feed(resp.text, fallback_title=row["url"])
        with transaction(conn):
            for entry in parsed.entries:
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO entries
                            (feed_id, guid, title, url, author, content, summary, published_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            feed_id,
                            entry.guid,
                            entry.title,
                            entry.url,
                            entry.author,
                            entry.content,
                            entry.summary,
                            entry.published_at,
                        ),
                    )
                    if cur.rowcount > 0:
                        new_count += 1
                except sqlite3.IntegrityError:
                    continue

            etag = resp.headers.get("etag")
            last_modified = resp.headers.get("last-modified")
            if etag or last_modified:
                conn.execute(
                    "UPDATE feeds SET etag = ?, last_modified = ? WHERE id = ?",
                    (etag, last_modified, feed_id),
                )

    rows = conn.execute(
        "SELECT published_at FROM entries WHERE feed_id = ? AND published_at IS NOT NULL "
        "ORDER BY published_at DESC LIMIT ?",
        (feed_id, cfg.history_window),
    ).fetchall()
    pub_times: list[datetime] = []
    for r in rows:
        try:
            pub_times.append(datetime.fromisoformat(r["published_at"]))
        except TypeError, ValueError:
            continue

    consecutive_empty = (
        0
        if new_count > 0
        else (
            (
                conn.execute(
                    "SELECT consecutive_empty FROM feeds WHERE id = ?", (feed_id,)
                ).fetchone()["consecutive_empty"]
                or 0
            )
            + 1
        )
    )
    next_interval = compute_next_interval(pub_times, consecutive_empty, cfg)
    next_at = now_utc() + timedelta(seconds=next_interval)

    with transaction(conn):
        conn.execute(
            "UPDATE feeds SET last_fetched_at = ?, next_fetch_at = ?, "
            "fetch_interval_sec = ?, consecutive_empty = ?, last_error = NULL "
            "WHERE id = ?",
            (to_iso(now_utc()), to_iso(next_at), next_interval, consecutive_empty, feed_id),
        )

    log.info(
        "feed %s: +%d entries, next in %ds (empty streak %d)",
        row["url"],
        new_count,
        next_interval,
        consecutive_empty,
    )
    return new_count


def fetch_due_feeds(conn: sqlite3.Connection, cfg: FetchConfig | None = None) -> int:
    rows = conn.execute(
        "SELECT id FROM feeds WHERE next_fetch_at IS NULL OR next_fetch_at <= ?",
        (to_iso(now_utc()),),
    ).fetchall()
    total_new = 0
    for r in rows:
        total_new += fetch_feed(conn, r["id"], cfg)
    return total_new


def fetch_all(conn: sqlite3.Connection, cfg: FetchConfig | None = None) -> int:
    rows = conn.execute("SELECT id FROM feeds").fetchall()
    total = 0
    for r in rows:
        total += fetch_feed(conn, r["id"], cfg)
    return total


def fetch_feed_ids(
    conn: sqlite3.Connection, feed_ids: Iterable[int], cfg: FetchConfig | None = None
) -> int:
    total = 0
    for fid in feed_ids:
        total += fetch_feed(conn, fid, cfg)
    return total
