from dataclasses import dataclass


class DomainError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class FolderName:
    value: str

    @classmethod
    def from_raw(cls, raw: str, *, message: str = "name required") -> FolderName:
        value = raw.strip()
        if not value:
            raise DomainError(message)
        return cls(value)


@dataclass(frozen=True)
class FeedUrl:
    value: str

    @classmethod
    def from_raw(cls, raw: str) -> FeedUrl:
        value = raw.strip()
        if not value:
            raise DomainError("URL を入力してください")
        return cls(value)


@dataclass(frozen=True)
class FolderSelection:
    folder_id: int | None = None
    new_folder_name: FolderName | None = None

    @classmethod
    def from_form(
        cls,
        folder_id: str | None,
        new_folder_name: str | None,
    ) -> FolderSelection:
        if folder_id == "__new":
            return cls(
                new_folder_name=FolderName.from_raw(
                    new_folder_name or "",
                    message="新しいフォルダ名を入力してください",
                )
            )
        if not folder_id:
            return cls()
        try:
            return cls(folder_id=int(folder_id))
        except ValueError:
            return cls()


@dataclass(frozen=True)
class FeedDraft:
    url: FeedUrl
    title: str
    site_url: str | None
    folder_selection: FolderSelection

    @property
    def normalized_title(self) -> str:
        return self.title.strip()
