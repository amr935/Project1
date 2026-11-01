"""Tests for project configuration loading and cross-file consistency."""

from pathlib import Path
import shutil

import pytest

from ks.config import ConfigError, load_config


def test_dose_rows_match_crop_flags(cfg) -> None:
    """Every crop marked for fertilizer has one dose row, and vice versa."""
    flagged = {crop.crop_id for crop in cfg.crops if crop.has_dose}
    configured = {dose.crop_id for dose in cfg.doses}

    assert flagged == configured


def test_districts_have_unique_ids_and_in_region_coordinates(cfg) -> None:
    """District IDs are unique and coordinates stay in the supplied region."""
    district_ids = [district.district_id for district in cfg.districts]

    assert len(district_ids) == len(set(district_ids))
    assert all(21.9 <= district.lat <= 27.6 for district in cfg.districts)
    assert all(83.3 <= district.lon <= 88.3 for district in cfg.districts)


def test_allowed_crops_exist_in_crop_table(cfg) -> None:
    """Every model-allowed crop is present in the crop catalog."""
    catalog_ids = {crop.crop_id for crop in cfg.crops}

    assert set(cfg.crop.allowed) <= catalog_ids


def test_loader_reports_missing_required_setting(tmp_path: Path) -> None:
    """A missing TOML section fails with a readable configuration error."""
    source = Path(__file__).resolve().parents[1] / "config"
    target = tmp_path / "config"
    shutil.copytree(source, target)
    settings = target / "settings.toml"
    settings.write_text('[app]\nname = "KrishiSahayak"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="features"):
        load_config(target)
