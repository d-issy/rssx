from dataclasses import dataclass

from rssx.domain.errors import DomainError
from rssx.domain.value_objects.folder_id import FolderId
from rssx.domain.value_objects.folder_name import FolderName


@dataclass(frozen=True)
class FolderSelection:
    folder_id: FolderId | None = None
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
            return cls(folder_id=FolderId.from_raw(folder_id))
        except DomainError:
            return cls()
