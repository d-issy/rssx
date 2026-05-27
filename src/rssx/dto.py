from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class FolderRow:
    id: str
    name: str
    parent_id: str | None
    position: int


@dataclass(frozen=True)
class FolderWithCount:
    id: str
    name: str
    parent_id: str | None
    position: int
    feed_count: int


@dataclass(frozen=True)
class FeedListItem:
    id: str
    url: str
    title: str
    site_url: str | None
    folder_id: str | None
    last_fetched_at: datetime | None
    next_fetch_at: datetime | None
    last_error: str | None
    unread_count: int


@dataclass(frozen=True)
class FeedRef:
    id: str
    title: str


@dataclass(frozen=True)
class EntryListItem:
    id: str
    feed_id: str
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
    id: str
    feed_id: str
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
    id: str
    name: str
    parent_id: str | None
    children: list[FolderTreeNode] = field(default_factory=list)
    feeds: list[FeedListItem] = field(default_factory=list)
    unread_count: int = 0


@dataclass(frozen=True)
class FeedFetchState:
    id: str
    url: str
    etag: str | None
    last_modified: str | None
