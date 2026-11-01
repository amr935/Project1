"""Compact seven-day weather summary for the Today tab."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ..i18n import t
from ..models import AppConfig, BlightDay, WeatherBundle


def render_weather_strip(weather: WeatherBundle | None, blight: list[BlightDay], lang: str, cfg: AppConfig, today: date) -> None:
    """Display seven daily forecasts and optional potato blight levels."""
    if weather is None:
        return
    weekday_names = t("weekdays", lang).split("|")
    daily = weather.daily.copy()
    if "date" in daily.columns:
        daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.date
    by_date = {row["date"]: row for _, row in daily.iterrows()} if "date" in daily.columns else {}
    by_blight = {item.day: item for item in blight}
    columns = st.columns(7)
    for offset, column in enumerate(columns):
        day = today + timedelta(days=offset)
        row = by_date.get(day)
        with column:
            st.caption(weekday_names[day.weekday()])
            st.caption(f"{day.day}/{day.month}")
            if row is None:
                st.write("—")
            else:
                high = row.get("temperature_2m_max")
                low = row.get("temperature_2m_min")
                rain = row.get("precipitation_sum")
                st.write(f"{_display(high)}° / {_display(low)}°C")
                st.caption(f"{_display(rain)} mm")
            item = by_blight.get(day)
            if item is not None and cfg.crop is not None:
                word_key = f"ui.level_word.{item.level.value}"
                st.markdown(t(word_key, lang))


def _display(value) -> str:
    """Format a finite forecast number for a compact card."""
    if pd.isna(value):
        return "—"
    return f"{float(value):.0f}"
