from rssx.tui.html_text import html_to_text
from rssx.tui.state import TuiState


def test_html_to_text_keeps_readable_paragraphs_and_lists() -> None:
    html = "<h1>Title</h1><p>Hello<br>world</p><ul><li>One</li><li>Two</li></ul>"

    assert html_to_text(html) == "Title\nHello\nworld\n• One\n• Two"


def test_tui_state_roundtrip(tmp_path) -> None:
    path = tmp_path / "state.toml"
    state = TuiState({"folder-1": True, "folder-2": False})

    state.save(path)

    assert TuiState.load(path) == state
