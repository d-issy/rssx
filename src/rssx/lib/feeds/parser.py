import calendar
import hashlib
from datetime import UTC, datetime
from time import struct_time

import feedparser

from rssx.lib.feeds.models import ParsedEntry, ParsedFeed
from rssx.lib.html import absolutize_html_urls


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def _parse_struct_time(st: object) -> datetime | None:
    if isinstance(st, struct_time):
        value: tuple[int, ...] | struct_time = st
    elif isinstance(st, tuple) and all(isinstance(part, int) for part in st):
        value = st
    else:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
    except TypeError, ValueError, OverflowError:
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _make_guid(entry: feedparser.FeedParserDict) -> str:
    for key in ("id", "guid", "link"):
        value = entry.get(key)
        if value:
            return str(value)
    raw = (_str_or_empty(entry.get("title")) + _str_or_empty(entry.get("summary"))).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _content_html(entry: feedparser.FeedParserDict) -> str:
    content_blocks = entry.get("content")
    if isinstance(content_blocks, list) and content_blocks:
        first = content_blocks[0]
        if isinstance(first, dict):
            value = first.get("value")
            if isinstance(value, str) and value:
                return value
    return _str_or_empty(entry.get("summary"))


def parse_entry(entry: feedparser.FeedParserDict, *, base_url: str | None = None) -> ParsedEntry:
    url = _optional_str(entry.get("link"))
    html_base = url or base_url
    summary = absolutize_html_urls(_str_or_empty(entry.get("summary")), html_base)
    return ParsedEntry(
        guid=_make_guid(entry),
        title=_str_or_empty(entry.get("title")).strip(),
        url=url,
        author=_optional_str(entry.get("author")),
        content=absolutize_html_urls(_content_html(entry), html_base),
        summary=summary,
        published_at=_to_iso(
            _parse_struct_time(entry.get("published_parsed"))
            or _parse_struct_time(entry.get("updated_parsed"))
        ),
    )


def parse_feed(text: str, *, fallback_title: str, base_url: str | None = None) -> ParsedFeed:
    parsed = feedparser.parse(text)
    title = (_optional_str(parsed.feed.get("title")) or fallback_title).strip()
    site_url = _optional_str(parsed.feed.get("link"))
    return ParsedFeed(
        title=title,
        site_url=site_url,
        entries=[parse_entry(entry, base_url=site_url or base_url) for entry in parsed.entries],
    )
