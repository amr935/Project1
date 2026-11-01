"""Tests for bilingual templates and translated date formatting."""

import json
import re
from pathlib import Path

from ks.i18n import t
from ks.timeutil import fmt_when
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z_0-9]*)\}")


def _catalog(language: str) -> dict[str, str]:
    """Load one checked-in translation catalog for assertions."""
    return json.loads((ROOT / "i18n" / f"{language}.json").read_text(encoding="utf-8"))


def test_catalogs_have_identical_keys_and_placeholders() -> None:
    """English and Hindi catalogs expose matching templates."""
    english = _catalog("en")
    hindi = _catalog("hi")

    assert english.keys() == hindi.keys()
    for key in english:
        assert set(PLACEHOLDER.findall(english[key])) == set(PLACEHOLDER.findall(hindi[key])), key


def test_hindi_values_contain_devanagari() -> None:
    """Hindi strings are actually localized, apart from the attribution key."""
    hindi = _catalog("hi")

    for key, value in hindi.items():
        if key == "attribution" or re.fullmatch(r"[\d\W]+", value):
            continue
        assert DEVANAGARI.search(value), key


def test_missing_translation_uses_marker_and_missing_params_are_safe() -> None:
    """Missing keys are visible and incomplete params do not crash rendering."""
    assert t("missing.key", "en") == "[missing: missing.key]"
    assert "{when}" in t("ui.updated", "en")


def test_fmt_when_uses_translation_weekday_lists() -> None:
    """Date formatting uses catalog weekday names without OS locale settings."""
    moment = datetime(2026, 11, 6, 9, 0)

    assert fmt_when(moment, "en") == "Fri 6/11, 09:00"
    assert fmt_when(moment, "hi").startswith("शुक्रवार 6/11, 09:00")
