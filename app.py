"""KrishiSahayak bilingual farm-planning dashboard."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from datetime import timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st

from ks.agent import run as run_advisor
from ks.config import load_config
from ks.i18n import t
from ks.timeutil import fmt_when, now_ist
from ks.weather import load_bundle, load_cached_bundle
from ks.ui.about_view import render_about
from ks.ui.cards import render_cards, render_text
from ks.ui.crop_view import render_crop_advisor
from ks.ui.evidence_view import render_evidence
from ks.ui.fertilizer_view import render_fertilizer
from ks.ui.risk_map import render_risk_map
from ks.ui.sidebar import draw_sidebar
from ks.ui.weather_strip import render_weather_strip
from ks.blight import blight_days, in_season


ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="KrishiSahayak | कृषि सहायक",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """<style>
    html, body, [class*="st-"] { font-family: system-ui, 'Noto Sans Devanagari', sans-serif; }
    .stApp { background: linear-gradient(180deg, #f5f8f1 0%, #ffffff 350px); }
    [data-testid="stSidebar"] { background: #f0f4e9; border-right: 1px solid #dce5d3; }
    [data-testid="stHeader"] { background: rgba(255,255,255,0.72); }
    .hero { padding: 1rem 0 .35rem; }
    .hero-kicker { color: #52733e; font-size: .82rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
    .hero h1 { color: #173b2a; margin: .3rem 0 .15rem; letter-spacing: -.035em; }
    .hero p { color: #52645a; font-size: 1.06rem; margin: 0 0 .55rem; }
    div[data-testid="stMetric"] { background: #f7f9f4; border: 1px solid #e1e9da; padding: .85rem 1rem; border-radius: 14px; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; border-color: #e3e9df; }
    button[kind="primary"] { background: #315f3b; border-color: #315f3b; }
    .stTabs [data-baseweb="tab-list"] { gap: .35rem; }
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def get_config():
    """Load application catalogs once per server process."""
    return load_config(ROOT / "config")


@st.cache_data(ttl=10800, show_spinner=False)
def get_weather(district_id: str, refresh_version: int):
    """Use saved data on page load and fetch live data only after a refresh request."""
    cfg = get_config()
    if refresh_version == 0:
        return load_cached_bundle(district_id, cfg, ROOT / "data" / "cache", now_ist())
    return load_bundle(district_id, cfg, ROOT / "data" / "cache", now_ist())


def _active_label(key: str, lang: str) -> str:
    return t(f"ui.tab.{key}", lang)


def _download_text(cards, lang: str, cfg, inputs) -> str:
    """Build a plain-text version of the current advice for sharing or saving."""
    district = next((item for item in cfg.districts if item.district_id == inputs.district_id), None)
    crop = next((item for item in cfg.crops if item.crop_id == inputs.crop_id), None)
    district_name = (district.name_hi if lang == "hi" else district.name_en) if district else inputs.district_id
    crop_name = (crop.name_hi if lang == "hi" else crop.name_en) if crop else inputs.crop_id
    unit = t(f"ui.unit.{inputs.area_unit}", lang)
    lines = [t("app.title", lang), f"{t('ui.district', lang)}: {district_name}", f"{t('ui.crop', lang)}: {crop_name}", f"{t('ui.area', lang)}: {inputs.area_value:g} {unit}", ""]
    lines.extend(render_text(card, lang, cfg) for card in cards)
    lines += ["", t("disclaimer", lang)]
    return "\n".join(lines)


def _today(inputs, lang: str, cfg, weather, cards) -> None:
    """Render selected-district weather and the rule-based farmer advice."""
    if weather is None:
        district = next((item for item in cfg.districts if item.district_id == inputs.district_id), None)
        name = (district.name_hi if lang == "hi" else district.name_en) if district else inputs.district_id
        st.warning(t("weather.unavailable", lang, district=name))
    else:
        if weather.source == "live":
            st.caption(f"🟢 {t('ui.live', lang)} · {t('ui.updated', lang, when=fmt_when(weather.fetched_at, lang))}")
        else:
            st.caption(f"🟠 {t('weather.offline', lang, when=fmt_when(weather.fetched_at, lang))}")
        days = []
        if inputs.crop_id == "potato" and in_season(now_ist().month, cfg):
            targets = [now_ist().date() + timedelta(days=offset) for offset in range(7)]
            days = blight_days(weather.hourly, targets, cfg)
        render_weather_strip(weather, days, lang, cfg, now_ist().date())
    st.subheader(_active_label("today", lang))
    render_cards(cards, lang, cfg)
    text = _download_text(cards, lang, cfg, inputs)
    left, right = st.columns([1, 1])
    with left:
        st.download_button(t("ui.download", lang), data=text, file_name="krishisahayak-advice.txt", mime="text/plain", use_container_width=True)
    with right:
        st.link_button(t("ui.share", lang), "https://wa.me/?text=" + quote(text), use_container_width=True)


def main() -> None:
    cfg = get_config()
    inputs, lang, refresh_version = draw_sidebar(cfg)
    st.markdown(
        f"<div class='hero'><div class='hero-kicker'>🌾 {t('app.title', lang)}</div><h1>{t('app.title', lang)}</h1><p>{t('app.tagline', lang)}</p></div>",
        unsafe_allow_html=True,
    )
    st.info(t("disclaimer", lang), icon="ℹ️")

    nav = ["today", "map", "fert", "crop", "evidence", "about"]
    selected = st.radio(
        "sections",
        nav,
        format_func=lambda key: _active_label(key, lang),
        horizontal=True,
        label_visibility="collapsed",
        key="main_navigation",
    )

    if selected == "today":
        with st.spinner(t("ui.live", lang)):
            weather = get_weather(inputs.district_id, refresh_version)
        data = {"doses": pd.DataFrame([asdict(item) for item in cfg.doses])}
        cards = run_advisor(inputs, weather, cfg, data, now_ist())
        _today(inputs, lang, cfg, weather, cards)
    elif selected == "map":
        render_risk_map(cfg, lang, ROOT / "data" / "cache")
    elif selected == "fert":
        st.subheader(_active_label("fert", lang))
        render_fertilizer(inputs, cfg, lang, pd.DataFrame([asdict(item) for item in cfg.doses]))
    elif selected == "crop":
        st.subheader(_active_label("crop", lang))
        weather = get_weather(inputs.district_id, refresh_version)
        render_crop_advisor(cfg, lang, weather, ROOT / "models", inputs.season)
    elif selected == "evidence":
        render_evidence(lang, ROOT / "reports")
    elif selected == "about":
        render_about(lang)

    st.divider()
    st.caption(f"{t('attribution', lang)} · {t('disclaimer', lang)}")


if __name__ == "__main__":
    main()
