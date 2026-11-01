"""Shared fixtures for KrishiSahayak tests."""

from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from ks.config import AppConfig, load_config


@pytest.fixture(scope="session")
def cfg() -> AppConfig:
    """Return the validated project configuration."""
    return load_config(Path(__file__).resolve().parents[1] / "config")


def make_hourly(start: datetime, hours: int, rh, t, rain=0.0, wind=5.0, prob=None) -> pd.DataFrame:
    """Build a synthetic hourly frame from scalar or per-hour values."""
    def expand(value, fallback: float) -> list[float]:
        """Expand a scalar or validate a list against the hour count."""
        if value is None:
            return [fallback] * hours
        if isinstance(value, (int, float)):
            return [float(value)] * hours
        values = [float(item) if item is not None else np.nan for item in value]
        if len(values) != hours:
            raise ValueError("hourly value count must match hours")
        return values

    times = pd.date_range(start=start, periods=hours, freq="h").tz_localize(None)
    return pd.DataFrame({
        "time": times,
        "relative_humidity_2m": expand(rh, np.nan),
        "temperature_2m": expand(t, np.nan),
        "precipitation": expand(rain, 0.0),
        "wind_speed_10m": expand(wind, 5.0),
        "precipitation_probability": expand(prob, np.nan),
    })
