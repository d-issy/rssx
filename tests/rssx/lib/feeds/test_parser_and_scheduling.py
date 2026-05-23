from datetime import UTC, datetime

from rssx.lib.feeds.parser import parse_feed
from rssx.lib.feeds.scheduling import FetchConfig, compute_next_interval


def test_parse_feed_normalizes_feed_metadata_and_entries() -> None:
    parsed = parse_feed(
        """
        <rss version="2.0">
          <channel>
            <title> Example Feed </title>
            <link>https://example.com</link>
            <item>
              <guid>entry-1</guid>
              <title> Entry Title </title>
              <link>https://example.com/entry</link>
              <author>Alice</author>
              <description>Summary text</description>
              <pubDate>Mon, 15 Jan 2024 09:30:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """,
        fallback_title="fallback",
    )

    assert parsed.title == "Example Feed"
    assert parsed.site_url == "https://example.com"
    assert len(parsed.entries) == 1

    entry = parsed.entries[0]
    assert entry.guid == "entry-1"
    assert entry.title == "Entry Title"
    assert entry.url == "https://example.com/entry"
    assert entry.author == "Alice"
    assert entry.summary == "Summary text"
    assert entry.content == "Summary text"
    assert entry.published_at == "2024-01-15T09:30:00+00:00"


def test_parse_feed_falls_back_to_source_title_and_generated_guid() -> None:
    parsed = parse_feed(
        """
        <rss version="2.0">
          <channel>
            <item>
              <title>No guid</title>
              <description>Body</description>
            </item>
          </channel>
        </rss>
        """,
        fallback_title="https://example.com/feed.xml",
    )

    assert parsed.title == "https://example.com/feed.xml"
    assert parsed.site_url is None
    assert parsed.entries[0].guid.startswith("sha256:")


def test_compute_next_interval_uses_minutes_config_but_returns_seconds() -> None:
    cfg = FetchConfig(min_interval_min=10, max_interval_min=120, initial_interval_min=30)

    assert compute_next_interval([], consecutive_empty=0, cfg=cfg) == 30 * 60

    interval = compute_next_interval(
        [
            datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        ],
        consecutive_empty=0,
        cfg=cfg,
    )

    assert interval == 60 * 60
