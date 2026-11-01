"""Project notes and safety limitations."""

from __future__ import annotations

import streamlit as st

from ..i18n import t


def render_about(lang: str) -> None:
    """Explain prototype scope, data sources, and practical limitations."""
    st.subheader(t("about.title", lang))
    st.markdown(t("about.body", lang))
    st.info(t("disclaimer", lang))
    st.markdown(t("about.sources", lang))
    st.caption(t("attribution", lang))
