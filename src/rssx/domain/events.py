from enum import StrEnum


class DomainEvent(StrEnum):
    COUNTS_CHANGED = "rssx:counts-changed"
    FEED_ADDED = "rssx:feed-added"
    FEED_FOLDER_CHANGED = "rssx:feed-folder-changed"
    FOLDER_CHANGED = "rssx:folder-changed"
