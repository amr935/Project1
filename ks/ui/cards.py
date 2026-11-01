"""Streamlit rendering for template-backed advice cards."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from ..i18n import t
from ..models import AppConfig, Card
from ..timeutil import fmt_when


def render_text(card: Card, lang: str, cfg: AppConfig) -> str:
    """Translate a card's structured parameters and return its sentence."""
    params: dict[str, Any] = dict(card.params)
    if "crop" in params:
        crop_id = str(params["crop"])
        item = next((crop for crop in cfg.crops if crop.crop_id == crop_id), None)
        if item:
            params["crop"] = item.name_hi if lang == "hi" else item.name_en
    if "district" in params:
        district_id = str(params["district"])
        district = next((item for item in cfg.districts if item.district_id == district_id), None)
        if district:
            params["district"] = district.name_hi if lang == "hi" else district.name_en
    if "nutrient" in params and str(params["nutrient"]) in {"N", "P", "K"}:
        params["nutrient"] = t(f"nutrient.{params['nutrient']}", lang)
    if "field" in params and f"feature.{params['field']}" in t_catalog(lang):
        params["field"] = t(f"feature.{params['field']}", lang)
    if "name" in params and str(params["name"]).startswith("product."):
        params["name"] = t(str(params["name"]), lang)
    if "when" in params and isinstance(params["when"], datetime):
        params["when"] = fmt_when(params["when"], lang)
    if card.key == "fert.line" and "kg" in params:
        params["kg"] = f"{float(params['kg']):.0f}"
    return t(card.key, lang, **params)


def t_catalog(lang: str) -> dict[str, str]:
    """Return the active catalog for structured feature-key validation."""
    from ..i18n import load

    return load(lang)


def render_card(card: Card, lang: str, cfg: AppConfig) -> None:
    """Display one card with a word label and its localized template."""
    labels = {1: ("🔴", "red"), 2: ("🟠", "yellow"), 3: ("ℹ️", "green")}
    icon, color_word = labels.get(card.priority, labels[3])
    level_word = t(f"ui.level_word.{color_word}", lang)
    with st.container(border=True):
        st.caption(f"{icon} {level_word}")
        st.write(render_text(card, lang, cfg))


def render_cards(cards: list[Card], lang: str, cfg: AppConfig) -> None:
    """Display a sequence of advice cards."""
    for card in cards:
        render_card(card, lang, cfg)
