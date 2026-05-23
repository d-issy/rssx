from fastapi.responses import HTMLResponse

from rssx.htmx import HtmxEvent, add_trigger, trigger_names


def test_add_trigger_merges_existing_json_header() -> None:
    resp = HTMLResponse("")
    add_trigger(resp, HtmxEvent.COUNTS_CHANGED)
    add_trigger(resp, HtmxEvent.FEED_FOLDER_CHANGED)

    assert trigger_names(resp.headers["HX-Trigger"]) == {
        HtmxEvent.COUNTS_CHANGED,
        HtmxEvent.FEED_FOLDER_CHANGED,
    }


def test_trigger_names_accepts_legacy_comma_header() -> None:
    assert trigger_names("a, b") == {"a", "b"}
