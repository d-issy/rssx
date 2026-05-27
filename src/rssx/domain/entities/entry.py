from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Entry:
    id: str
    feed_id: str
    guid: str
    title: str
    url: str | None
    author: str | None
    content: str
    summary: str
    published_at: datetime | None
    fetched_at: datetime
    is_read: bool
    is_starred: bool
    read_at: datetime | None
    starred_at: datetime | None
