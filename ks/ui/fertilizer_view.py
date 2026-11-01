"""Fertilizer results and calculation details."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..fertilizer import compute
from ..i18n import t
from ..models import AppConfig, FarmerInputs
from .cards import render_card


def render_fertilizer(inputs: FarmerInputs, cfg: AppConfig, lang: str, doses: pd.DataFrame) -> None:
    """Show product amounts, explanation cards, and transparent arithmetic."""
    try:
        result = compute(inputs, cfg, doses)
    except KeyError:
        crop = _crop_name(inputs.crop_id, cfg, lang)
        st.info(t("fert.no_dose", lang, crop=crop))
        return
    except ValueError:
        if inputs.ph is not None and (inputs.ph < cfg.ph.valid_min or inputs.ph > cfg.ph.valid_max):
            st.error(t("ph.invalid", lang, min=cfg.ph.valid_min, max=cfg.ph.valid_max))
        else:
            st.error(t("fert.bad_area", lang, min=cfg.area.min_ha, max=cfg.area.max_ha))
        return

    crop = _crop_name(inputs.crop_id, cfg, lang)
    unit = t(f"ui.unit.{inputs.area_unit}", lang)
    st.subheader(t("fert.title", lang, crop=crop, area=f"{inputs.area_value:g}", unit=unit))
    for line in result.lines:
        product_name = t(f"product.{line.product}", lang)
        if line.kg < 1:
            st.write(t("fert.line_small", lang, name=product_name))
        else:
            st.write(t("fert.line", lang, name=product_name, kg=f"{line.kg:.0f}", bags=f"{line.bags:.1f}", bag_kg=line.bag_kg))
    for card in result.reasons:
        render_card(card, lang, cfg)

    with st.expander(t("ui.show_maths", lang)):
        st.caption(f"{t('nutrient.N', lang)}: {result.target_n / result.area_ha:.1f} × {result.area_ha:.3f} = {result.target_n:.1f} kg")
        st.caption(f"{t('nutrient.P', lang)}: {result.target_p2o5 / result.area_ha:.1f} × {result.area_ha:.3f} = {result.target_p2o5:.1f} kg")
        st.caption(f"{t('nutrient.K', lang)}: {result.target_k2o / result.area_ha:.1f} × {result.area_ha:.3f} = {result.target_k2o:.1f} kg")
        dap = next(line for line in result.lines if line.product == "dap")
        urea = next(line for line in result.lines if line.product == "urea")
        mop = next(line for line in result.lines if line.product == "mop")
        st.code(
            f"{t('product.dap', lang)}: {result.target_p2o5:.1f} / {cfg.fertilizer.dap_p2o5:.2f} = {dap.kg:.1f} kg\n"
            f"N from DAP: {dap.kg:.1f} × {cfg.fertilizer.dap_n:.2f} = {dap.kg * cfg.fertilizer.dap_n:.1f} kg\n"
            f"{t('product.urea', lang)}: max(0, ({result.target_n:.1f} − N from DAP) / {cfg.fertilizer.urea_n:.2f}) = {urea.kg:.1f} kg\n"
            f"{t('product.mop', lang)}: {result.target_k2o:.1f} / {cfg.fertilizer.mop_k2o:.2f} = {mop.kg:.1f} kg"
        )


def _crop_name(crop_id: str, cfg: AppConfig, lang: str) -> str:
    """Return the configured crop name for the active language."""
    crop = next((item for item in cfg.crops if item.crop_id == crop_id), None)
    if crop is None:
        return crop_id
    return crop.name_hi if lang == "hi" else crop.name_en
