"""Scenario tests for the advice agent's rule order and failure handling."""

from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from conftest import make_hourly
from ks.agent import run
from ks.models import FarmerInputs, WeatherBundle, SoilLevel


NOW = datetime(2026, 11, 20, 10, 0)
IST = ZoneInfo("Asia/Kolkata")


def _inputs(crop: str = "potato", district: str = "nalanda", ph=None, unknown=True) -> FarmerInputs:
    """Create farmer inputs with optional all-unknown soil ratings."""
    levels = {key: SoilLevel.UNKNOWN for key in ("N", "P", "K")} if unknown else {key: SoilLevel.MEDIUM for key in ("N", "P", "K")}
    values = {key: None for key in ("N", "P", "K")}
    return FarmerInputs(district, crop, 1.0, "ha", levels, values, ph)


def _weather(rain_first_hours: int = 0, wet_after_first_day: bool = False, high_blight: bool = True) -> WeatherBundle:
    """Create forecast rows covering all seven blight target windows."""
    start = NOW.replace(hour=0) - timedelta(days=6)
    hours = 13 * 24
    rh = 95 if high_blight else 50
    temperature = 15
    rain = [0.0] * hours
    start_index = int((NOW - start).total_seconds() // 3600)
    for offset in range(rain_first_hours):
        rain[start_index + offset] = 5.0 / 24 if offset < 24 else 0.1
    if wet_after_first_day:
        for offset in range(24, 72):
            rain[start_index + offset] = 0.1
    hourly = make_hourly(start, hours, rh, temperature, rain=rain, wind=5.0, prob=None)
    daily = pd.DataFrame(columns=["date", "temperature_2m_max", "temperature_2m_min", "precipitation_sum"])
    return WeatherBundle("nalanda", hourly, daily, NOW.replace(tzinfo=IST), "live")


def _cards(inputs, weather, cfg, now=NOW):
    """Run the agent with the checked-in dose table."""
    doses = pd.DataFrame([asdict(item) for item in cfg.doses])
    return run(inputs, weather, cfg, {"doses": doses}, now)


def test_s1_red_potato_and_safe_spray(cfg) -> None:
    """A red potato alert is first and safe spray advice is present."""
    cards = _cards(_inputs(), _weather(), cfg)

    assert cards[0].key == "blight.red"
    assert cards[0].priority == 1
    assert any(card.key == "spray.ok" for card in cards)


def test_s2_non_potato_still_gets_spray_rain_advice(cfg) -> None:
    """A wheat crop skips blight but still receives a rain warning."""
    cards = _cards(_inputs("wheat"), _weather(rain_first_hours=24, high_blight=False), cfg)

    assert any(card.key == "blight.not_potato" for card in cards)
    assert any(card.key == "spray.rain" and card.params["rain_mm"] == 5.0 for card in cards)


def test_s3_lime_advice_precedes_fertilizer_cards(cfg) -> None:
    """Acidic soil advice appears before every fertilizer card."""
    cards = _cards(_inputs("wheat", "ranchi", ph=5.0), None, cfg)
    lime_index = next(index for index, card in enumerate(cards) if card.key == "lime.advice")
    fert_indices = [index for index, card in enumerate(cards) if card.key.startswith("fert.")]

    assert fert_indices
    assert lime_index < min(fert_indices)


def test_s4_unknown_soil_uses_standard_dose_math(cfg) -> None:
    """Unknown soil is assumed medium, leaving base product calculations."""
    cards = _cards(_inputs("wheat"), None, cfg)
    assert any(card.key == "fert.assumed_medium" for card in cards)
    lines = {card.params["name"]: card.params for card in cards if card.key == "fert.line"}
    assert lines["product.dap"]["kg"] == 130.4
    assert lines["product.urea"]["kg"] == 209.8
    assert lines["product.mop"]["kg"] == 66.7


def test_s5_red_alert_with_rain_uses_one_combined_spray_card(cfg) -> None:
    """Urgent blight and wet weather produce one future-window card."""
    cards = _cards(_inputs(), _weather(rain_first_hours=72, wet_after_first_day=True), cfg)
    spray_keys = [card.key for card in cards if card.key.startswith("spray.")]

    assert spray_keys.count("spray.urgent_combined") == 1
    assert "when" in next(card for card in cards if card.key == "spray.urgent_combined").params
    assert "spray.rain" not in spray_keys
    assert "spray.ok" not in spray_keys


def test_s6_missing_weather_skips_forecast_rules(cfg) -> None:
    """No weather disables blight/spray while retaining fertilizer advice."""
    cards = _cards(_inputs("wheat"), None, cfg)
    keys = [card.key for card in cards]

    assert "weather.unavailable" in keys
    assert not any(key.startswith(("blight.", "spray.")) for key in keys)
    assert any(key.startswith("fert.") for key in keys)


def test_s7_july_potato_is_off_season(cfg) -> None:
    """An in-season month outside October–March yields the off-season card."""
    july = datetime(2026, 7, 20, 10, 0)
    cards = _cards(_inputs(), _weather_for(july), cfg, now=july)

    assert any(card.key == "blight.off_season" for card in cards)


def _weather_for(now: datetime) -> WeatherBundle:
    """Create enough July rows to calculate all target windows."""
    start = now.replace(hour=0) - timedelta(days=6)
    hourly = make_hourly(start, 13 * 24, 95, 15, rain=0.0, wind=5.0)
    daily = pd.DataFrame(columns=["date", "temperature_2m_max", "temperature_2m_min", "precipitation_sum"])
    return WeatherBundle("nalanda", hourly, daily, now.replace(tzinfo=IST), "live")


def test_s8_crop_without_dose_shows_reason_and_always_ends_with_kcc(cfg) -> None:
    """A crop missing a dose is handled and the KCC card remains last."""
    cards = _cards(_inputs("jute"), None, cfg)

    assert any(card.key == "fert.no_dose" for card in cards)
    assert cards[-1].key == "general.kcc"


def test_last_card_is_always_kcc(cfg) -> None:
    """The standard fully-weathered advice list ends in the call-centre card."""
    assert _cards(_inputs(), _weather(), cfg)[-1].key == "general.kcc"
