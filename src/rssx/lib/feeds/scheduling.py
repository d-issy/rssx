from dataclasses import dataclass
from datetime import datetime


@dataclass
class FetchConfig:
    min_interval_min: int = 10
    max_interval_min: int = 24 * 60
    initial_interval_min: int = 30
    history_window: int = 15
    interval_factor: float = 0.5
    empty_backoff_factor: float = 1.5


def compute_next_interval(
    published_times: list[datetime],
    consecutive_empty: int,
    cfg: FetchConfig,
) -> int:
    """Return the next fetch interval in seconds for DB/runtime scheduling."""
    times = sorted([t for t in published_times if t is not None], reverse=True)
    if len(times) < 2:
        base = cfg.initial_interval_min * 60
    else:
        sample = times[: cfg.history_window]
        deltas = [(sample[i] - sample[i + 1]).total_seconds() for i in range(len(sample) - 1)]
        deltas = [d for d in deltas if d > 0]
        if not deltas:
            base = cfg.initial_interval_min * 60
        else:
            avg = sum(deltas) / len(deltas)
            base = int(avg * cfg.interval_factor)

    if consecutive_empty > 0:
        base = int(base * (cfg.empty_backoff_factor**consecutive_empty))

    return max(cfg.min_interval_min * 60, min(cfg.max_interval_min * 60, base))
