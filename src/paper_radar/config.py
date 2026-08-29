from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RadarConfig:
    root: Path
    common: dict[str, Any]
    venues: dict[str, Any]
    seeds: dict[str, Any]
    tuning: dict[str, Any]
    categories: dict[str, dict[str, Any]]

    def category(self, name: str) -> dict[str, Any]:
        try:
            return self.categories[name]
        except KeyError as exc:
            raise ConfigError(f"Unknown category: {name}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"Config root must be a mapping: {path}")
    return value


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "config" / "common.yaml").exists():
            return candidate
    raise ConfigError("Could not find config/common.yaml from current directory")


def load_config(root: Path | None = None) -> RadarConfig:
    root = (root or find_project_root()).resolve()
    config_dir = root / "config"
    common = _read_yaml(config_dir / "common.yaml")
    search = common.get("search", {})
    for mode in ("daily", "more"):
        values = search.get(mode, {})
        if int(values.get("lookback_days", 0)) <= 0:
            raise ConfigError(f"config/common: {mode}.lookback_days must be positive")
        if int(values.get("source_limit_multiplier", 0)) <= 0:
            raise ConfigError(f"config/common: {mode}.source_limit_multiplier must be positive")
    if int(search["more"].get("count", 0)) <= 0:
        raise ConfigError("config/common: more.count must be positive")
    venues = _read_yaml(config_dir / "venues.yaml")
    seeds = _read_yaml(config_dir / "seeds.yaml")
    tuning = _read_yaml(config_dir / "tuning.yaml")
    categories = {
        "bioinfo": _read_yaml(config_dir / "bioinfo.yaml"),
        "ml": _read_yaml(config_dir / "ml_algorithms.yaml"),
        "frontier": _read_yaml(config_dir / "ai_frontier.yaml"),
    }
    for name, cfg in categories.items():
        for required in ("families", "weights", "thresholds"):
            if required not in cfg:
                raise ConfigError(f"config/{name}: missing {required}")
        thresholds = cfg["thresholds"]
        if thresholds["must_read"] <= thresholds["strong"]:
            raise ConfigError(f"config/{name}: must_read must exceed strong")
        if thresholds["strong"] <= thresholds["more_min_score"]:
            raise ConfigError(f"config/{name}: strong must exceed more_min_score")
    return RadarConfig(root, common, venues, seeds, tuning, categories)
