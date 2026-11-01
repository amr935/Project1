"""India-time helpers that do not depend on the host locale or timezone."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .i18n import t

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Return the current timezone-aware time in India."""
    return datetime.now(IST)


def now_local_naive() -> datetime:
    """Return current India time without timezone, floored to the hour."""
    return now_ist().replace(tzinfo=None, minute=0, second=0, microsecond=0)


def fmt_when(dt: datetime, lang: str) -> str:
    """Format a date and time using weekday names from the language catalog."""
    local = dt.astimezone(IST) if dt.tzinfo is not None else dt
    weekdays = t("weekdays", lang).split("|")
    if len(weekdays) != 7:
        weekdays = t("weekdays", "en").split("|")
    weekday = weekdays[local.weekday()]
    return f"{weekday} {local.day}/{local.month}, {local:%H:%M}"
