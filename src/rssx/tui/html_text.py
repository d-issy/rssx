import re
from html import unescape
from html.parser import HTMLParser

_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "main",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "ul",
}


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._in_pre = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "br":
            self._newline()
        elif tag == "li":
            self._newline()
            self.parts.append("• ")
        elif tag == "pre":
            self._newline()
            self._in_pre = True
        elif tag in _BLOCK_TAGS:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "pre":
            self._in_pre = False
            self._newline()
        elif tag in _BLOCK_TAGS or tag == "li":
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_pre:
            self.parts.append(data)
        else:
            self.parts.append(re.sub(r"\s+", " ", data))

    def _newline(self) -> None:
        if not self.parts or self.parts[-1].endswith("\n"):
            return
        self.parts.append("\n")


_POST_BLANK_LINE_TAGS = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    parser = _PlainTextParser()
    parser.feed(html)
    parser.close()
    text = unescape("".join(parser.parts))
    lines = [line.strip() for line in text.splitlines()]
    compact = "\n".join(line for line in lines if line)
    return _POST_BLANK_LINE_TAGS.sub("\n\n", compact).strip()
