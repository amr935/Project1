"""Crop model inputs, recommendations, and MSP ranking."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from ..crop import load_model, nutrient_presets, profit_table, recommend, season_crops, season_for_month
from ..i18n import t
from ..models import AppConfig, WeatherBundle
from ..timeutil import now_ist, now_local_naive
from .cards import render_card


def render_crop_advisor(cfg: AppConfig, lang: str, weather: WeatherBundle | None, models_dir: Path, selected_season: str | None = None) -> None:
    """Render the independent Kaggle-scale crop advisor and profit table."""
    loaded = load_model(models_dir)
    if loaded is None:
        st.info(t("crop.model_missing", lang))
        return
    model, meta = loaded
    if not isinstance(meta.get("feature_medians"), dict):
        st.info(t("crop.meta_incomplete", lang))
        return
    presets = nutrient_presets(meta)
    choices = {"low": t("ui.level.low", lang), "medium": t("ui.level.medium", lang), "high": t("ui.level.high", lang)}
    exact = st.toggle(t("ui.soil.exact.enable", lang), key="crop_exact_toggle")
    values: dict[str, float] = {}
    columns = st.columns(3)
    for column, nutrient in zip(columns, ("N", "P", "K")):
        with column:
            label = t(f"feature.{nutrient}", lang)
            if exact:
                values[nutrient] = st.number_input(label, value=float(presets[nutrient]["medium"]), step=1.0, key=f"crop_exact_{nutrient}")
            else:
                level = st.selectbox(label, ["low", "medium", "high"], format_func=lambda item: choices[item], key=f"crop_band_{nutrient}")
                values[nutrient] = float(presets[nutrient][level])

    temperature, humidity = _weather_defaults(weather, meta)
    env_columns = st.columns(4)
    with env_columns[0]:
        values["temperature"] = st.number_input(t("feature.temperature", lang), value=temperature, step=0.5)
    with env_columns[1]:
        values["humidity"] = st.number_input(t("feature.humidity", lang), value=humidity, step=1.0)
    with env_columns[2]:
        values["ph"] = st.number_input(t("feature.ph", lang), min_value=cfg.ph.valid_min, max_value=cfg.ph.valid_max, value=6.5, step=0.1)
    with env_columns[3]:
        values["rainfall"] = st.number_input(t("feature.rainfall", lang), min_value=0.0, value=float(cfg.crop.default_rainfall_mm), step=5.0)
    st.caption(t("crop.npk_scale_note", lang))
    if not st.button(t("ui.recommend", lang), key="run_crop_recommendation"):
        return

    result = recommend(values, model, meta, cfg)
    if result["status"] == "no_match":
        st.info(t("crop.no_match", lang))
        return
    labels = []
    for item in result["recommendations"]:
        name = _crop_name(item["crop_id"], cfg, lang)
        labels.append(f"{name} ({item['prob']:.0%})")
        st.write(name)
        st.progress(float(item["prob"]))
    st.write(t("crop.top", lang, list=", ".join(labels)))
    reason_names = [t(f"feature.{item['feature']}", lang) for item in result["reason_features"]]
    st.write(t("crop.reason", lang, features=", ".join(reason_names)))
    for card in result["cards"]:
        render_card(card, lang, cfg)
    if result["version_mismatch"]:
        import sklearn

        st.warning(t("crop.version_mismatch", lang, built=meta.get("sklearn_version", "?"), running=sklearn.__version__))

    month = now_ist().month
    season = selected_season or _season_choice(cfg, month)
    seasonal_ids = season_crops(season, cfg.season_crops)
    st.write(t("crop.season_rule", lang, list=", ".join(_crop_name(item, cfg, lang) for item in seasonal_ids)))
    msp_frame = pd.DataFrame([item.__dict__ for item in cfg.msp])
    rankings = profit_table(list(dict.fromkeys([item["crop_id"] for item in result["recommendations"]] + seasonal_ids)), msp_frame)
    st.subheader(t("crop.profit_heading", lang))
    for row in rankings:
        name = _crop_name(row["crop_id"], cfg, lang)
        if row["reason_key"] == "crop.no_price":
            sentence = t("crop.no_price", lang, crop=name)
        else:
            sentence = t("crop.profit", lang, crop=name, msp=f"{row['msp_rs_q']:,.0f}", margin=f"{row['margin_pct']:.0f}")
        if not row["verified"]:
            sentence += f" · ⚠ {t('ui.verify', lang)}"
        st.write(sentence)


def _weather_defaults(weather: WeatherBundle | None, meta: dict) -> tuple[float, float]:
    """Use seven-day forecast means, or saved dataset medians if unavailable."""
    medians = meta["feature_medians"]
    if weather is not None and not weather.hourly.empty:
        frame = weather.hourly.copy()
        frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
        now = pd.Timestamp(now_local_naive())
        window = frame.loc[frame["time"].between(now, now + pd.Timedelta(days=7), inclusive="both")]
        if not window.empty:
            t_values = pd.to_numeric(window["temperature_2m"], errors="coerce").dropna()
            rh_values = pd.to_numeric(window["relative_humidity_2m"], errors="coerce").dropna()
            if not t_values.empty and not rh_values.empty:
                return float(t_values.mean()), float(rh_values.mean())
    return float(medians["temperature"]), float(medians["humidity"])


def _crop_name(crop_id: str, cfg: AppConfig, lang: str) -> str:
    """Return a configured crop name for display."""
    item = next((crop for crop in cfg.crops if crop.crop_id == crop_id), None)
    if item is None:
        return crop_id
    return item.name_hi if lang == "hi" else item.name_en


def _season_choice(cfg: AppConfig, month: int) -> str:
    """Use the selected season or infer it from the current month."""
    return season_for_month(month, cfg.season_crops)
