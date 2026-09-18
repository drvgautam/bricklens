"""Configuration loading. One YAML file drives model paths, graph backend, sources, detectors."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path("config/bricklens.yaml")


class Config(dict):
    """A dict with attribute-style access and a `path` for resolving relative files."""

    def __init__(self, data: dict[str, Any], path: Path | None = None):
        super().__init__(data)
        self.path = path or DEFAULT_CONFIG
        self.root = self.path.resolve().parent.parent if self.path.parent.name == "config" else Path.cwd()

    def __getattr__(self, item: str) -> Any:
        try:
            v = self[item]
        except KeyError as e:
            raise AttributeError(item) from e
        return Config(v, self.path) if isinstance(v, dict) else v

    def resolve(self, rel: str | Path) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.root / p)


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG
    with open(p) as f:
        return Config(yaml.safe_load(f), p)


def save_config(cfg: Config) -> None:
    with open(cfg.path, "w") as f:
        yaml.safe_dump(dict(cfg), f, sort_keys=False)
