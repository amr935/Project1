"""Tests for the seven-day potato late-blight rule."""

from datetime import date, datetime, timedelta

import numpy as np

from ks.blight import blight_days, in_season, week_summary
from conftest import make_hourly
from ks.models import BlightDay, Level


def _day() -> date:
    """Return a fixed window end date for repeatable hourly fixtures."""
    return date(2026, 11, 20)


def _evaluate(cfg, rh, temperature, missing: int = 0) -> BlightDay:
    """Calculate one blight day from a seven-day synthetic frame."""
    humidity = list(rh) if isinstance(rh, (list, np.ndarray)) else [rh] * 168
    temps = list(temperature) if isinstance(temperature, (list, np.ndarray)) else [temperature] * 168
    for index in range(missing):
        humidity[index] = np.nan
    frame = make_hourly(datetime(2026, 11, 14), 168, humidity, temps)
    return blight_days(frame, [_day()], cfg)[0]


def test_all_suitable_hours_are_red(cfg) -> None:
    """Meeting both inclusive thresholds produces a red day."""
    result = _evaluate(cfg, 95, 15)

    assert result.level is Level.RED
    assert result.rh_hours == 168
    assert result.t_hours == 168


def test_temperature_only_condition_is_green(cfg) -> None:
    """Temperature hours alone do not raise the humidity-driven warning."""
    assert _evaluate(cfg, 50, 15).level is Level.GREEN


def test_near_both_thresholds_is_yellow(cfg) -> None:
    """At least 70 percent of both counts produces yellow."""
    humidity = [95] * 80 + [50] * 88
    result = _evaluate(cfg, humidity, 15)

    assert result.level is Level.YELLOW
    assert result.rh_hours == 80
    assert result.t_hours == 168


def test_humidity_alone_is_yellow(cfg) -> None:
    """Meeting humidity hours alone produces yellow."""
    assert _evaluate(cfg, 95, 30).level is Level.YELLOW


def test_threshold_boundaries_are_inclusive(cfg) -> None:
    """Humidity 90 and temperatures 7.2/26.6 count toward limits."""
    humidity = [90] * 105 + [89] * 63
    temperature = [7.2] * 75 + [26.6] * 75 + [26.7] * 18
    result = _evaluate(cfg, humidity, temperature)

    assert result.level is Level.RED
    assert result.rh_hours == 105
    assert result.t_hours == 150
    assert _evaluate(cfg, [90] * 104 + [89] * 64, 15).level is not Level.RED


def test_missing_data_limit_is_strictly_above_ten_percent(cfg) -> None:
    """More than ten percent missing is no-data; less is classified."""
    assert _evaluate(cfg, 95, 15, missing=20).level is Level.NO_DATA
    assert _evaluate(cfg, 50, 15, missing=16).level is Level.GREEN


def test_season_months_come_from_config(cfg) -> None:
    """Season membership follows the configured month list."""
    assert in_season(11, cfg)
    assert not in_season(7, cfg)


def test_week_summary_uses_worst_level_and_first_matching_date() -> None:
    """The first day at the worst level is returned."""
    first = date(2026, 11, 20)
    entries = [
        BlightDay(first, 0, 168, 0.0, Level.GREEN),
        BlightDay(first + timedelta(days=1), 168, 168, 0.0, Level.RED),
        BlightDay(first + timedelta(days=2), 168, 168, 0.0, Level.RED),
    ]

    assert week_summary(entries) == (Level.RED, first + timedelta(days=1))
