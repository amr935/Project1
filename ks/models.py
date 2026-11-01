"""Shared typed data contracts for KrishiSahayak logic modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


class Level(str, Enum):
    """Blight risk level or an explicit unavailable/off-season state."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    NO_DATA = "no_data"
    OFF_SEASON = "off_season"


class SoilLevel(str, Enum):
    """Soil Health Card category supplied for a nutrient."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class FarmerInputs:
    """Farmer-provided crop, area, soil, and season information."""

    district_id: str
    crop_id: str
    area_value: float
    area_unit: str
    soil_levels: dict[str, SoilLevel]
    soil_values: dict[str, float | None]
    ph: float | None = None
    season: str | None = None


@dataclass
class WeatherBundle:
    """Hourly and daily weather data for one district."""

    district_id: str
    hourly: pd.DataFrame
    daily: pd.DataFrame
    fetched_at: datetime
    source: str


@dataclass
class BlightDay:
    """Blight observations and classified level for one date."""

    day: date
    rh_hours: int
    t_hours: int
    missing_fraction: float
    level: Level


@dataclass
class FertLine:
    """Fertilizer product amount for a field."""

    product: str
    kg: float
    bags: float
    bag_kg: int


@dataclass
class FertResult:
    """Fertilizer targets, product lines, and explanation cards."""

    crop_id: str
    area_ha: float
    target_n: float
    target_p2o5: float
    target_k2o: float
    lines: list[FertLine]
    reasons: list[Card]
    dose_verified: bool


@dataclass
class Card:
    """Template-backed farmer advice with urgency and module metadata."""

    key: str
    params: dict[str, Any] = field(default_factory=dict)
    priority: int = 3
    module: str = "general"


@dataclass(frozen=True)
class AppSettings:
    name: str
    default_language: str
    timezone: str


@dataclass(frozen=True)
class FeatureSettings:
    crop_advisor: bool
    risk_map: bool
    leaf_scanner: bool


@dataclass(frozen=True)
class WeatherSettings:
    forecast_url: str
    archive_url: str
    hourly_vars: tuple[str, ...]
    daily_vars: tuple[str, ...]
    past_days: int
    forecast_days: int
    timeout_seconds: int
    retries: int
    cache_ttl_seconds: int
    max_cache_age_hours: int


@dataclass(frozen=True)
class BlightSettings:
    rh_threshold: float
    rh_hours_required: int
    t_min: float
    t_max: float
    t_hours_required: int
    window_hours: int
    yellow_fraction: float
    max_missing_fraction: float
    season_months: tuple[int, ...]


@dataclass(frozen=True)
class SpraySettings:
    rain_mm_24h_max: float
    rain_prob_max: float
    wind_kmh_max: float
    day_start_hour: int
    day_end_hour: int
    search_days: int


@dataclass(frozen=True)
class SoilLimits:
    N_low_below: float
    N_high_above: float
    P_low_below: float
    P_high_above: float
    K_low_below: float
    K_high_above: float


@dataclass(frozen=True)
class FertilizerSettings:
    adjust_pct: float
    urea_n: float
    dap_n: float
    dap_p2o5: float
    mop_k2o: float
    urea_bag_kg: int
    dap_bag_kg: int
    mop_bag_kg: int
    soil_limits: SoilLimits


@dataclass(frozen=True)
class PhSettings:
    valid_min: float
    valid_max: float
    lime_below: float
    alkaline_above: float


@dataclass(frozen=True)
class AreaSettings:
    min_ha: float
    max_ha: float
    acre_ha: float
    bigha_ha: float


@dataclass(frozen=True)
class CropSettings:
    features: tuple[str, ...]
    allowed: tuple[str, ...]
    top_k: int
    min_confidence: float
    default_rainfall_mm: float


@dataclass(frozen=True)
class DistrictConfig:
    district_id: str
    name_en: str
    name_hi: str
    state: str
    lat: float
    lon: float


@dataclass(frozen=True)
class CropConfig:
    crop_id: str
    name_en: str
    name_hi: str
    in_ml_model: bool
    has_dose: bool
    potato_blight: bool


@dataclass(frozen=True)
class DoseConfig:
    crop_id: str
    n_kg_ha: float
    p2o5_kg_ha: float
    k2o_kg_ha: float
    verified: bool
    source: str


@dataclass(frozen=True)
class MspConfig:
    crop_id: str
    marketing_year: str
    msp_rs_q: float
    cost_rs_q: float
    margin_pct: float
    verified: bool
    source: str


@dataclass(frozen=True)
class SeasonCropConfig:
    season: str
    months: tuple[int, ...]
    crop_ids: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    app: AppSettings
    features: FeatureSettings
    weather: WeatherSettings
    blight: BlightSettings
    spray: SpraySettings
    fertilizer: FertilizerSettings
    ph: PhSettings
    area: AreaSettings
    crop: CropSettings
    districts: tuple[DistrictConfig, ...]
    crops: tuple[CropConfig, ...]
    doses: tuple[DoseConfig, ...]
    msp: tuple[MspConfig, ...]
    season_crops: tuple[SeasonCropConfig, ...]
    config_dir: Path
