"""Mocked tests for Open-Meteo loading and the weather cache."""

from datetime import datetime, timedelta
import json
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

from ks.weather import load_bundle, load_cached_bundle


IST = ZoneInfo("Asia/Kolkata")


def _payload() -> dict:
    """Return the minimum complete forecast payload."""
    return {
        "hourly": {
            "time": ["2026-11-01T09:00", "2026-11-01T10:00"],
            "temperature_2m": [20, 21],
            "relative_humidity_2m": [90, 88],
            "precipitation": [0, 0],
            "precipitation_probability": [None, 10],
            "wind_speed_10m": [4, 5],
        },
        "daily": {
            "time": ["2026-11-01"],
            "temperature_2m_max": [22],
            "temperature_2m_min": [16],
            "precipitation_sum": [0],
        },
    }


def _response(payload: dict, status: int = 200) -> Mock:
    """Build a minimal requests response mock."""
    result = Mock()
    result.status_code = status
    result.json.return_value = payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return result


def test_success_writes_cache_and_returns_live(cfg, tmp_path) -> None:
    """A valid forecast is parsed and stored with an IST timestamp."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=IST)
    with patch("ks.weather.requests.get", return_value=_response(_payload())) as get:
        bundle = load_bundle(cfg.districts[0], cfg, tmp_path, now)

    assert bundle is not None
    assert bundle.source == "live"
    assert bundle.hourly["time"].iloc[0].tzinfo is None
    assert bundle.hourly["precipitation_probability"].iloc[0] != bundle.hourly["precipitation_probability"].iloc[0]
    assert get.call_args.kwargs["timeout"] == cfg.weather.timeout_seconds
    cache = json.loads((tmp_path / f"{cfg.districts[0].district_id}.json").read_text(encoding="utf-8"))
    assert cache["fetched_at"].endswith("+05:30")
    assert cache["payload"] == _payload()


def test_timeout_retries_then_uses_recent_cache(cfg, tmp_path) -> None:
    """Repeated timeouts fall back to a cache entry two hours old."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=IST)
    cache_path = tmp_path / f"{cfg.districts[0].district_id}.json"
    cache_path.write_text(json.dumps({"fetched_at": (now - timedelta(hours=2)).isoformat(), "payload": _payload()}), encoding="utf-8")
    failures = [requests.Timeout(), requests.Timeout(), requests.Timeout()]
    with patch("ks.weather.requests.get", side_effect=failures) as get, patch("ks.weather.time.sleep") as sleep:
        bundle = load_bundle(cfg.districts[0], cfg, tmp_path, now)

    assert bundle is not None and bundle.source == "cache"
    assert get.call_count == cfg.weather.retries + 1
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2]


def test_old_cache_is_marked_stale(cfg, tmp_path) -> None:
    """A 100-hour-old cache remains usable but is identified as stale."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=IST)
    path = tmp_path / f"{cfg.districts[0].district_id}.json"
    path.write_text(json.dumps({"fetched_at": (now - timedelta(hours=100)).isoformat(), "payload": _payload()}), encoding="utf-8")
    with patch("ks.weather.requests.get", side_effect=requests.Timeout()), patch("ks.weather.time.sleep"):
        bundle = load_bundle(cfg.districts[0], cfg, tmp_path, now)

    assert bundle is not None and bundle.source == "stale_cache"


def test_failure_without_cache_returns_none(cfg, tmp_path) -> None:
    """A total fetch failure with no saved file disables only weather advice."""
    with patch("ks.weather.requests.get", side_effect=requests.ConnectionError()), patch("ks.weather.time.sleep"):
        assert load_bundle(cfg.districts[0], cfg, tmp_path, datetime.now(IST)) is None


def test_corrupt_cache_returns_none_without_raising(cfg, tmp_path) -> None:
    """Malformed cache JSON is treated as unavailable data."""
    path = tmp_path / f"{cfg.districts[0].district_id}.json"
    path.write_text("{broken", encoding="utf-8")
    with patch("ks.weather.requests.get", side_effect=requests.Timeout()), patch("ks.weather.time.sleep"):
        assert load_bundle(cfg.districts[0], cfg, tmp_path, datetime.now(IST)) is None


def test_load_cached_bundle_does_not_make_a_network_request(cfg, tmp_path) -> None:
    """The offline-first page loader reads the requested district snapshot directly."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=IST)
    record = cfg.districts[0]
    (tmp_path / f"{record.district_id}.json").write_text(
        json.dumps({"fetched_at": now.isoformat(), "payload": _payload()}), encoding="utf-8"
    )
    with patch("ks.weather.requests.get") as get:
        bundle = load_cached_bundle(record.district_id, cfg, tmp_path, now)

    assert bundle is not None
    assert bundle.source == "cache"
    get.assert_not_called()


def test_payload_missing_hourly_is_a_failure(cfg, tmp_path) -> None:
    """A nominal HTTP response without hourly data is rejected."""
    with patch("ks.weather.requests.get", return_value=_response({"daily": {}})):
        assert load_bundle(cfg.districts[0], cfg, tmp_path, datetime.now(IST)) is None
