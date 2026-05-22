from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser
import httpx

from .db import transaction

log = logging.getLogger(__name__)

USER_AGENT = "rssx/0.1 (+https://github.com/d-issy/rssx)"


@dataclass
class FetchConfig:
    min_interval_sec: int = 10 * 60
    max_interval_sec: int = 24 * 60 * 60
    initial_interval_sec: int = 30 * 60
    history_window: int = 15
    interval_factor: float = 0.5
    empty_backoff_factor: float = 1.5


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_struct_time(st) -> datetime | None:
    if not st:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(st), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def make_guid(entry) -> str:
    for key in ("id", "guid", "link"):
        value = entry.get(key)
        if value:
            return str(value)
    raw = (entry.get("title", "") + entry.get("summary", "")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def extract_entry_fields(entry) -> dict:
    content_blocks = entry.get("content") or []
    content_html = ""
    if content_blocks:
        content_html = content_blocks[0].get("value", "") or ""
    summary = entry.get("summary", "") or ""
    if not content_html:
        content_html = summary

    return {
        "guid": make_guid(entry),
        "title": (entry.get("title") or "").strip(),
        "url": entry.get("link") or None,
        "author": entry.get("author") or None,
        "content": content_html,
        "summary": summary,
        "published_at": to_iso(
            parse_struct_time(entry.get("published_parsed"))
            or parse_struct_time(entry.get("updated_parsed"))
        ),
    }


def fetch_url(url: str, etag: str | None = None, last_modified: str | None = None) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        return client.get(url)


def probe_feed_title(url: str) -> tuple[str, str | None]:
    resp = fetch_url(url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.text)
    title = (parsed.feed.get("title") or url).strip()
    site_url = parsed.feed.get("link") or None
    return title, site_url


def compute_next_interval(
    published_times: list[datetime],
    consecutive_empty: int,
    cfg: FetchConfig,
) -> int:
    times = sorted([t for t in published_times if t is not None], reverse=True)
    if len(times) < 2:
        base = cfg.initial_interval_sec
    else:
        sample = times[: cfg.history_window]
        deltas = [
            (sample[i] - sample[i + 1]).total_seconds()
            for i in range(len(sample) - 1)
        ]
        deltas = [d for d in deltas if d > 0]
        if not deltas:
            base = cfg.initial_interval_sec
        else:
            avg = sum(deltas) / len(deltas)
            base = int(avg * cfg.interval_factor)

    if consecutive_empty > 0:
        base = int(base * (cfg.empty_backoff_factor ** consecutive_empty))

    return max(cfg.min_interval_sec, min(cfg.max_interval_sec, base))


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
                    to_iso(now_utc() + timedelta(seconds=cfg.min_interval_sec)),
                    feed_id,
                ),
            )
        return 0

    new_count = 0
    if resp.status_code == 304:
        log.info("not modified: %s", row["url"])
    else:
        parsed = feedparser.parse(resp.text)
        with transaction(conn):
            for entry in parsed.entries:
                fields = extract_entry_fields(entry)
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO entries
                            (feed_id, guid, title, url, author, content, summary, published_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            feed_id,
                            fields["guid"],
                            fields["title"],
                            fields["url"],
                            fields["author"],
                            fields["content"],
                            fields["summary"],
                            fields["published_at"],
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
        except (TypeError, ValueError):
            continue

    consecutive_empty = 0 if new_count > 0 else (
        (conn.execute("SELECT consecutive_empty FROM feeds WHERE id = ?", (feed_id,)).fetchone()["consecutive_empty"] or 0) + 1
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
        row["url"], new_count, next_interval, consecutive_empty,
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


def fetch_feed_ids(conn: sqlite3.Connection, feed_ids: Iterable[int], cfg: FetchConfig | None = None) -> int:
    total = 0
    for fid in feed_ids:
        total += fetch_feed(conn, fid, cfg)
    return total
