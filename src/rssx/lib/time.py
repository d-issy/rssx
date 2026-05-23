import logging
from collections.abc import Callable
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)


def resolve_tz(name: str) -> tzinfo | None:
    if name == "local":
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        log.warning("unknown timezone %r, falling back to system local", name)
        return datetime.now().astimezone().tzinfo


def parse_stored_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))


def make_datetime_filters(
    tz: tzinfo | None,
) -> tuple[Callable[[str | None], str], Callable[[str | None], str]]:
    def iso_utc(value: str | None) -> str:
        dt = parse_stored_datetime(value)
        if dt is None:
            return ""
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def fmt_dt(value: str | None) -> str:
        dt = parse_stored_datetime(value)
        if dt is None:
            return ""
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M")

    return iso_utc, fmt_dt
