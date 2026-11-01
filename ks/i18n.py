"""Render farmer-facing messages from the checked-in language catalogs."""

from __future__ import annotations

import json
from functools import lru_cache
import logging
from pathlib import Path
from typing import Any

from .models import Card

logger = logging.getLogger(__name__)

def _catalog_path() -> Path:
    """Return the project translation directory."""
    return Path(__file__).resolve().parents[1] / "i18n"


@lru_cache(maxsize=2)
def load_catalog(lang: str = "en") -> dict[str, str]:
    """Load one language catalog, returning an empty catalog if unavailable."""
    language = lang if lang in {"en", "hi"} else "en"
    try:
        payload = json.loads((_catalog_path() / f"{language}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in payload.items()):
        return {}
    return payload


def load(lang: str) -> dict[str, str]:
    """Return one validated translation catalog."""
    return load_catalog(lang)


class _SafeValues(dict[str, Any]):
    """Keep an unresolved placeholder visible instead of raising KeyError."""

    def __missing__(self, key: str) -> str:
        """Return the original placeholder spelling for an absent value."""
        return "{" + key + "}"


def t(key: str, lang: str = "en", **params: Any) -> str:
    """Render a localized template with safe fallback and formatting."""
    language = lang if lang in {"en", "hi"} else "en"
    template = load_catalog(language).get(key)
    if template is None and language != "en":
        logger.warning("Missing %s translation for %s; using English fallback", language, key)
        template = load_catalog("en").get(key)
    if template is None:
        return f"[missing: {key}]"
    try:
        return template.format_map(_SafeValues(params))
    except (ValueError, AttributeError):
        return template


def render(card: Card, lang: str) -> str:
    """Render a card, translating structured feature and product references."""
    from datetime import datetime
    from .timeutil import fmt_when

    params = dict(card.params)
    for key in ("nutrient", "field"):
        value = params.get(key)
        prefix = "nutrient" if key == "nutrient" else "feature"
        if isinstance(value, str) and f"{prefix}.{value}" in load_catalog(lang):
            params[key] = t(f"{prefix}.{value}", lang)
    name = params.get("name")
    if isinstance(name, str) and name.startswith("product."):
        params["name"] = t(name, lang)
    when = params.get("when")
    if isinstance(when, datetime):
        params["when"] = fmt_when(when, lang)
    return t(card.key, lang, **params)
