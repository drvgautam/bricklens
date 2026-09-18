"""Telemetry sources — the industry-integration seam.

`TelemetrySource` is the one Protocol a real BMS must satisfy to feed BrickLens.
Ship: CsvSource, ParquetSource, SyntheticSource, CsiroSource (public dataset), and a
documented BmsRestSource stub. Swapping sources is one line in config/bricklens.yaml.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pandas as pd

from .store import COLUMNS


class TelemetrySource(Protocol):
    def points(self) -> list[str]:
        """Brick point URIs this source can supply."""
        ...

    def readings(self, start=None, end=None) -> Iterator[pd.DataFrame]:
        """Yield normalised frames with columns ts, point_uri, value, unit, quality."""
        ...


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("unit", "quality"):
        if c not in df:
            df[c] = None if c == "unit" else "good"
    df["ts"] = pd.to_datetime(df["ts"])
    return df[COLUMNS]


class FrameSource:
    """Base for sources that already hold a long-format frame."""

    def __init__(self, df: pd.DataFrame):
        self.df = _normalise(df)

    def points(self):
        return sorted(self.df["point_uri"].unique())

    def readings(self, start=None, end=None):
        df = self.df
        if start is not None:
            df = df[df["ts"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["ts"] <= pd.Timestamp(end)]
        yield df


class CsvSource(FrameSource):
    """Long-format CSV: ts,point_uri,value[,unit,quality]."""

    def __init__(self, path: str | Path):
        super().__init__(pd.read_csv(path))


class ParquetSource(FrameSource):
    def __init__(self, path: str | Path):
        super().__init__(pd.read_parquet(path))


class SyntheticSource(FrameSource):
    """Four weeks of scripted telemetry for the demo building with injected faults."""

    def __init__(self, seed=42, start="2026-08-03", weeks=4, resolution_min=5, faults_path=None):
        from .synthetic import generate
        df, faults = generate(seed=seed, start=start, weeks=weeks, resolution_min=resolution_min)
        self.faults = faults
        if faults_path:
            Path(faults_path).parent.mkdir(parents=True, exist_ok=True)
            faults.to_csv(faults_path, index=False)
        super().__init__(df)


class CsiroSource(FrameSource):
    """CSIRO Newcastle AHU fault-detection dataset (CC BY-SA 4.0).

    https://github.com/csiro-energy-systems/ahu-fault-detection-dataset  — clone, then
    `git lfs pull` to fetch data/AHU9.parquet, data/AHU10.parquet, data/fault-experiments.parquet.
    Columns are wide (one per BMS tag); `mapping` binds tag names to Brick point URIs, e.g.
    {"SA Temp": "urn:bricklens:demo#AHU1.sat", "CHW Valve": "urn:bricklens:demo#AHU1.clg_cmd", ...}.
    Unmapped tags are ignored, so a partial mapping is fine for a first run.
    """

    def __init__(self, path: str | Path, ahu: int = 9, mapping: dict[str, str] | None = None):
        p = Path(path)
        wide = pd.read_parquet(p / f"AHU{ahu}.parquet")
        wide.index.name = "ts"
        mapping = mapping or {}
        cols = [c for c in wide.columns if c in mapping]
        if not cols:
            raise ValueError("CsiroSource: no columns matched the mapping; check tag names in the parquet")
        long = wide[cols].reset_index().melt(id_vars="ts", var_name="tag", value_name="value")
        long["point_uri"] = long["tag"].map(mapping)
        gt_path = p / "fault-experiments.parquet"
        self.faults = pd.read_parquet(gt_path) if gt_path.exists() else None
        super().__init__(long[["ts", "point_uri", "value"]])


class BmsRestSource:
    """Stub for a live BMS/historian REST feed. Documented, not implemented.

    A real implementation needs three things, all of which live outside the detector code:
    1. an auth'd HTTP client (token or mTLS) to the historian's trend endpoint
    2. a tag → Brick URI mapping file (see config/mapping.example.yaml)
    3. unit normalisation (°F→°C, cfm→m³/h) done here, never in a detector

    readings() should page by time window and yield frames in the store schema.
    """

    def __init__(self, base_url: str, mapping: dict[str, str], token: str | None = None):
        self.base_url, self.mapping, self.token = base_url, mapping, token

    def points(self):
        return sorted(set(self.mapping.values()))

    def readings(self, start=None, end=None):
        raise NotImplementedError("BmsRestSource is a documented stub; implement against your historian's trend API")


def make_source(cfg) -> TelemetrySource:
    s = cfg.telemetry.source
    kind = s["kind"]
    if kind == "synthetic":
        return SyntheticSource(seed=s.get("seed", 42), start=s.get("start", "2026-08-03"), weeks=s.get("weeks", 4),
                               resolution_min=s.get("resolution_min", 5),
                               faults_path=cfg.resolve(s["faults"]) if s.get("faults") else None)
    if kind == "csv":
        return CsvSource(cfg.resolve(s["path"]))
    if kind == "parquet":
        return ParquetSource(cfg.resolve(s["path"]))
    if kind == "csiro":
        return CsiroSource(cfg.resolve(s["path"]), ahu=s.get("ahu", 9), mapping=s.get("mapping"))
    if kind == "bms_rest":
        return BmsRestSource(s["base_url"], s.get("mapping", {}), s.get("token"))
    raise ValueError(f"unknown source kind {kind}")
