from rssx.lib.feeds.parser import parse_feed
from rssx.lib.html import absolutize_html_urls


def test_absolutize_html_urls_resolves_root_relative_assets() -> None:
    html = '<p><img src="/greenteagc/greentea-075.png" srcset="/a.png 1x, /b.png 2x"></p>'

    actual = absolutize_html_urls(html, "https://example.com/posts/entry.html")

    assert actual == (
        '<p><img src="https://example.com/greenteagc/greentea-075.png" '
        'srcset="https://example.com/a.png 1x, https://example.com/b.png 2x"></p>'
    )


def test_absolutize_html_urls_keeps_absolute_and_data_urls() -> None:
    html = '<img src="https://cdn.example.com/x.png"><img src="data:image/png;base64,abc">'

    actual = absolutize_html_urls(html, "https://example.com/posts/entry.html")

    assert (
        actual == '<img src="https://cdn.example.com/x.png"><img src="data:image/png;base64,abc">'
    )


def test_parse_feed_absolutizes_entry_content_urls() -> None:
    xml = """
    <rss version="2.0">
      <channel>
        <title>Example</title>
        <link>https://example.com/</link>
        <item>
          <guid>1</guid>
          <title>Entry</title>
          <link>https://example.com/posts/entry.html</link>
          <description><![CDATA[<img src="/greenteagc/timeline.png">]]></description>
        </item>
      </channel>
    </rss>
    """

    parsed = parse_feed(xml, fallback_title="fallback", base_url="https://example.com/feed.xml")

    assert parsed.entries[0].content == '<img src="https://example.com/greenteagc/timeline.png" />'
