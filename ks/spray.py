"""Evaluate spray conditions and find upcoming dry daytime windows."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .models import AppConfig


def _local_hour(value: datetime, cfg: AppConfig) -> pd.Timestamp:
    """Convert a datetime to a naive configured-local hour."""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(ZoneInfo(cfg.app.timezone)).tz_localize(None)
    return stamp.floor("h")


def _prepare(hourly: pd.DataFrame, cfg: AppConfig) -> pd.DataFrame:
    """Validate and normalize the weather columns used for spray checks."""
    required = {"time", "precipitation", "precipitation_probability", "wind_speed_10m"}
    missing = required - set(hourly.columns)
    if missing:
        raise ValueError(f"hourly weather is missing columns: {', '.join(sorted(missing))}")
    frame = hourly.loc[:, ["time", "precipitation", "precipitation_probability", "wind_speed_10m"]].copy()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    if isinstance(frame["time"].dtype, pd.DatetimeTZDtype):
        frame["time"] = frame["time"].dt.tz_convert(ZoneInfo(cfg.app.timezone)).dt.tz_localize(None)
    for column in ("precipitation", "precipitation_probability", "wind_speed_10m"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["time"]).drop_duplicates("time").set_index("time").sort_index()


def _assess(frame: pd.DataFrame, start: pd.Timestamp, cfg: AppConfig) -> tuple[bool, str, dict[str, float]]:
    """Assess one 24-hour start and return its reason template and values."""
    times = pd.date_range(start=start, periods=24, freq="h")
    window = frame.reindex(times)
    if len(window) != 24 or pd.isna(window["wind_speed_10m"].iloc[0]):
        return False, "spray.no_window", {}
    precipitation = window["precipitation"]
    if precipitation.isna().all():
        return False, "spray.no_window", {}
    rain_total = float(precipitation.fillna(0).sum())
    rain_mm = round(rain_total, 1)
    probabilities = window["precipitation_probability"].dropna()
    if rain_total >= cfg.spray.rain_mm_24h_max or (
        not probabilities.empty and probabilities.max() > cfg.spray.rain_prob_max
    ):
        return False, "spray.rain", {"rain_mm": rain_mm}
    wind = float(window["wind_speed_10m"].iloc[0])
    if wind >= cfg.spray.wind_kmh_max:
        return False, "spray.wind", {"wind": round(wind, 1)}
    return True, "spray.ok", {}


def spray_now(hourly: pd.DataFrame, now: datetime, cfg: AppConfig) -> tuple[bool, str, dict[str, float]]:
    """Return whether the next 24 hours permit spraying at the current hour."""
    frame = _prepare(hourly, cfg)
    return _assess(frame, _local_hour(now, cfg), cfg)


def next_dry_window(hourly: pd.DataFrame, now: datetime, cfg: AppConfig) -> datetime | None:
    """Find the first dry 24-hour window starting during configured daytime."""
    frame = _prepare(hourly, cfg)
    first = _local_hour(now, cfg)
    last = first + pd.Timedelta(days=cfg.spray.search_days)
    candidate = first
    while candidate <= last:
        if cfg.spray.day_start_hour <= candidate.hour <= cfg.spray.day_end_hour:
            dry, _, _ = _assess(frame, candidate, cfg)
            if dry:
                return candidate.to_pydatetime()
        candidate += pd.Timedelta(hours=1)
    return None
