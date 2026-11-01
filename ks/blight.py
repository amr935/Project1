"""Rule-based potato late-blight risk calculations."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from .models import AppConfig, BlightDay, Level


def blight_days(hourly: pd.DataFrame, days: list[date], cfg: AppConfig) -> list[BlightDay]:
    """Classify each date using its preceding configured hourly window."""
    required = {"time", "relative_humidity_2m", "temperature_2m"}
    missing_columns = required - set(hourly.columns)
    if missing_columns:
        raise ValueError(f"hourly weather is missing columns: {', '.join(sorted(missing_columns))}")
    frame = hourly.loc[:, ["time", "relative_humidity_2m", "temperature_2m"]].copy()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    if frame["time"].dt.tz is not None:
        frame["time"] = frame["time"].dt.tz_localize(None)
    for column in ("relative_humidity_2m", "temperature_2m"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    result: list[BlightDay] = []
    for target in days:
        start = pd.Timestamp(datetime.combine(target - timedelta(days=6), time.min))
        end = pd.Timestamp(datetime.combine(target, time(23, 0)))
        window = frame.loc[frame["time"].between(start, end, inclusive="both")]
        rh = window["relative_humidity_2m"]
        temperature = window["temperature_2m"]
        valid = int((rh.notna() & temperature.notna()).sum())
        missing_fraction = (cfg.blight.window_hours - valid) / cfg.blight.window_hours
        rh_hours = int((rh >= cfg.blight.rh_threshold).sum())
        t_hours = int(temperature.between(cfg.blight.t_min, cfg.blight.t_max, inclusive="both").sum())
        if missing_fraction > cfg.blight.max_missing_fraction:
            level = Level.NO_DATA
        elif rh_hours >= cfg.blight.rh_hours_required and t_hours >= cfg.blight.t_hours_required:
            level = Level.RED
        elif rh_hours >= cfg.blight.rh_hours_required or (
            rh_hours >= cfg.blight.yellow_fraction * cfg.blight.rh_hours_required
            and t_hours >= cfg.blight.yellow_fraction * cfg.blight.t_hours_required
        ):
            level = Level.YELLOW
        else:
            level = Level.GREEN
        result.append(BlightDay(target, rh_hours, t_hours, missing_fraction, level))
    return result


def week_summary(blight: list[BlightDay]) -> tuple[Level, date | None]:
    """Return the worst level and its first date, with green above no-data."""
    if not blight:
        return Level.NO_DATA, None
    rank = {Level.NO_DATA: 0, Level.GREEN: 1, Level.YELLOW: 2, Level.RED: 3, Level.OFF_SEASON: -1}
    worst_rank = max(rank[day.level] for day in blight)
    first = min(day.day for day in blight if rank[day.level] == worst_rank)
    return next(level for level, level_rank in rank.items() if level_rank == worst_rank), first


def in_season(month: int, cfg: AppConfig) -> bool:
    """Return whether a month is inside the configured blight season."""
    return month in cfg.blight.season_months
