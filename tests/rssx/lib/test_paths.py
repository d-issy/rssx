from pathlib import Path

from rssx.lib.paths import xdg_config_home, xdg_data_home


def test_xdg_paths_use_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "~/custom-data")
    monkeypatch.setenv("XDG_CONFIG_HOME", "~/custom-config")

    assert xdg_data_home() == Path("~/custom-data").expanduser()
    assert xdg_config_home() == Path("~/custom-config").expanduser()


def test_xdg_paths_fallback_to_home(monkeypatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert xdg_data_home() == Path.home() / ".local" / "share"
    assert xdg_config_home() == Path.home() / ".config"
