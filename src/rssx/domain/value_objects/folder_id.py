from dataclasses import dataclass

from ulid import ULID

from rssx.domain.errors import DomainError


@dataclass(frozen=True)
class FolderId:
    value: str

    @classmethod
    def from_raw(cls, raw: str, *, message: str = "不正なフォルダ ID です") -> FolderId:
        try:
            ULID.from_str(raw)
        except (ValueError, TypeError) as e:
            raise DomainError(message) from e
        return cls(raw)
