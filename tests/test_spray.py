"""Tests for spray safety checks and future dry-window search."""

from datetime import datetime

import numpy as np

from conftest import make_hourly
from ks.spray import next_dry_window, spray_now


def test_dry_calm_next_day_is_sprayable(cfg) -> None:
    """No rain and light wind permit a spray recommendation."""
    start = datetime(2026, 11, 20, 10)
    hourly = make_hourly(start, 48, 70, 20, rain=0.0, wind=5.0)

    assert spray_now(hourly, start, cfg) == (True, "spray.ok", {})


def test_rain_total_is_reported_to_one_decimal(cfg) -> None:
    """Rain across the next 24 hours blocks the spray."""
    start = datetime(2026, 11, 20, 10)
    hourly = make_hourly(start, 48, 70, 20, rain=[5.0 / 24] * 24 + [0.0] * 24)
    result = spray_now(hourly, start, cfg)

    assert result == (False, "spray.rain", {"rain_mm": 5.0})


def test_strong_wind_blocks_spray(cfg) -> None:
    """Wind at the start hour above the configured limit is unsafe."""
    start = datetime(2026, 11, 20, 10)
    hourly = make_hourly(start, 48, 70, 20, wind=20.0)

    assert spray_now(hourly, start, cfg) == (False, "spray.wind", {"wind": 20.0})


def test_next_dry_window_starts_after_rain_and_in_daytime(cfg) -> None:
    """Search chooses the first safe daytime start after 48 wet hours."""
    start = datetime(2026, 11, 20, 4)
    rain = [1.0] * 48 + [0.0] * 144
    hourly = make_hourly(start, len(rain), 70, 20, rain=rain)

    assert next_dry_window(hourly, start, cfg) == datetime(2026, 11, 22, 6)


def test_no_dry_window_when_forecast_stays_wet(cfg) -> None:
    """A wet forecast with no safe 24-hour window returns None."""
    start = datetime(2026, 11, 20, 6)
    hourly = make_hourly(start, 8 * 24, 70, 20, rain=1.0)

    assert next_dry_window(hourly, start, cfg) is None


def test_probability_blocks_but_all_missing_probability_is_ignored(cfg) -> None:
    """Known high rain probability blocks; entirely missing probability does not."""
    start = datetime(2026, 11, 20, 10)
    rainy = make_hourly(start, 48, 70, 20, rain=0.0, prob=80.0)
    missing = make_hourly(start, 48, 70, 20, rain=0.0, prob=np.nan)

    assert not spray_now(rainy, start, cfg)[0]
    assert spray_now(missing, start, cfg)[0]
