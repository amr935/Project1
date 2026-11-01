"""Farmer input controls and language persistence."""

from __future__ import annotations

import streamlit as st

from ..i18n import t
from ..models import AppConfig, FarmerInputs, SoilLevel


def _initial_language(cfg: AppConfig) -> str:
    """Read the language from session state, then a shared URL, then config."""
    if "lang" in st.session_state:
        return st.session_state["lang"]
    query_language = st.query_params.get("lang", cfg.app.default_language)
    return query_language if query_language in {"en", "hi"} else cfg.app.default_language


def _crop_label(crop_id: str, cfg: AppConfig, lang: str) -> str:
    """Return a localized crop name for the selector."""
    crop = next(item for item in cfg.crops if item.crop_id == crop_id)
    return crop.name_hi if lang == "hi" else crop.name_en


def draw_sidebar(cfg: AppConfig) -> tuple[FarmerInputs, str, int]:
    """Collect bilingual farmer inputs and a weather refresh version."""
    current_lang = _initial_language(cfg)
    language_options = {"English": "en", "हिंदी": "hi"}
    chosen = st.sidebar.radio(
        t("ui.language", current_lang),
        list(language_options),
        index=list(language_options.values()).index(current_lang),
        horizontal=True,
        key="language_radio",
    )
    lang = language_options[chosen]
    st.session_state["lang"] = lang
    if st.query_params.get("lang") != lang:
        st.query_params["lang"] = lang

    districts = sorted(cfg.districts, key=lambda item: (item.state, item.name_en))
    district_ids = [item.district_id for item in districts]
    district_id = st.sidebar.selectbox(
        t("ui.district", lang),
        district_ids,
        index=district_ids.index("nalanda") if "nalanda" in district_ids else 0,
        format_func=lambda value: next(
            f"{item.state} · {item.name_hi if lang == 'hi' else item.name_en}"
            for item in districts if item.district_id == value
        ),
    )
    crop_ids = [item.crop_id for item in cfg.crops]
    crop_id = st.sidebar.selectbox(
        t("ui.crop", lang), crop_ids,
        index=crop_ids.index("potato") if "potato" in crop_ids else 0,
        format_func=lambda value: _crop_label(value, cfg, lang),
    )
    area_value = st.sidebar.number_input(t("ui.area", lang), min_value=0.01, value=1.0, step=0.1)
    area_unit = st.sidebar.selectbox(
        t("ui.unit", lang), ["ha", "acre", "bigha"],
        format_func=lambda value: t(f"ui.unit.{value}", lang),
    )
    if area_unit == "bigha":
        st.sidebar.caption(t("ui.bigha_note", lang))

    st.sidebar.markdown(f"**{t('ui.soil', lang)}**")
    soil_levels: dict[str, SoilLevel] = {}
    for nutrient in ("N", "P", "K"):
        soil_levels[nutrient] = st.sidebar.selectbox(
            t(f"nutrient.{nutrient}", lang),
            list(SoilLevel),
            format_func=lambda value: t(f"ui.level.{value.value}", lang),
            key=f"soil_level_{nutrient}",
        )
    soil_values: dict[str, float | None] = {key: None for key in ("N", "P", "K")}
    with st.sidebar.expander(t("ui.soil.exact", lang)):
        exact_enabled = st.checkbox(t("ui.soil.exact.enable", lang), key="soil_exact_enabled")
        if exact_enabled:
            for nutrient in ("N", "P", "K"):
                raw_value = st.text_input(
                    f"{t(f'nutrient.{nutrient}', lang)} (kg/ha)",
                    placeholder=t("ui.soil.exact.placeholder", lang), key=f"soil_exact_{nutrient}",
                )
                if raw_value.strip():
                    try:
                        exact_value = float(raw_value.strip().replace(",", "."))
                        if exact_value < 0:
                            raise ValueError
                        soil_values[nutrient] = exact_value
                    except ValueError:
                        st.sidebar.warning(t("ui.soil.exact.invalid", lang, nutrient=t(f"nutrient.{nutrient}", lang)))

    ph = None
    if st.sidebar.checkbox(t("ui.ph.known", lang), key="ph_known"):
        ph = st.sidebar.number_input(t("ui.ph.known", lang), min_value=cfg.ph.valid_min, max_value=cfg.ph.valid_max, value=6.5, step=0.1)
    season_label = st.sidebar.selectbox(
        t("ui.season", lang), ["auto", "kharif", "rabi", "zaid"],
        format_func=lambda value: t(f"season.{value}", lang),
    )
    if st.sidebar.button(t("ui.refresh", lang), use_container_width=True):
        st.session_state["weather_refresh"] = st.session_state.get("weather_refresh", 0) + 1
    refresh = int(st.session_state.get("weather_refresh", 0))
    inputs = FarmerInputs(
        district_id, crop_id, float(area_value), area_unit, soil_levels, soil_values,
        ph=ph, season=None if season_label == "auto" else season_label,
    )
    return inputs, lang, refresh
