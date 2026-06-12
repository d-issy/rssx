import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from shutil import get_terminal_size
from typing import Any, Literal

if os.name == "nt":
    select: Any | None = None
    termios: Any | None = None
    tty: Any | None = None
else:
    import select
    import termios
    import tty

Key = str


@dataclass(frozen=True)
class Size:
    rows: int
    cols: int


class Terminal:
    def __init__(self) -> None:
        self.stdin = sys.stdin
        self.stdout = sys.stdout
        self._old_attrs: Any | None = None
        self._is_windows = os.name == "nt"

    @contextmanager
    def session(self) -> Iterator[None]:
        self.enter()
        try:
            yield
        finally:
            self.exit()

    def enter(self) -> None:
        if not self._is_windows and self.stdin.isatty():
            assert termios is not None
            assert tty is not None
            self._old_attrs = termios.tcgetattr(self.stdin.fileno())
            tty.setcbreak(self.stdin.fileno())
        self.write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")

    def exit(self) -> None:
        self.write("\x1b[?25h\x1b[0m\x1b[?1049l")
        if not self._is_windows and self._old_attrs is not None and self.stdin.isatty():
            assert termios is not None
            termios.tcsetattr(self.stdin.fileno(), termios.TCSADRAIN, self._old_attrs)
            self._old_attrs = None

    def size(self) -> Size:
        size = get_terminal_size((100, 30))
        return Size(rows=size.lines, cols=size.columns)

    def write(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    def render(self, lines: list[str]) -> None:
        size = self.size()
        clipped = lines[: size.rows]
        out = ["\x1b[H"]
        for i in range(size.rows):
            line = clipped[i] if i < len(clipped) else ""
            out.append(clip_ansi(line, size.cols))
            out.append("\x1b[0m\x1b[K")
            if i != size.rows - 1:
                out.append("\n")
        self.write("".join(out))

    def read_key(self, timeout: float | None = None) -> Key | None:
        if self._is_windows:
            return self._read_key_windows(timeout)
        return self._read_key_posix(timeout)

    def _read_key_posix(self, timeout: float | None) -> Key | None:
        assert select is not None
        if timeout is not None:
            ready, _, _ = select.select([self.stdin], [], [], timeout)
            if not ready:
                return None
        ch = self.stdin.read(1)
        if ch == "\x03":
            return "ctrl_c"
        if ch in {"\r", "\n"}:
            return "enter"
        if ch == "\t":
            return "tab"
        if ch in {"\x7f", "\b"}:
            return "backspace"
        if ch != "\x1b":
            return ch

        ready, _, _ = select.select([self.stdin], [], [], 0.01)
        if not ready:
            return "esc"
        seq = self.stdin.read(1)
        if seq != "[":
            return "esc"
        ready, _, _ = select.select([self.stdin], [], [], 0.01)
        if not ready:
            return "esc"
        code = self.stdin.read(1)
        return {
            "A": "up",
            "B": "down",
            "C": "right",
            "D": "left",
            "H": "home",
            "F": "end",
        }.get(code, "esc")

    def _read_key_windows(self, timeout: float | None) -> Key | None:
        import msvcrt
        import time

        kbhit = msvcrt.kbhit  # type: ignore[attr-defined]
        getwch = msvcrt.getwch  # type: ignore[attr-defined]
        if timeout is not None:
            deadline = time.monotonic() + timeout
            while not kbhit():
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.01)
        ch = str(getwch())
        if ch == "\x03":
            return "ctrl_c"
        if ch == "\r":
            return "enter"
        if ch == "\t":
            return "tab"
        if ch in {"\x08", "\x7f"}:
            return "backspace"
        if ch == "\x1b":
            return "esc"
        if ch in {"\x00", "\xe0"}:
            code = str(getwch())
            return {
                "H": "up",
                "P": "down",
                "K": "left",
                "M": "right",
                "G": "home",
                "O": "end",
            }.get(code, "")
        return ch


Color = Literal[
    "normal",
    "bold",
    "dim",
    "reverse",
    "error",
    "accent",
    "muted",
    "selected",
    "inactive_selected",
    "body_marker",
    "star",
]


_STYLES: dict[Color, str] = {
    "normal": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "reverse": "\x1b[7m",
    "error": "\x1b[31m",
    "accent": "\x1b[36m",
    "muted": "\x1b[90m",
    "selected": "\x1b[7m",
    "inactive_selected": "\x1b[7m",
    "body_marker": "\x1b[2;100m",
    "star": "\x1b[33m",
}


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1


def clip_ansi(text: str, width: int) -> str:
    """Clip a styled terminal line by visible cells without cutting ANSI codes."""
    if width <= 0:
        return ""
    out: list[str] = []
    visible = 0
    i = 0
    while i < len(text):
        match = _ANSI_RE.match(text, i)
        if match:
            out.append(match.group(0))
            i = match.end()
            continue
        ch = text[i]
        ch_width = _char_width(ch)
        if visible + ch_width > width:
            break
        out.append(ch)
        visible += ch_width
        i += 1
    return "".join(out)


def style(text: str, color: Color) -> str:
    code = _STYLES[color]
    return f"{code}{text.replace('\x1b[0m', f'\x1b[0m{code}')}\x1b[0m"
