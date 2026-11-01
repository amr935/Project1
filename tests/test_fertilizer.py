"""Tests for area conversion, soil classification, and nutrient calculations."""

from dataclasses import asdict

import pandas as pd
import pytest

from ks.fertilizer import classify, compute, to_hectares
from ks.models import FarmerInputs, SoilLevel


def _dose_frame(cfg) -> pd.DataFrame:
    """Convert configured dose rows into the table accepted by compute."""
    return pd.DataFrame([asdict(item) for item in cfg.doses])


def _inputs(crop: str, levels: dict[str, SoilLevel] | None = None, area: float = 1.0, unit: str = "ha", ph: float | None = None, values: dict[str, float | None] | None = None) -> FarmerInputs:
    """Build complete farmer inputs with explicit unknown soil defaults."""
    soil_levels = levels or {key: SoilLevel.UNKNOWN for key in ("N", "P", "K")}
    soil_values = values or {key: None for key in ("N", "P", "K")}
    return FarmerInputs("nalanda", crop, area, unit, soil_levels, soil_values, ph)


def _line(result, product: str):
    """Return one product line by its stable product identifier."""
    return next(item for item in result.lines if item.product == product)


def test_golden_wheat_case(cfg) -> None:
    """The low-N wheat case matches the documented hand calculation."""
    inputs = _inputs("wheat", {"N": SoilLevel.LOW, "P": SoilLevel.MEDIUM, "K": SoilLevel.MEDIUM})
    result = compute(inputs, cfg, _dose_frame(cfg))

    assert _line(result, "dap").kg == pytest.approx(130.4, abs=0.1)
    assert _line(result, "dap").bags == pytest.approx(2.6, abs=0.1)
    assert _line(result, "urea").kg == pytest.approx(275.0, abs=0.1)
    assert _line(result, "urea").bags == pytest.approx(6.1, abs=0.1)
    assert _line(result, "mop").kg == pytest.approx(66.7, abs=0.1)
    assert _line(result, "mop").bags == pytest.approx(1.3, abs=0.1)


def test_lentil_standard_dose_math(cfg) -> None:
    """Medium soil uses the unadjusted lentil targets."""
    levels = {key: SoilLevel.MEDIUM for key in ("N", "P", "K")}
    result = compute(_inputs("lentil", levels), cfg, _dose_frame(cfg))

    assert _line(result, "dap").kg == pytest.approx(87.0, abs=0.1)
    assert _line(result, "urea").kg == pytest.approx(9.5, abs=0.1)
    assert _line(result, "mop").kg == pytest.approx(33.3, abs=0.1)


def test_dap_can_cover_entire_nitrogen_target(cfg) -> None:
    """Urea is clamped at zero and a reason card explains why."""
    levels = {"N": SoilLevel.HIGH, "P": SoilLevel.MEDIUM, "K": SoilLevel.MEDIUM}
    result = compute(_inputs("chickpea", levels), cfg, _dose_frame(cfg))

    assert _line(result, "urea").kg == 0.0
    assert any(card.key == "fert.dap_covers_n" for card in result.reasons)


def test_acre_conversion_uses_configured_factor(cfg) -> None:
    """Acre input is converted before whole-field nutrient totals."""
    levels = {key: SoilLevel.MEDIUM for key in ("N", "P", "K")}
    result = compute(_inputs("wheat", levels, area=1, unit="acre"), cfg, _dose_frame(cfg))

    assert result.target_n == pytest.approx(48.6, abs=0.1)


@pytest.mark.parametrize(
    ("nutrient", "value", "expected"),
    [("N", 279.9, SoilLevel.LOW), ("N", 280, SoilLevel.MEDIUM), ("N", 560, SoilLevel.MEDIUM),
     ("N", 560.1, SoilLevel.HIGH), ("P", 10, SoilLevel.MEDIUM), ("P", 25, SoilLevel.MEDIUM),
     ("P", 25.1, SoilLevel.HIGH), ("K", 120, SoilLevel.MEDIUM), ("K", 280, SoilLevel.MEDIUM)],
)
def test_soil_classification_boundaries(cfg, nutrient, value, expected) -> None:
    """Soil rating boundaries match the inclusive medium ranges."""
    assert classify(nutrient, value, cfg) is expected


@pytest.mark.parametrize("value", [0, -1, 51])
def test_invalid_area_is_rejected(cfg, value) -> None:
    """Area below the minimum or above 50 hectares fails clearly."""
    with pytest.raises(ValueError):
        to_hectares(value, "ha", cfg)


def test_ph_boundaries_and_errors(cfg) -> None:
    """Acidic, neutral-boundary, alkaline, and invalid pH values are handled."""
    levels = {key: SoilLevel.MEDIUM for key in ("N", "P", "K")}
    doses = _dose_frame(cfg)
    assert any(c.key == "lime.advice" for c in compute(_inputs("wheat", levels, ph=5.4), cfg, doses).reasons)
    assert not any(c.key == "lime.advice" for c in compute(_inputs("wheat", levels, ph=5.5), cfg, doses).reasons)
    assert any(c.key == "ph.alkaline" for c in compute(_inputs("wheat", levels, ph=9.0), cfg, doses).reasons)
    with pytest.raises(ValueError):
        compute(_inputs("wheat", levels, ph=11), cfg, doses)


def test_unknown_levels_are_noted_once(cfg) -> None:
    """All-unknown and partially unknown soil levels use separate notes."""
    doses = _dose_frame(cfg)
    all_unknown = compute(_inputs("wheat"), cfg, doses)
    partial = compute(_inputs("wheat", {"N": SoilLevel.LOW, "P": SoilLevel.UNKNOWN, "K": SoilLevel.MEDIUM}), cfg, doses)

    assert [card.key for card in all_unknown.reasons].count("fert.assumed_medium") == 1
    assert not any(card.key == "fert.assumed_medium_some" for card in all_unknown.reasons)
    assert any(card.key == "fert.assumed_medium_some" for card in partial.reasons)


def test_unverified_dose_has_visible_reason(cfg) -> None:
    """A placeholder dose is returned with its verification warning."""
    result = compute(_inputs("wheat"), cfg, _dose_frame(cfg))

    assert not result.dose_verified
    assert any(card.key == "fert.unverified" for card in result.reasons)


def test_bigha_uses_configured_conversion(cfg) -> None:
    """The configured Bihar bigha conversion is applied."""
    assert to_hectares(1, "bigha", cfg) == pytest.approx(cfg.area.bigha_ha)
