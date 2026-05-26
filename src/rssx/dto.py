from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class FolderRow:
    id: int
    name: str
    parent_id: int | None
    position: int


@dataclass(frozen=True)
class FolderWithCount:
    id: int
    name: str
    parent_id: int | None
    position: int
    feed_count: int


@dataclass(frozen=True)
class FeedListItem:
    id: int
    url: str
    title: str
    site_url: str | None
    folder_id: int | None
    last_fetched_at: datetime | None
    next_fetch_at: datetime | None
    last_error: str | None
    unread_count: int


@dataclass(frozen=True)
class FeedRef:
    id: int
    title: str


@dataclass(frozen=True)
class EntryListItem:
    id: int
    feed_id: int
    title: str
    url: str | None
    author: str | None
    summary: str
    published_at: datetime | None
    is_read: bool
    is_starred: bool
    feed_title: str


@dataclass(frozen=True)
class EntryDetail:
    id: int
    feed_id: int
    guid: str
    title: str
    url: str | None
    author: str | None
    content: str
    summary: str
    published_at: datetime | None
    fetched_at: datetime | None
    is_read: bool
    is_starred: bool
    read_at: datetime | None
    starred_at: datetime | None
    feed_title: str


@dataclass
class FolderTreeNode:
    id: int
    name: str
    parent_id: int | None
    children: list[FolderTreeNode] = field(default_factory=list)
    feeds: list[FeedListItem] = field(default_factory=list)
    unread_count: int = 0


@dataclass(frozen=True)
class FeedFetchState:
    id: int
    url: str
    etag: str | None
    last_modified: str | None
