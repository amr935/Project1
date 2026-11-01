"""Open-Meteo requests, weather parsing, and the local JSON cache."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .models import AppConfig, DistrictConfig, WeatherBundle

logger = logging.getLogger(__name__)


def _get_json(url: str, params: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
    """Fetch JSON with the configured timeout and retry policy."""
    retries = cfg.weather.retries
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=cfg.weather.timeout_seconds)
            status = response.status_code
            retryable_status = status == 429 or status >= 500
            if retryable_status:
                if attempt < retries:
                    time.sleep(attempt + 1)
                    continue
                response.raise_for_status()
                raise requests.HTTPError(f"Open-Meteo returned HTTP {status}")
            if status >= 400:
                response.raise_for_status()
                raise requests.HTTPError(f"Open-Meteo returned HTTP {status}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Open-Meteo response must be a JSON object")
            return payload
        except (requests.Timeout, requests.ConnectionError):
            if attempt >= retries:
                raise
            time.sleep(attempt + 1)
    raise requests.RequestException("Open-Meteo request failed")


def _forecast_params(lat: float, lon: float, cfg: AppConfig) -> dict[str, Any]:
    """Build the configured seven-day history and forecast request."""
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(cfg.weather.hourly_vars),
        "daily": ",".join(cfg.weather.daily_vars),
        "past_days": cfg.weather.past_days,
        "forecast_days": cfg.weather.forecast_days,
        "timezone": cfg.app.timezone,
    }


def fetch_forecast(lat: float, lon: float, cfg: AppConfig) -> dict[str, Any]:
    """Fetch raw hourly and daily forecast JSON from Open-Meteo."""
    return _get_json(cfg.weather.forecast_url, _forecast_params(lat, lon, cfg), cfg)


def _hourly_frame(payload: dict[str, Any], cfg: AppConfig) -> pd.DataFrame:
    """Validate and normalize hourly arrays from an Open-Meteo payload."""
    section = payload.get("hourly")
    required = ("time", *cfg.weather.hourly_vars)
    if not isinstance(section, dict) or any(name not in section for name in required):
        raise ValueError("weather payload is missing required hourly columns")
    frame = pd.DataFrame(section)
    frame["time"] = pd.to_datetime(frame["time"], errors="raise")
    if frame["time"].isna().any():
        raise ValueError("weather payload contains an invalid hourly timestamp")
    for column in cfg.weather.hourly_vars:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.loc[:, list(required)]


def _daily_frame(payload: dict[str, Any], cfg: AppConfig) -> pd.DataFrame:
    """Validate and normalize daily arrays from an Open-Meteo payload."""
    section = payload.get("daily")
    required = ("time", *cfg.weather.daily_vars)
    if not isinstance(section, dict) or any(name not in section for name in required):
        raise ValueError("weather payload is missing required daily columns")
    frame = pd.DataFrame(section)
    dates = pd.to_datetime(frame["time"], errors="raise")
    if dates.isna().any():
        raise ValueError("weather payload contains an invalid daily date")
    frame["date"] = dates.dt.date
    for column in cfg.weather.daily_vars:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.loc[:, ["date", *cfg.weather.daily_vars]]


def _bundle(payload: dict[str, Any], district_id: str, fetched_at: datetime, source: str, cfg: AppConfig) -> WeatherBundle:
    """Create a typed bundle from a validated payload."""
    return WeatherBundle(district_id, _hourly_frame(payload, cfg), _daily_frame(payload, cfg), fetched_at, source)


def _local_time(value: datetime, cfg: AppConfig) -> datetime:
    """Normalize a timestamp to the configured local timezone."""
    zone = ZoneInfo(cfg.app.timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def _district(value: DistrictConfig | str, cfg: AppConfig) -> DistrictConfig | None:
    """Resolve a district record or ID to configured coordinates."""
    if isinstance(value, DistrictConfig):
        return value
    return next((item for item in cfg.districts if item.district_id == value), None)


def _cached_bundle(path: Path, district_id: str, cfg: AppConfig, now: datetime) -> WeatherBundle | None:
    """Load a valid saved bundle and classify its age."""
    if not path.is_file():
        logger.warning("No weather cache found for %s", district_id)
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(saved["fetched_at"])
        fetched_at = _local_time(fetched_at, cfg)
        payload = saved["payload"]
        if not isinstance(payload, dict):
            raise ValueError("cached payload must be a JSON object")
        current = _local_time(now, cfg)
        age_hours = max(0.0, (current - fetched_at).total_seconds() / 3600)
        source = "cache" if age_hours <= cfg.weather.max_cache_age_hours else "stale_cache"
        return _bundle(payload, district_id, fetched_at, source, cfg)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Weather cache for %s is invalid: %s", district_id, exc)
        return None


def load_cached_bundle(district: DistrictConfig | str, cfg: AppConfig, cache_dir: Path, now: datetime) -> WeatherBundle | None:
    """Load a district's saved weather without making a network request."""
    record = _district(district, cfg)
    if record is None:
        logger.error("Unknown district for weather cache: %s", district)
        return None
    return _cached_bundle(Path(cache_dir) / f"{record.district_id}.json", record.district_id, cfg, now)


def load_bundle(district: DistrictConfig | str, cfg: AppConfig, cache_dir: Path, now: datetime) -> WeatherBundle | None:
    """Fetch a district forecast, fall back to cache, and never raise to UI."""
    record = _district(district, cfg)
    if record is None:
        logger.error("Unknown district for weather request: %s", district)
        return None
    cache_path = Path(cache_dir) / f"{record.district_id}.json"
    try:
        payload = fetch_forecast(record.lat, record.lon, cfg)
        fetched_at = _local_time(now, cfg)
        bundle = _bundle(payload, record.district_id, fetched_at, "live", cfg)
    except Exception:
        logger.exception("Weather fetch failed for %s; trying cache", record.district_id)
        return _cached_bundle(cache_path, record.district_id, cfg, now)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"fetched_at": fetched_at.isoformat(), "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.exception("Could not write weather cache for %s", record.district_id)
    return bundle


def fetch_archive(lat: float, lon: float, start: date, end: date, cfg: AppConfig) -> pd.DataFrame:
    """Fetch and normalize hourly archive data for a date range."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(cfg.weather.hourly_vars),
        "timezone": cfg.app.timezone,
    }
    payload = _get_json(cfg.weather.archive_url, params, cfg)
    return _hourly_frame(payload, cfg)
