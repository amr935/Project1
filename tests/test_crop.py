"""Tests for crop recommendations, season rules, and MSP ranking."""

from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import sklearn

from ks.crop import load_model, nutrient_presets, profit_table, recommend, season_crops, season_for_month


ROOT = Path(__file__).resolve().parents[1]


class _FixedModel:
    """Minimal probability model used to exercise recommendation rules."""

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        """Return fixed scores in metadata class order."""
        return np.array([[0.4, 0.3, 0.3]])


def _meta(cfg) -> dict:
    """Build compact metadata for deterministic recommendation tests."""
    features = list(cfg.crop.features)
    return {
        "features": features,
        "classes": ["rice", "jute", "wheat"],
        "feature_ranges": {key: {"min": 0.0, "max": 100.0} for key in features},
        "nutrient_percentiles": {key: {"20": 10.0, "50": 20.0, "80": 30.0} for key in ("N", "P", "K")},
        "class_stats": {
            crop: {"means": {key: 50.0 for key in features}, "stds": {key: 10.0 for key in features}}
            for crop in ("rice", "jute", "wheat")
        },
        "feature_importances": {key: 1.0 / len(features) for key in features},
        "sklearn_version": sklearn.__version__,
    }


def _values(cfg) -> dict[str, float]:
    """Return one valid numeric row in configured model-feature order."""
    return {key: 50.0 for key in cfg.crop.features}


def test_missing_model_returns_none() -> None:
    """Absent or placeholder model files do not crash model loading."""
    assert load_model(ROOT / "models") is None


def test_recommendation_filters_allowed_and_renormalizes(cfg) -> None:
    """Only allowed labels remain and their scores sum to one."""
    result = recommend(_values(cfg), _FixedModel(), _meta(cfg), cfg)
    picks = result["recommendations"]

    assert result["status"] == "ok"
    assert len(picks) <= 3
    assert all(item["crop_id"] in cfg.crop.allowed for item in picks)
    assert sum(item["prob"] for item in picks) == pytest.approx(1.0)
    assert len(result["reason_features"]) == 2


def test_recommendation_reports_each_out_of_range_feature(cfg) -> None:
    """A rainfall value above training bounds creates a template card."""
    values = _values(cfg)
    values["rainfall"] = 5000.0

    result = recommend(values, _FixedModel(), _meta(cfg), cfg)

    assert any(card.key == "crop.out_of_range" and card.params["field"] == "rainfall" for card in result["cards"])


def test_low_allowed_probability_returns_no_match(cfg) -> None:
    """A weak best allowed class is rejected before normalization."""
    class LowModel:
        """Model with low probability on every allowed label."""

        def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
            """Return scores below the configured confidence floor."""
            return np.array([[0.01, 0.01, 0.98]])

    assert recommend(_values(cfg), LowModel(), _meta(cfg), cfg) == {"status": "no_match"}


def test_profit_table_sorts_margin_and_missing_price_last(cfg) -> None:
    """Verified and placeholder MSP rows are ordered by margin."""
    frame = pd.DataFrame([asdict(row) for row in cfg.msp])
    table = profit_table(["mustard", "wheat", "rice"], frame)

    assert [row["crop_id"] for row in table] == ["wheat", "mustard", "rice"]
    assert table[-1]["reason_key"] == "crop.no_price"


def test_season_helpers_use_configured_rule_table(cfg) -> None:
    """Month lookup and crop lookup use the configured month lists."""
    assert season_for_month(11, cfg.season_crops) == "rabi"
    assert season_for_month(7, cfg.season_crops) == "kharif"
    assert season_for_month(4, cfg.season_crops) == "zaid"
    assert "wheat" in season_crops("rabi", cfg.season_crops)


def test_model_predicts_training_row_zero_when_artifacts_exist() -> None:
    """The trained random forest reproduces its first source row when present."""
    dataset = ROOT / "data" / "raw" / "Crop_recommendation.csv"
    loaded = load_model(ROOT / "models")
    if loaded is None or not dataset.is_file() or dataset.stat().st_size == 0:
        pytest.skip("trained model or Kaggle dataset is unavailable; run scripts/train_crop_model.py after downloading it")
    model, meta = loaded
    frame = pd.read_csv(dataset)
    features = meta["features"]
    expected = frame.loc[0, "label"]

    assert model.predict(frame.loc[[0], features])[0] == expected


def test_nutrient_presets_read_saved_percentiles(cfg) -> None:
    """N, P, and K defaults map to the configured metadata percentiles."""
    presets = nutrient_presets(_meta(cfg))

    assert presets["N"] == {"low": 10.0, "medium": 20.0, "high": 30.0}
