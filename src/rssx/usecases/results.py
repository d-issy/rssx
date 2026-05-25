from dataclasses import dataclass

from rssx.domain.events import DomainEvent


class ApplicationError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class OperationResult:
    events: tuple[DomainEvent, ...] = ()


@dataclass(frozen=True)
class FeedCreateResult(OperationResult):
    feed_id: int = 0
