from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

URL_ATTRS = {"href", "src", "poster", "cite", "action"}
SRCSET_ATTRS = {"srcset"}


def _is_rewritable_url(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith("#"):
        return False
    parsed = urlparse(stripped)
    return not parsed.scheme and not stripped.startswith("//")


def _absolutize_url(value: str, base_url: str) -> str:
    if not _is_rewritable_url(value):
        return value
    return urljoin(base_url, value.strip())


def _absolutize_srcset(value: str, base_url: str) -> str:
    if not value.strip() or value.lstrip().lower().startswith("data:"):
        return value

    candidates: list[str] = []
    for raw_candidate in value.split(","):
        leading = raw_candidate[: len(raw_candidate) - len(raw_candidate.lstrip())]
        trailing = raw_candidate[len(raw_candidate.rstrip()) :]
        candidate = raw_candidate.strip()
        if not candidate:
            candidates.append(raw_candidate)
            continue
        parts = candidate.split(None, 1)
        url = _absolutize_url(parts[0], base_url)
        descriptor = f" {parts[1]}" if len(parts) > 1 else ""
        candidates.append(f"{leading}{url}{descriptor}{trailing}")
    return ",".join(candidates)


class _URLAbsolutizer(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.parts: list[str] = []

    def _attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        rendered: list[str] = []
        for name, value in attrs:
            if value is None:
                rendered.append(f" {name}")
                continue
            lower = name.lower()
            if lower in URL_ATTRS:
                value = _absolutize_url(value, self.base_url)
            elif lower in SRCSET_ATTRS:
                value = _absolutize_srcset(value, self.base_url)
            rendered.append(f' {name}="{escape(value, quote=True)}"')
        return "".join(rendered)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(f"<{tag}{self._attrs(attrs)} />")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.parts.append(f"<?{data}>")

    def get_html(self) -> str:
        return "".join(self.parts)


def absolutize_html_urls(html: str, base_url: str | None) -> str:
    """Resolve relative URL attributes in feed-provided HTML against base_url."""
    if not html or not base_url:
        return html
    parsed_base = urlparse(base_url)
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
        return html
    parser = _URLAbsolutizer(base_url)
    parser.feed(html)
    parser.close()
    return parser.get_html()
