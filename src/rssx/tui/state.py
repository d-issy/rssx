import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from rssx.lib.paths import xdg_state_home


@dataclass
class TuiState:
    folder_open: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> TuiState:
        state_file = path or default_state_path()
        if not state_file.exists():
            return cls()
        try:
            with state_file.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError:
            return cls()
        folders = data.get("folders", {})
        if not isinstance(folders, dict):
            return cls()
        return cls({str(k): bool(v) for k, v in folders.items()})

    def save(self, path: Path | None = None) -> None:
        state_file = path or default_state_path()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[folders]"]
        for key in sorted(self.folder_open):
            escaped = key.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{escaped}" = {str(self.folder_open[key]).lower()}')
        state_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def default_state_path() -> Path:
    return xdg_state_home() / "rssx" / "state.toml"
