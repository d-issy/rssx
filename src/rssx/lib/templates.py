from pathlib import Path

from fastapi.templating import Jinja2Templates

from rssx.lib.env import is_dev_mode
from rssx.lib.html import absolutize_html_urls
from rssx.lib.time import make_datetime_filters, resolve_tz


def create_templates(base_dir: Path, *, timezone: str) -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    templates.env.globals["dev_mode"] = is_dev_mode()
    iso_utc, fmt_dt = make_datetime_filters(resolve_tz(timezone))
    templates.env.filters["iso_utc"] = iso_utc
    templates.env.filters["fmt_dt"] = fmt_dt
    templates.env.filters["absolutize_urls"] = absolutize_html_urls
    return templates
