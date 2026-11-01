"""Fetch and cache one forecast for each configured district."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ks.config import load_config
from ks.timeutil import now_ist
from ks.weather import load_bundle


def main() -> int:
    """Prefetch weather and print one status line per district."""
    cfg = load_config(ROOT / "config")
    fetched_at = now_ist()
    cache_dir = ROOT / "data" / "cache"
    failed = False
    for district in cfg.districts:
        bundle = load_bundle(district, cfg, cache_dir, fetched_at)
        if bundle is None:
            print(f"{district.district_id}: FAILED")
            failed = True
        else:
            print(f"{district.district_id}: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
