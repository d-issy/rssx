import sqlite3
from collections.abc import Callable

from rssx import repository as repo
from rssx.domain.errors import DomainError
from rssx.domain.events import DomainEvent
from rssx.domain.value_objects import FolderName
from rssx.usecases.results import ApplicationError, OperationResult


class FolderManagementUseCases:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_folder(self, name: str) -> OperationResult:
        folder_name = self._to_application_error(lambda: FolderName.from_raw(name))
        repo.add_folder(self.conn, folder_name.value, None)
        return OperationResult((DomainEvent.COUNTS_CHANGED,))

    def rename_folder(self, folder_id: str, name: str) -> OperationResult:
        folder_name = self._to_application_error(lambda: FolderName.from_raw(name))
        repo.rename_folder(self.conn, folder_id, folder_name.value)
        return OperationResult((DomainEvent.COUNTS_CHANGED,))

    def delete_folder(self, folder_id: str, mode: str) -> OperationResult:
        if mode == "cascade":
            repo.delete_folder_cascade(self.conn, folder_id)
        else:
            repo.delete_folder(self.conn, folder_id)
        return OperationResult((DomainEvent.COUNTS_CHANGED, DomainEvent.FOLDER_CHANGED))

    def _to_application_error[T](self, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except DomainError as e:
            raise ApplicationError(e.message) from e
