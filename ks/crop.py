"""Crop model loading, filtered recommendations, reasons, and MSP ranking."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn

from .models import AppConfig, Card, SeasonCropConfig

logger = logging.getLogger(__name__)


def load_model(models_dir: Path) -> tuple[Any, dict[str, Any]] | None:
    """Load the RF and metadata, returning None when artifacts are unavailable."""
    folder = Path(models_dir)
    model_path, meta_path = folder / "crop_rf.joblib", folder / "crop_meta.json"
    if not model_path.is_file() or not meta_path.is_file() or model_path.stat().st_size == 0 or meta_path.stat().st_size == 0:
        return None
    try:
        model = joblib.load(model_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("crop metadata must be a JSON object")
        return model, meta
    except Exception:
        logger.exception("Could not load crop model artifacts from %s", folder)
        return None


def nutrient_presets(meta: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Return N/P/K low, medium, and high presets from saved percentiles."""
    percentiles = meta["nutrient_percentiles"]
    return {
        nutrient: {
            "low": float(percentiles[nutrient]["20"]),
            "medium": float(percentiles[nutrient]["50"]),
            "high": float(percentiles[nutrient]["80"]),
        }
        for nutrient in ("N", "P", "K")
    }


def _reason_features(values: dict[str, float], crop_id: str, meta: dict[str, Any]) -> list[dict[str, float | str]]:
    """Score features by importance and closeness to the crop's mean."""
    stats = meta["class_stats"][crop_id]
    importances = meta["feature_importances"]
    scores = []
    for feature in meta["features"]:
        mean = float(stats["means"][feature])
        std = float(stats["stds"].get(feature, 1.0)) or 1.0
        value = float(values[feature])
        z_score = (value - mean) / std
        score = float(importances[feature]) * math.exp(-abs(z_score))
        scores.append({"feature": feature, "value": value, "typical": mean, "score": score})
    return sorted(scores, key=lambda item: float(item["score"]), reverse=True)[:2]


def _out_of_range(values: dict[str, float], meta: dict[str, Any]) -> list[Card]:
    """Build one template card for every input outside saved feature bounds."""
    ranges = meta.get("feature_ranges", {})
    cards = []
    for feature in meta["features"]:
        bounds = ranges.get(feature)
        if not bounds:
            continue
        value, minimum, maximum = float(values[feature]), float(bounds["min"]), float(bounds["max"])
        if value < minimum or value > maximum:
            cards.append(Card("crop.out_of_range", {"field": feature, "value": value, "min": minimum, "max": maximum}, module="crop"))
    return cards


def recommend(values: dict[str, float], model: Any, meta: dict[str, Any], cfg: AppConfig) -> dict[str, Any]:
    """Filter model probabilities to allowed crops and explain the top match."""
    features = list(meta["features"])
    missing = [feature for feature in features if feature not in values]
    if missing:
        raise ValueError(f"crop inputs are missing features: {', '.join(missing)}")
    row = pd.DataFrame([[float(values[feature]) for feature in features]], columns=features)
    probabilities = np.asarray(model.predict_proba(row), dtype=float)[0]
    classes = list(meta["classes"])
    if len(classes) != len(probabilities):
        raise ValueError("crop metadata classes do not match model probabilities")
    allowed = set(cfg.crop.allowed)
    kept = [(crop_id, float(prob)) for crop_id, prob in zip(classes, probabilities) if crop_id in allowed]
    if not kept or max(prob for _, prob in kept) < cfg.crop.min_confidence:
        return {"status": "no_match"}
    total = sum(prob for _, prob in kept)
    if total <= 0:
        return {"status": "no_match"}
    recommendations = [
        {"crop_id": crop_id, "prob": prob / total}
        for crop_id, prob in sorted(kept, key=lambda item: item[1], reverse=True)[:cfg.crop.top_k]
    ]
    top_crop = recommendations[0]["crop_id"]
    return {
        "status": "ok",
        "recommendations": recommendations,
        "reason_features": _reason_features(values, top_crop, meta),
        "cards": _out_of_range(values, meta),
        "version_mismatch": sklearn.__version__ != meta.get("sklearn_version"),
    }


def _season_rows(table: Any) -> list[dict[str, Any]]:
    """Normalize configured season rows from dataclasses, dicts, or a frame."""
    if isinstance(table, pd.DataFrame):
        return table.to_dict(orient="records")
    records = []
    for item in table:
        if isinstance(item, dict):
            records.append(item)
        elif isinstance(item, SeasonCropConfig):
            records.append({"season": item.season, "months": item.months, "crop_ids": item.crop_ids})
        else:
            records.append({"season": item.season, "months": item.months, "crop_ids": item.crop_ids})
    return records


def _month_values(value: Any) -> tuple[int, ...]:
    """Normalize an integer sequence or pipe-delimited month cell."""
    return tuple(int(part) for part in value.split("|")) if isinstance(value, str) else tuple(int(part) for part in value)


def season_for_month(month: int, season_table: Any) -> str:
    """Return the configured sowing season containing a month."""
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12")
    for row in _season_rows(season_table):
        if month in _month_values(row["months"]):
            return str(row["season"])
    return "unknown"


def season_crops(season: str, season_table: Any) -> list[str]:
    """Return the crop IDs listed for one configured season."""
    for row in _season_rows(season_table):
        if row["season"] == season:
            crop_ids = row["crop_ids"]
            return crop_ids.split("|") if isinstance(crop_ids, str) else list(crop_ids)
    return []


def _as_bool(value: Any) -> bool:
    """Parse MSP verification values supplied as booleans or CSV strings."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() == "true"


def profit_table(crop_ids: list[str], msp: pd.DataFrame) -> list[dict[str, Any]]:
    """Join requested crops to MSP data and rank priced crops by margin."""
    if "crop_id" not in msp.columns:
        raise ValueError("MSP table is missing crop_id")
    rows: list[dict[str, Any]] = []
    for index, crop_id in enumerate(crop_ids):
        matches = msp.loc[msp["crop_id"] == crop_id]
        if matches.empty:
            rows.append({"crop_id": crop_id, "msp_rs_q": None, "cost_rs_q": None, "margin_pct": None, "verified": False, "source": "", "reason_key": "crop.no_price", "_index": index})
            continue
        record = matches.iloc[0].to_dict()
        rows.append({
            "crop_id": crop_id,
            "marketing_year": record.get("marketing_year"),
            "msp_rs_q": float(record["msp_rs_q"]),
            "cost_rs_q": float(record["cost_rs_q"]),
            "margin_pct": float(record["margin_pct"]),
            "verified": _as_bool(record.get("verified", False)),
            "source": str(record.get("source", "")),
            "reason_key": "crop.profit",
            "_index": index,
        })
    rows.sort(key=lambda item: (item["margin_pct"] is None, -(item["margin_pct"] or 0), item["_index"]))
    return [{key: value for key, value in item.items() if key != "_index"} for item in rows]
