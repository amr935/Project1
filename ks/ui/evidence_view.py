"""Evidence and verification notes shown alongside the prototype rules."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from ..i18n import t


def render_evidence(lang: str, reports_dir: Path) -> None:
    """Display only generated evidence, and mark pending evidence plainly."""
    st.subheader(t("evidence.title", lang))
    metrics_path = Path(reports_dir) / "evidence_metrics.json"
    if metrics_path.is_file():
        try:
            evidence = json.loads(metrics_path.read_text(encoding="utf-8"))
            st.json(evidence, expanded=True)
        except (OSError, json.JSONDecodeError):
            st.warning(t("evidence.invalid", lang))
    else:
        st.info(t("evidence.pending", lang))
    st.markdown(t("evidence.rules", lang))
    st.markdown(t("evidence.validation", lang))
