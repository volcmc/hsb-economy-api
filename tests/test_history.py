from hsb_economy import config
from hsb_economy.history import History

START = 1_800_000_000 - 1_800_000_000 % config.DAY


def test_observations_average_within_a_bucket():
    history = History()
    history.record("X", "lbin", START, 100)
    history.record("X", "lbin", START + 60, 200)
    history.record("X", "lbin", START + config.HOUR, 50)
    hourly = history.data["X"]["lbin"]["hourly"]
    assert hourly["t"] == [START, START + config.HOUR]
    assert hourly["v"] == [150, 50]
    assert history.data["X"]["lbin"]["daily"]["v"] == [(100 + 200 + 50) / 3]


def test_none_values_are_not_recorded():
    history = History()
    history.record("X", "buy", START, None)
    assert history.data == {}


def test_change_against_past_point():
    history = History()
    history.record("X", "lbin", START, 100)
    history.record("X", "lbin", START + config.DAY, 125)
    assert history.change("X", "lbin", START + config.DAY, config.DAY, 125) == 0.25
    assert history.change("X", "lbin", START + config.DAY, 7 * config.DAY, 125) is None
    assert history.change("MISSING", "lbin", START, config.DAY, 1) is None


def test_no_change_without_a_current_value():
    history = History()
    history.record("X", "lbin", START, 100)
    history.record("X", "lbin", START + config.DAY, 125)
    assert history.change("X", "lbin", START + config.DAY, config.DAY, None) is None


def test_seven_day_change_uses_daily_series():
    history = History()
    # Off bucket boundaries, so the hourly point from 7 days ago has been pruned.
    offset = config.HOUR // 2
    for day in range(8):
        history.record("X", "lbin", START + day * config.DAY + offset, 100 + day * 10)
    now = START + 7 * config.DAY + offset
    assert history.change("X", "lbin", now, 7 * config.DAY, 170) == 170 / 100 - 1


def test_retention_prunes_and_removes_empty_keys():
    history = History()
    history.record("X", "lbin", START, 100)
    history.record("Y", "lbin", START + config.DAILY_RETENTION, 1)
    assert history.data["X"]["lbin"]["hourly"]["t"] == [START]
    history.prune(START + config.DAILY_RETENTION + config.DAY)
    assert "X" not in history.data
    assert history.data["Y"]["lbin"]["daily"]["v"] == [1]
