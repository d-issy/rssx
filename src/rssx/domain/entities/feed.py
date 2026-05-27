from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Feed:
    id: str
    url: str
    title: str
    site_url: str | None
    folder_id: str | None
    etag: str | None
    last_modified: str | None
    last_fetched_at: datetime | None
    next_fetch_at: datetime | None
    fetch_interval_sec: int
    consecutive_empty: int
    last_error: str | None
    created_at: datetime
