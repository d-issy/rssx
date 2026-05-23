from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from rssx.lib.time import make_datetime_filters, parse_stored_datetime, resolve_tz


def test_parse_stored_datetime_accepts_sqlite_and_iso_values() -> None:
    assert parse_stored_datetime("2024-01-15 09:30:00") == datetime(2024, 1, 15, 9, 30, tzinfo=UTC)
    assert parse_stored_datetime("2024-01-15T18:30:00+09:00") == datetime(
        2024, 1, 15, 9, 30, tzinfo=UTC
    )
    assert parse_stored_datetime(None) is None
    assert parse_stored_datetime("not a datetime") is None


def test_make_datetime_filters_formats_for_templates() -> None:
    iso_utc, fmt_dt = make_datetime_filters(ZoneInfo("Asia/Tokyo"))

    assert iso_utc("2024-01-15 09:30:00") == "2024-01-15T09:30:00Z"
    assert fmt_dt("2024-01-15 09:30:00") == "2024-01-15 18:30"
    assert iso_utc(None) == ""
    assert fmt_dt("invalid") == ""


def test_resolve_tz_falls_back_for_unknown_timezone() -> None:
    assert resolve_tz("UTC") == ZoneInfo("UTC")
    assert resolve_tz("Definitely/Unknown") is not None
