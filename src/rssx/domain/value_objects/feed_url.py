from dataclasses import dataclass

from rssx.domain.errors import DomainError


@dataclass(frozen=True)
class FeedUrl:
    value: str

    @classmethod
    def from_raw(cls, raw: str) -> FeedUrl:
        value = raw.strip()
        if not value:
            raise DomainError("URL を入力してください")
        return cls(value)
