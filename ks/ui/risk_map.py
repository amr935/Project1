"""District-level potato late-blight risk map from saved weather snapshots."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ..blight import blight_days, in_season, week_summary
from ..i18n import t
from ..models import AppConfig, Level
from ..timeutil import fmt_when, now_ist
from ..weather import load_cached_bundle


def render_risk_map(cfg: AppConfig, lang: str, cache_dir: Path) -> None:
    """Show a fast, offline-first district map with its freshness visible."""
    st.subheader(t("map.title", lang))
    st.caption(t("map.caption", lang))
    now = now_ist()
    if not in_season(now.month, cfg):
        st.info(t("blight.off_season", lang))

    def inspect(district):
        bundle = load_cached_bundle(district.district_id, cfg, cache_dir, now)
        if bundle is None or not in_season(now.month, cfg):
            return district, None, None
        targets = [now.date() + timedelta(days=offset) for offset in range(7)]
        days = blight_days(bundle.hourly, targets, cfg)
        level, day = week_summary(days)
        return district, level, (bundle, day)

    results = []
    with st.spinner(t("map.loading", lang)):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(inspect, district) for district in cfg.districts]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    results.append((None, None, None))
    results = [item for item in results if item[0] is not None]
    results.sort(key=lambda item: (item[0].state, item[0].name_en))
    palette = {Level.RED: "red", Level.YELLOW: "orange", Level.GREEN: "green", Level.NO_DATA: "gray", Level.OFF_SEASON: "blue"}
    statuses = []
    for district, level, details in results:
        name = district.name_hi if lang == "hi" else district.name_en
        if level is None:
            label = t("ui.level_word.no_data", lang)
            observed = "—"
            saved = "—"
            color = palette[Level.NO_DATA]
        else:
            label = t(f"ui.level_word.{level.value}", lang)
            observed = details[1].isoformat() if details[1] else "—"
            saved = fmt_when(details[0].fetched_at, lang)
            if details[0].source == "stale_cache":
                saved += f" · {t('map.stale', lang)}"
            color = palette.get(level, "gray")
        statuses.append({"district": district, "name": name, "level": level, "label": label, "observed": observed, "saved": saved, "color": color})

    available = [row for row in statuses if row["level"] is not None]
    if available:
        center = [sum(row["district"].lat for row in available) / len(available), sum(row["district"].lon for row in available) / len(available)]
        map_view = folium.Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
        for row in statuses:
            district = row["district"]
            label = f"{row['name']} · {row['label']} · {row['observed']}"
            folium.CircleMarker(
                location=[district.lat, district.lon], radius=8,
                color=row["color"], fill=True, fill_color=row["color"], fill_opacity=0.82,
                tooltip=label, popup=label,
            ).add_to(map_view)
        st_folium(map_view, height=430, width=900, returned_objects=[])
    else:
        st.info(t("map.empty", lang))

    frame = pd.DataFrame([
        {t("ui.district", lang): row["name"], t("map.risk", lang): row["label"], t("map.observed", lang): row["observed"], t("map.saved", lang): row["saved"]}
        for row in statuses
    ])
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.caption(t("map.freshness", lang))
