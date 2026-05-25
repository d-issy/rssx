import json

from fastapi import Request
from starlette.responses import Response

from rssx.domain.events import DomainEvent

# Backward-compatible name for tests/call sites that still think in HTMX terms.
HtmxEvent = DomainEvent


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def add_trigger(resp: Response, *events: DomainEvent | str) -> Response:
    """Merge HTMX trigger events into a response.

    Always writes the JSON-object form. It is unambiguous for event names that
    contain colons and composes safely when multiple code paths add events.
    """
    merged: dict[str, None] = {}
    existing = resp.headers.get("HX-Trigger")
    if existing:
        try:
            parsed: object = json.loads(existing)
        except json.JSONDecodeError:
            for name in existing.split(","):
                name = name.strip()
                if name:
                    merged[name] = None
        else:
            if isinstance(parsed, dict):
                for key in parsed:
                    if isinstance(key, str):
                        merged[key] = None
            elif isinstance(parsed, str):
                merged[parsed] = None
    for event in events:
        merged[str(event)] = None
    resp.headers["HX-Trigger"] = json.dumps(merged)
    return resp


def trigger_names(value: str | None) -> set[str]:
    """Test helper-friendly parser for HX-Trigger header values."""
    if not value:
        return set()
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(parsed, dict):
        return {key for key in parsed if isinstance(key, str)}
    if isinstance(parsed, str):
        return {parsed}
    return set()
