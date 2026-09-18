"""Telemetry store: readings keyed by Brick point URI in DuckDB (Parquet-backed).

Schema (one row per reading): ts TIMESTAMP, point_uri VARCHAR, value DOUBLE, unit VARCHAR, quality VARCHAR
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

COLUMNS = ["ts", "point_uri", "value", "unit", "quality"]


class TelemetryStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS readings (ts TIMESTAMP, point_uri VARCHAR, value DOUBLE, unit VARCHAR, quality VARCHAR)"
        )

    def clear(self):
        self.con.execute("DELETE FROM readings")

    def append(self, df: pd.DataFrame) -> int:
        df = df[COLUMNS].copy()
        df["ts"] = pd.to_datetime(df["ts"])
        self.con.register("_new", df)
        self.con.execute("INSERT INTO readings SELECT * FROM _new")
        self.con.unregister("_new")
        return len(df)

    def series(self, point_uri: str, start=None, end=None) -> pd.Series:
        q = "SELECT ts, value FROM readings WHERE point_uri = ?"
        params: list = [point_uri]
        if start is not None:
            q += " AND ts >= ?"; params.append(pd.Timestamp(start))
        if end is not None:
            q += " AND ts <= ?"; params.append(pd.Timestamp(end))
        df = self.con.execute(q + " ORDER BY ts", params).df()
        s = pd.Series(df["value"].values, index=pd.DatetimeIndex(df["ts"]), name=point_uri)
        return s[~s.index.duplicated(keep="last")]

    def frame(self, point_uris: list[str], start=None, end=None) -> pd.DataFrame:
        cols = {u: self.series(u, start, end) for u in point_uris}
        return pd.DataFrame(cols).sort_index()

    def points(self) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT DISTINCT point_uri FROM readings").fetchall()]

    def bounds(self):
        r = self.con.execute("SELECT min(ts), max(ts), count(*) FROM readings").fetchone()
        return {"start": r[0], "end": r[1], "rows": r[2]}

    def status(self, graph_point_uris: list[str]) -> dict:
        have = set(self.points())
        want = set(graph_point_uris)
        b = self.bounds()
        return {
            "points_in_model": len(want),
            "series_bound": len(have & want),
            "unbound_series": sorted(have - want),      # telemetry with no Brick point
            "points_without_data": sorted(want - have),
            "rows": b["rows"], "start": b["start"], "end": b["end"],
        }
