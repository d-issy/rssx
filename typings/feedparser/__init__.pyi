class FeedParserDict(dict[str, object]):
    def __getattr__(self, name: str) -> object: ...
    def __setattr__(self, name: str, value: object) -> None: ...

class FeedParserResult(FeedParserDict):
    feed: FeedParserDict
    entries: list[FeedParserDict]

# feedparser.parse accepts many file/URL/bytes/string shapes and keyword options.
# Keep the input broad, but make the result shape visible to LSP/type checkers.
def parse(
    url_file_stream_or_string: object, *args: object, **kwargs: object
) -> FeedParserResult: ...
