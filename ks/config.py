"""Load and validate KrishiSahayak TOML and CSV configuration."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any

import pandas as pd

from .models import (
    AppConfig, AppSettings, AreaSettings, BlightSettings, CropConfig,
    CropSettings, DistrictConfig, DoseConfig, FeatureSettings,
    FertilizerSettings, MspConfig, PhSettings, SeasonCropConfig,
    SoilLimits, SpraySettings, WeatherSettings,
)


class ConfigError(ValueError):
    """Raised when a required configuration value is invalid or missing."""


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a required TOML table or raise a readable error."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"settings.toml: [{key}] table is missing or invalid")
    return value


def _value(table: dict[str, Any], key: str, kind: type, section: str) -> Any:
    """Return a TOML value after checking its declared type."""
    if key not in table:
        raise ConfigError(f"settings.toml: missing [{section}].{key}")
    value = table[key]
    valid = isinstance(value, (int, float)) and not isinstance(value, bool) if kind is float else isinstance(value, kind)
    if not valid:
        raise ConfigError(f"settings.toml: [{section}].{key} must be {kind.__name__}")
    if kind is float:
        value = float(value)
        if not math.isfinite(value):
            raise ConfigError(f"settings.toml: [{section}].{key} must be finite")
    return value


def _list(table: dict[str, Any], key: str, section: str, item_type: type) -> tuple[Any, ...]:
    """Return a typed TOML array as an immutable tuple."""
    values = _value(table, key, list, section)
    if not all(isinstance(item, item_type) and not isinstance(item, bool) for item in values):
        raise ConfigError(f"settings.toml: [{section}].{key} must contain {item_type.__name__} values")
    if item_type is str and not all(values):
        raise ConfigError(f"settings.toml: [{section}].{key} cannot contain empty strings")
    return tuple(values)


def _many(table: dict[str, Any], keys: tuple[str, ...], section: str, kind: type) -> list[Any]:
    """Read several required values of one type from a TOML table."""
    return [_value(table, key, kind, section) for key in keys]


def _rows(folder: Path, filename: str, required: tuple[str, ...]) -> list[dict[str, str]]:
    """Read CSV records after checking required headers and row presence."""
    try:
        frame = pd.read_csv(folder / filename, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ConfigError(f"{filename}: could not read CSV ({exc})") from exc
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ConfigError(f"{filename}: missing columns {', '.join(missing)}")
    if frame.empty:
        raise ConfigError(f"{filename}: no data rows")
    return frame.to_dict(orient="records")


def _text(row: dict[str, str], key: str, filename: str, allow_empty: bool = False) -> str:
    """Return a required text cell from a CSV row."""
    value = row.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{filename}: {key} must be a non-empty string")
    return value


def _number(row: dict[str, str], key: str, filename: str) -> float:
    """Parse a finite numeric CSV cell."""
    try:
        result = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{filename}: {key} must be numeric") from exc
    if not math.isfinite(result):
        raise ConfigError(f"{filename}: {key} must be finite")
    return result


def _boolean(row: dict[str, str], key: str, filename: str) -> bool:
    """Parse a strict true/false CSV cell."""
    value = row.get(key, "").strip().lower()
    if value not in {"true", "false"}:
        raise ConfigError(f"{filename}: {key} must be true or false")
    return value == "true"


def _split(value: str, filename: str, field: str) -> tuple[str, ...]:
    """Split a pipe-delimited cell and reject empty entries."""
    result = tuple(part.strip() for part in value.split("|"))
    if not result or any(not item for item in result):
        raise ConfigError(f"{filename}: {field} must contain pipe-delimited values")
    return result


def _unique(rows: tuple[Any, ...], field: str, filename: str) -> None:
    """Reject duplicate identifiers in a catalog."""
    values = [getattr(row, field) for row in rows]
    if len(values) != len(set(values)):
        raise ConfigError(f"{filename}: duplicate {field} values")


def _load_csvs(folder: Path) -> tuple[tuple[Any, ...], ...]:
    """Load each catalog CSV into typed immutable records."""
    districts = tuple(DistrictConfig(_text(r, "district_id", "districts.csv"), _text(r, "name_en", "districts.csv"), _text(r, "name_hi", "districts.csv"), _text(r, "state", "districts.csv"), _number(r, "lat", "districts.csv"), _number(r, "lon", "districts.csv")) for r in _rows(folder, "districts.csv", ("district_id", "name_en", "name_hi", "state", "lat", "lon")))
    crops = tuple(CropConfig(_text(r, "crop_id", "crops.csv"), _text(r, "name_en", "crops.csv"), _text(r, "name_hi", "crops.csv"), _boolean(r, "in_ml_model", "crops.csv"), _boolean(r, "has_dose", "crops.csv"), _boolean(r, "potato_blight", "crops.csv")) for r in _rows(folder, "crops.csv", ("crop_id", "name_en", "name_hi", "in_ml_model", "has_dose", "potato_blight")))
    doses = tuple(DoseConfig(_text(r, "crop_id", "doses.csv"), _number(r, "n_kg_ha", "doses.csv"), _number(r, "p2o5_kg_ha", "doses.csv"), _number(r, "k2o_kg_ha", "doses.csv"), _boolean(r, "verified", "doses.csv"), _text(r, "source", "doses.csv", True)) for r in _rows(folder, "doses.csv", ("crop_id", "n_kg_ha", "p2o5_kg_ha", "k2o_kg_ha", "verified", "source")))
    msp = tuple(MspConfig(_text(r, "crop_id", "msp.csv"), _text(r, "marketing_year", "msp.csv"), _number(r, "msp_rs_q", "msp.csv"), _number(r, "cost_rs_q", "msp.csv"), _number(r, "margin_pct", "msp.csv"), _boolean(r, "verified", "msp.csv"), _text(r, "source", "msp.csv", True)) for r in _rows(folder, "msp.csv", ("crop_id", "marketing_year", "msp_rs_q", "cost_rs_q", "margin_pct", "verified", "source")))
    seasons = []
    for row in _rows(folder, "season_crops.csv", ("season", "months", "crop_ids")):
        try:
            months = tuple(int(item) for item in _split(row["months"], "season_crops.csv", "months"))
        except ValueError as exc:
            raise ConfigError("season_crops.csv: months must be integers") from exc
        seasons.append(SeasonCropConfig(_text(row, "season", "season_crops.csv"), months, _split(row["crop_ids"], "season_crops.csv", "crop_ids")))
    season_rows = tuple(seasons)
    for rows, field, name in ((districts, "district_id", "districts.csv"), (crops, "crop_id", "crops.csv"), (doses, "crop_id", "doses.csv"), (msp, "crop_id", "msp.csv"), (season_rows, "season", "season_crops.csv")):
        _unique(rows, field, name)
    return districts, crops, doses, msp, season_rows


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Load settings and catalog rows into validated dataclasses."""
    folder = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parents[1] / "config"
    try:
        with (folder / "settings.toml").open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"settings.toml: could not load configuration ({exc})") from exc

    app, features = _table(raw, "app"), _table(raw, "features")
    weather, blight, spray = _table(raw, "weather"), _table(raw, "blight"), _table(raw, "spray")
    fert = _table(raw, "fertilizer")
    soil, ph, area, crop = _table(fert, "soil_limits"), _table(raw, "ph"), _table(raw, "area"), _table(raw, "crop")
    app_settings = AppSettings(*_many(app, ("name", "default_language", "timezone"), "app", str))
    if app_settings.default_language not in {"en", "hi"}:
        raise ConfigError("settings.toml: [app].default_language must be en or hi")
    feature_settings = FeatureSettings(*(_value(features, key, bool, "features") for key in ("crop_advisor", "risk_map", "leaf_scanner")))
    weather_settings = WeatherSettings(*_many(weather, ("forecast_url", "archive_url"), "weather", str), _list(weather, "hourly_vars", "weather", str), _list(weather, "daily_vars", "weather", str), *_many(weather, ("past_days", "forecast_days", "timeout_seconds", "retries", "cache_ttl_seconds", "max_cache_age_hours"), "weather", int))
    blight_settings = BlightSettings(_value(blight, "rh_threshold", float, "blight"), _value(blight, "rh_hours_required", int, "blight"), _value(blight, "t_min", float, "blight"), _value(blight, "t_max", float, "blight"), _value(blight, "t_hours_required", int, "blight"), _value(blight, "window_hours", int, "blight"), _value(blight, "yellow_fraction", float, "blight"), _value(blight, "max_missing_fraction", float, "blight"), _list(blight, "season_months", "blight", int))
    spray_settings = SpraySettings(_value(spray, "rain_mm_24h_max", float, "spray"), _value(spray, "rain_prob_max", int, "spray"), _value(spray, "wind_kmh_max", float, "spray"), *_many(spray, ("day_start_hour", "day_end_hour", "search_days"), "spray", int))
    soil_settings = SoilLimits(*_many(soil, ("N_low_below", "N_high_above", "P_low_below", "P_high_above", "K_low_below", "K_high_above"), "fertilizer.soil_limits", float))
    fert_settings = FertilizerSettings(_value(fert, "adjust_pct", float, "fertilizer"), *_many(fert, ("urea_n", "dap_n", "dap_p2o5", "mop_k2o"), "fertilizer", float), *_many(fert, ("urea_bag_kg", "dap_bag_kg", "mop_bag_kg"), "fertilizer", int), soil_settings)
    ph_settings = PhSettings(*_many(ph, ("valid_min", "valid_max", "lime_below", "alkaline_above"), "ph", float))
    area_settings = AreaSettings(*_many(area, ("min_ha", "max_ha", "acre_ha", "bigha_ha"), "area", float))
    crop_settings = CropSettings(_list(crop, "features", "crop", str), _list(crop, "allowed", "crop", str), _value(crop, "top_k", int, "crop"), _value(crop, "min_confidence", float, "crop"), _value(crop, "default_rainfall_mm", float, "crop"))

    districts, crops, doses, msp, seasons = _load_csvs(folder)
    crop_ids = {item.crop_id for item in crops}
    if {item.crop_id for item in doses} != {item.crop_id for item in crops if item.has_dose}:
        raise ConfigError("doses.csv rows must match crops.csv has_dose=true flags")
    if not set(crop_settings.allowed) <= crop_ids:
        raise ConfigError("settings.toml: [crop].allowed contains an unknown crop_id")
    if any(item.crop_id not in crop_ids for item in msp):
        raise ConfigError("msp.csv contains an unknown crop_id")
    for season in seasons:
        if any(month < 1 or month > 12 for month in season.months):
            raise ConfigError("season_crops.csv: months must be between 1 and 12")
        if not set(season.crop_ids) <= crop_ids:
            raise ConfigError("season_crops.csv: crop_ids contains an unknown crop_id")
    return AppConfig(app_settings, feature_settings, weather_settings, blight_settings, spray_settings, fert_settings, ph_settings, area_settings, crop_settings, districts, crops, doses, msp, seasons, folder.resolve())
