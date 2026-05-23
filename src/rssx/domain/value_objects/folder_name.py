from dataclasses import dataclass

from rssx.domain.errors import DomainError


@dataclass(frozen=True)
class FolderName:
    value: str

    @classmethod
    def from_raw(cls, raw: str, *, message: str = "name required") -> FolderName:
        value = raw.strip()
        if not value:
            raise DomainError(message)
        return cls(value)
