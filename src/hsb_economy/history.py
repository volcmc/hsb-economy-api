"""Downsampled price history.

Each metric keeps two series: hourly points for a week and daily points for a year. A point's value is
the mean of every observation that fell into its bucket; ``n`` tracks how many observations the newest
(still open) bucket has absorbed so later runs can keep averaging into it.

Serialized form of one series: ``{"t": [bucket_start, ...], "v": [value, ...], "n": count_in_last}``.
"""

from . import config

RESOLUTIONS = {
    "hourly": (config.HOUR, config.HOURLY_RETENTION),
    "daily": (config.DAY, config.DAILY_RETENTION),
}


def new_series() -> dict:
    return {"t": [], "v": [], "n": 0}


def record(series: dict, now: int, value: float, resolution: int, retention: int) -> None:
    bucket = now - now % resolution
    if series["t"] and series["t"][-1] == bucket:
        n = series["n"]
        series["v"][-1] = (series["v"][-1] * n + value) / (n + 1)
        series["n"] = n + 1
    else:
        series["t"].append(bucket)
        series["v"].append(value)
        series["n"] = 1
    prune(series, now, retention)


def prune(series: dict, now: int, retention: int) -> None:
    cutoff = now - retention
    drop = 0
    while drop < len(series["t"]) and series["t"][drop] < cutoff:
        drop += 1
    if drop:
        del series["t"][:drop]
        del series["v"][:drop]


def value_at(series: dict, when: int) -> float | None:
    """Value of the last bucket starting at or before ``when``."""
    result = None
    for t, v in zip(series["t"], series["v"], strict=True):
        if t > when:
            break
        result = v
    return result


class History:
    """History for one dataset (e.g. bazaar): ``{key: {metric: {resolution: series}}}``."""

    def __init__(self, data: dict | None = None):
        self.data: dict = data or {}

    def record(self, key: str, metric: str, now: int, value: float | None) -> None:
        if value is None:
            return
        metrics = self.data.setdefault(key, {})
        by_resolution = metrics.setdefault(metric, {name: new_series() for name in RESOLUTIONS})
        for name, (resolution, retention) in RESOLUTIONS.items():
            record(by_resolution[name], now, value, resolution, retention)

    def change(self, key: str, metric: str, now: int, ago: int, current: float | None) -> float | None:
        """Relative change from the value ``ago`` seconds earlier to ``current``, e.g. 0.05 for +5%.

        ``None`` when there is no current value (nothing listed now) or no point that far back.
        """
        series = self.data.get(key, {}).get(metric)
        if current is None or not series:
            return None
        # At exactly the retention boundary the hourly point has already been pruned.
        resolution = "hourly" if ago < config.HOURLY_RETENTION else "daily"
        then = value_at(series[resolution], now - ago)
        if not then:
            return None
        return current / then - 1

    def prune(self, now: int) -> None:
        """Drop metrics, then keys, that have no points left in any resolution."""
        for key in list(self.data):
            metrics = self.data[key]
            for metric in list(metrics):
                for name, (_, retention) in RESOLUTIONS.items():
                    prune(metrics[metric][name], now, retention)
                if not any(series["t"] for series in metrics[metric].values()):
                    del metrics[metric]
            if not metrics:
                del self.data[key]

    def export(self, key: str) -> dict:
        return {
            metric: {name: {"t": s["t"], "v": [round(v, 2) for v in s["v"]]} for name, s in series.items()}
            for metric, series in self.data.get(key, {}).items()
        }
