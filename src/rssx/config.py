import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


@dataclass
class Config:
    db_path: Path = field(default_factory=lambda: xdg_data_home() / "rssx" / "rssx.db")
    host: str = "0.0.0.0"
    port: int = 8080
    min_interval_sec: int = 10 * 60
    max_interval_sec: int = 24 * 60 * 60
    initial_interval_sec: int = 30 * 60
    scheduler_tick_sec: int = 60
    timezone: str = "local"

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        cfg = cls()
        config_file = path or (xdg_config_home() / "rssx" / "config.toml")
        if config_file.exists():
            with config_file.open("rb") as f:
                data = tomllib.load(f)
            if "db_path" in data:
                cfg.db_path = Path(data["db_path"]).expanduser()
            if "host" in data:
                cfg.host = str(data["host"])
            if "port" in data:
                cfg.port = int(data["port"])
            if "timezone" in data:
                cfg.timezone = str(data["timezone"])
            fetch = data.get("fetch", {})
            if "min_interval_sec" in fetch:
                cfg.min_interval_sec = int(fetch["min_interval_sec"])
            if "max_interval_sec" in fetch:
                cfg.max_interval_sec = int(fetch["max_interval_sec"])
            if "initial_interval_sec" in fetch:
                cfg.initial_interval_sec = int(fetch["initial_interval_sec"])
            if "scheduler_tick_sec" in fetch:
                cfg.scheduler_tick_sec = int(fetch["scheduler_tick_sec"])
        return cfg
