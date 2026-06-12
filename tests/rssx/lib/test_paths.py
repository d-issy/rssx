from pathlib import Path

from rssx.lib.paths import xdg_config_home, xdg_data_home, xdg_state_home


def test_xdg_paths_use_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "~/custom-data")
    monkeypatch.setenv("XDG_CONFIG_HOME", "~/custom-config")
    monkeypatch.setenv("XDG_STATE_HOME", "~/custom-state")

    assert xdg_data_home() == Path("~/custom-data").expanduser()
    assert xdg_config_home() == Path("~/custom-config").expanduser()
    assert xdg_state_home() == Path("~/custom-state").expanduser()


def test_xdg_paths_fallback_to_home(monkeypatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    assert xdg_data_home() == Path.home() / ".local" / "share"
    assert xdg_config_home() == Path.home() / ".config"
    assert xdg_state_home() == Path.home() / ".local" / "state"
