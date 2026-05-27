from dataclasses import dataclass

from rssx.domain.value_objects.folder_name import FolderName


@dataclass(frozen=True)
class FolderSelection:
    folder_id: str | None = None
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
        return cls(folder_id=folder_id)
