"""Soil Health Card based fertilizer calculations."""

from __future__ import annotations

import math

import pandas as pd

from .models import AppConfig, Card, FarmerInputs, FertLine, FertResult, SoilLevel

NUTRIENTS = ("N", "P", "K")


def to_hectares(value: float, unit: str, cfg: AppConfig) -> float:
    """Convert a supplied field area to hectares and enforce configured bounds."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("field area must be a finite number")
    factors = {"ha": 1.0, "acre": cfg.area.acre_ha, "bigha": cfg.area.bigha_ha}
    if unit not in factors:
        raise ValueError(f"unsupported area unit: {unit}")
    area_ha = float(value) * factors[unit]
    if area_ha < cfg.area.min_ha or area_ha > cfg.area.max_ha:
        raise ValueError(f"field area must be between {cfg.area.min_ha} and {cfg.area.max_ha} hectares")
    return area_ha


def classify(nutrient: str, kg_ha: float, cfg: AppConfig) -> SoilLevel:
    """Classify an exact Soil Health Card value using configured boundaries."""
    if nutrient not in NUTRIENTS:
        raise ValueError(f"unknown nutrient: {nutrient}")
    if not isinstance(kg_ha, (int, float)) or isinstance(kg_ha, bool) or not math.isfinite(kg_ha):
        raise ValueError("soil value must be a finite number")
    limits = cfg.fertilizer.soil_limits
    low = getattr(limits, f"{nutrient}_low_below")
    high = getattr(limits, f"{nutrient}_high_above")
    if kg_ha < low:
        return SoilLevel.LOW
    if kg_ha <= high:
        return SoilLevel.MEDIUM
    return SoilLevel.HIGH


def _dose_row(crop_id: str, doses: pd.DataFrame) -> dict:
    """Return the configured dose row for one crop or raise KeyError."""
    if "crop_id" not in doses.columns:
        raise ValueError("doses table is missing crop_id")
    matches = doses.loc[doses["crop_id"] == crop_id]
    if matches.empty:
        raise KeyError(crop_id)
    return matches.iloc[0].to_dict()


def _verified(value) -> bool:
    """Interpret a boolean or true/false dose cell strictly."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError("dose verified value must be true or false")


def _soil_levels(inputs: FarmerInputs, cfg: AppConfig) -> tuple[dict[str, SoilLevel], int]:
    """Resolve exact/dropdown levels and count nutrients assumed medium."""
    levels: dict[str, SoilLevel] = {}
    unknown = 0
    for nutrient in NUTRIENTS:
        exact = inputs.soil_values.get(nutrient)
        if exact is not None:
            levels[nutrient] = classify(nutrient, exact, cfg)
            continue
        selected = inputs.soil_levels.get(nutrient, SoilLevel.UNKNOWN)
        if not isinstance(selected, SoilLevel):
            try:
                selected = SoilLevel(selected)
            except ValueError as exc:
                raise ValueError(f"invalid {nutrient} soil level: {selected}") from exc
        if selected is SoilLevel.UNKNOWN:
            levels[nutrient] = SoilLevel.MEDIUM
            unknown += 1
        else:
            levels[nutrient] = selected
    return levels, unknown


def _adjusted(value: float, level: SoilLevel, pct: float) -> float:
    """Apply the configured low/medium/high dose factor."""
    if level is SoilLevel.LOW:
        return value * (1 + pct / 100)
    if level is SoilLevel.HIGH:
        return value * (1 - pct / 100)
    return value


def compute(inputs: FarmerInputs, cfg: AppConfig, doses: pd.DataFrame) -> FertResult:
    """Calculate field totals, fertilizer products, and template reason cards."""
    area_ha = to_hectares(inputs.area_value, inputs.area_unit, cfg)
    if inputs.ph is not None and (not math.isfinite(inputs.ph) or inputs.ph < cfg.ph.valid_min or inputs.ph > cfg.ph.valid_max):
        raise ValueError(f"soil pH must be between {cfg.ph.valid_min} and {cfg.ph.valid_max}")
    dose = _dose_row(inputs.crop_id, doses)
    dose_values = {key: float(dose[key]) for key in ("n_kg_ha", "p2o5_kg_ha", "k2o_kg_ha")}
    verified = _verified(dose.get("verified"))
    levels, unknown = _soil_levels(inputs, cfg)
    factors = {"N": "n_kg_ha", "P": "p2o5_kg_ha", "K": "k2o_kg_ha"}
    target_per_ha = {key: _adjusted(dose_values[field], levels[key], cfg.fertilizer.adjust_pct) for key, field in factors.items()}
    target_n = target_per_ha["N"] * area_ha
    target_p = target_per_ha["P"] * area_ha
    target_k = target_per_ha["K"] * area_ha
    dap_kg = target_p / cfg.fertilizer.dap_p2o5
    n_from_dap = dap_kg * cfg.fertilizer.dap_n
    remaining_n = target_n - n_from_dap
    urea_kg = max(0.0, remaining_n / cfg.fertilizer.urea_n)
    mop_kg = target_k / cfg.fertilizer.mop_k2o
    dap_kg, urea_kg, mop_kg = round(dap_kg, 1), round(urea_kg, 1), round(mop_kg, 1)
    lines = [
        FertLine("dap", dap_kg, round(dap_kg / cfg.fertilizer.dap_bag_kg, 1), cfg.fertilizer.dap_bag_kg),
        FertLine("urea", urea_kg, round(urea_kg / cfg.fertilizer.urea_bag_kg, 1), cfg.fertilizer.urea_bag_kg),
        FertLine("mop", mop_kg, round(mop_kg / cfg.fertilizer.mop_bag_kg, 1), cfg.fertilizer.mop_bag_kg),
    ]

    reasons: list[Card] = []
    if inputs.ph is not None and inputs.ph < cfg.ph.lime_below:
        reasons.append(Card("lime.advice", {"ph": inputs.ph}, priority=2, module="fertilizer"))
    elif inputs.ph is not None and inputs.ph > cfg.ph.alkaline_above:
        reasons.append(Card("ph.alkaline", {"ph": inputs.ph}, priority=2, module="fertilizer"))
    if unknown == len(NUTRIENTS):
        reasons.append(Card("fert.assumed_medium", module="fertilizer"))
    elif unknown:
        reasons.append(Card("fert.assumed_medium_some", module="fertilizer"))
    reason_keys = {SoilLevel.LOW: "fert.reason_low", SoilLevel.MEDIUM: "fert.reason_medium", SoilLevel.HIGH: "fert.reason_high"}
    for nutrient in NUTRIENTS:
        level = levels[nutrient]
        params = {"nutrient": nutrient}
        if level is not SoilLevel.MEDIUM:
            params["pct"] = cfg.fertilizer.adjust_pct
        reasons.append(Card(reason_keys[level], params, module="fertilizer"))
    if remaining_n <= 0:
        reasons.append(Card("fert.dap_covers_n", module="fertilizer"))
    if not verified:
        reasons.append(Card("fert.unverified", {"crop": inputs.crop_id}, module="fertilizer"))
    reasons.append(Card("fert.timing", module="fertilizer"))
    return FertResult(inputs.crop_id, area_ha, round(target_n, 1), round(target_p, 1), round(target_k, 1), lines, reasons, verified)
