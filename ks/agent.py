"""Rule-based perceive-decide-act-explain advice coordinator."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .blight import blight_days, in_season, week_summary
from .fertilizer import compute, to_hectares
from .models import AppConfig, Card, FarmerInputs, Level, WeatherBundle
from .spray import next_dry_window, spray_now

logger = logging.getLogger(__name__)


def _local_now(now: datetime, cfg: AppConfig) -> datetime:
    """Return a naive configured-local clock value for hourly data matching."""
    if now.tzinfo is not None:
        return now.astimezone(ZoneInfo(cfg.app.timezone)).replace(tzinfo=None)
    return now


def _district_name(district_id: str, cfg: AppConfig) -> str:
    """Return the configured English district name or its ID fallback."""
    return next((item.name_en for item in cfg.districts if item.district_id == district_id), district_id)


def _rule_blight(inputs: FarmerInputs, weather: WeatherBundle, cfg: AppConfig, now: datetime) -> tuple[list[Card], bool]:
    """Apply crop, season, and seven-day potato blight rules."""
    if inputs.crop_id != "potato":
        return [Card("blight.not_potato", {"crop": inputs.crop_id}, module="blight")], False
    local_now = _local_now(now, cfg)
    if not in_season(local_now.month, cfg):
        return [Card("blight.off_season", module="blight")], False
    days = [local_now.date() + timedelta(days=offset) for offset in range(7)]
    details = blight_days(weather.hourly, days, cfg)
    worst, first_date = week_summary(details)
    if worst is Level.NO_DATA or first_date is None:
        return [Card("blight.no_data", {"date": local_now.date().isoformat()}, module="blight")], False
    chosen = next(item for item in details if item.day == first_date and item.level is worst)
    params = {
        "date": chosen.day.isoformat(),
        "rh_hours": chosen.rh_hours,
        "t_hours": chosen.t_hours,
        "rh_limit": cfg.blight.rh_hours_required,
        "t_limit": cfg.blight.t_hours_required,
    }
    keys = {Level.RED: ("blight.red", 1), Level.YELLOW: ("blight.yellow", 2), Level.GREEN: ("blight.green", 3)}
    key, priority = keys.get(worst, ("blight.no_data", 3))
    return [Card(key, params, priority=priority, module="blight")], worst is Level.RED


def _rule_spray(weather: WeatherBundle, cfg: AppConfig, now: datetime, urgent: bool) -> list[Card]:
    """Apply current spray checks and return safe or next-window advice."""
    ok, reason, params = spray_now(weather.hourly, now, cfg)
    if urgent and not ok:
        next_window = next_dry_window(weather.hourly, now, cfg)
        if next_window is None:
            return [Card("spray.no_window", priority=1, module="spray")]
        return [Card("spray.urgent_combined", {"when": next_window}, priority=1, module="spray")]
    if ok:
        return [Card("spray.ok", priority=3, module="spray"), Card("spray.safety", priority=3, module="spray")]
    cards = [Card(reason, params, priority=2, module="spray")]
    next_window = next_dry_window(weather.hourly, now, cfg)
    if next_window is None:
        cards.append(Card("spray.no_window", priority=2, module="spray"))
    else:
        cards.append(Card("spray.next_window", {"when": next_window}, priority=2, module="spray"))
    return cards


def _ph_cards(inputs: FarmerInputs, cfg: AppConfig) -> list[Card]:
    """Build pH cards early so lime advice precedes fertilizer reasons."""
    if inputs.ph is None:
        return []
    if inputs.ph < cfg.ph.valid_min or inputs.ph > cfg.ph.valid_max:
        return [Card("ph.invalid", {"min": cfg.ph.valid_min, "max": cfg.ph.valid_max}, priority=2, module="fertilizer")]
    if inputs.ph < cfg.ph.lime_below:
        return [Card("lime.advice", {"ph": inputs.ph}, priority=2, module="fertilizer")]
    if inputs.ph > cfg.ph.alkaline_above:
        return [Card("ph.alkaline", {"ph": inputs.ph}, priority=2, module="fertilizer")]
    return []


def _rule_fertilizer(inputs: FarmerInputs, cfg: AppConfig, data: dict[str, Any] | None) -> list[Card]:
    """Calculate fertilizer product cards and handle expected input failures."""
    cards = _ph_cards(inputs, cfg)
    if any(card.key == "ph.invalid" for card in cards):
        return cards
    try:
        to_hectares(inputs.area_value, inputs.area_unit, cfg)
    except ValueError:
        cards.append(Card("fert.bad_area", {"min": cfg.area.min_ha, "max": cfg.area.max_ha}, priority=2, module="fertilizer"))
        return cards
    doses = data.get("doses") if data else None
    if doses is None:
        doses = pd.DataFrame([asdict(item) for item in cfg.doses])
    try:
        result = compute(inputs, cfg, doses)
    except KeyError:
        cards.append(Card("fert.no_dose", {"crop": inputs.crop_id}, priority=2, module="fertilizer"))
        return cards
    except Exception:
        logger.exception("Fertilizer rule failed for %s", inputs.crop_id)
        cards.append(Card("general.section_failed", {"section": "fertilizer"}, priority=2, module="fertilizer"))
        return cards
    for line in result.lines:
        params = {"name": f"product.{line.product}"}
        if line.kg < 1:
            cards.append(Card("fert.line_small", params, module="fertilizer"))
        else:
            cards.append(Card("fert.line", {**params, "kg": line.kg, "bags": line.bags, "bag_kg": line.bag_kg}, module="fertilizer"))
    cards.extend(card for card in result.reasons if card.key not in {"lime.advice", "ph.alkaline"})
    return cards


def run(inputs: FarmerInputs, weather: WeatherBundle | None, cfg: AppConfig, data: dict[str, Any] | None, now: datetime) -> list[Card]:
    """Run each independent rule and return stable priority-sorted cards."""
    cards: list[Card] = []
    if weather is None:
        cards.append(Card("weather.unavailable", {"district": _district_name(inputs.district_id, cfg)}, priority=2, module="weather"))
    else:
        if weather.source in {"cache", "stale_cache"}:
            cards.append(Card("weather.offline", {"when": weather.fetched_at}, priority=2, module="weather"))
        urgent = False
        try:
            blight_cards, urgent = _rule_blight(inputs, weather, cfg, now)
            cards.extend(blight_cards)
        except Exception:
            logger.exception("Blight rule failed for %s", inputs.district_id)
            cards.append(Card("general.section_failed", {"section": "blight"}, priority=2, module="blight"))
        try:
            cards.extend(_rule_spray(weather, cfg, now, urgent))
        except Exception:
            logger.exception("Spray rule failed for %s", inputs.district_id)
            cards.append(Card("general.section_failed", {"section": "spray"}, priority=2, module="spray"))
    try:
        cards.extend(_rule_fertilizer(inputs, cfg, data))
    except Exception:
        logger.exception("Fertilizer rule failed for %s", inputs.crop_id)
        cards.append(Card("general.section_failed", {"section": "fertilizer"}, priority=2, module="fertilizer"))
    cards.append(Card("general.kcc", priority=3, module="general"))
    return sorted(cards, key=lambda card: card.priority)
