from rssx.lib.feeds.parser import parse_feed


def test_parse_feed_resolves_relative_entry_content_urls() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <title>Example</title>
        <link>https://example.com/</link>
        <item>
          <guid>1</guid>
          <title>Entry</title>
          <link>https://example.com/posts/entry.html</link>
          <description><![CDATA[<img src="/greenteagc/timeline.png"><a href="/about">about</a>]]></description>
        </item>
      </channel>
    </rss>
    """

    parsed = parse_feed(xml, fallback_title="fallback", source_url="https://example.com/feed.xml")

    content = parsed.entries[0].content
    assert 'src="https://example.com/greenteagc/timeline.png"' in content
    assert 'href="https://example.com/about"' in content


def test_parse_feed_leaves_absolute_urls_unchanged() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <title>Example</title>
        <link>https://example.com/</link>
        <item>
          <guid>1</guid>
          <title>Entry</title>
          <link>https://example.com/posts/entry.html</link>
          <description><![CDATA[<img src="https://cdn.example.com/x.png">]]></description>
        </item>
      </channel>
    </rss>
    """

    parsed = parse_feed(xml, fallback_title="fallback", source_url="https://example.com/feed.xml")

    assert 'src="https://cdn.example.com/x.png"' in parsed.entries[0].content
