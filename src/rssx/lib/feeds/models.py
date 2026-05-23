from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedEntry:
    guid: str
    title: str
    url: str | None
    author: str | None
    content: str
    summary: str
    published_at: str | None


@dataclass(frozen=True)
class ParsedFeed:
    title: str
    site_url: str | None
    entries: list[ParsedEntry]
