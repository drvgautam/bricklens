"""Convert the CSIRO fault-experiments table to BrickLens' faults.csv schema.

Usage: python scripts/csiro_labels.py ../ahu-fault-detection-dataset/data/fault-experiments.parquet data/csiro_faults.csv
Map CSIRO fault descriptions onto BrickLens alert types; unmapped rows are dropped with a note.
"""
import sys

import pandas as pd

NS = "urn:bricklens:demo#"
TYPE_MAP = {  # substring of the CSIRO fault description → (alert type, target uri)
    "hot water valve": ("coil_fighting", NS + "AHU1"),
    "chilled water valve": ("coil_fighting", NS + "AHU1"),
    "zone air temperature sensor": ("temp_band", NS + "Z1"),
    "outside air damper": ("pattern_deviation", NS + "AHU1"),
    "return air damper": ("pattern_deviation", NS + "AHU1"),
    "fan belt": ("pattern_deviation", NS + "AHU1"),
    "supply-air duct": ("pattern_deviation", NS + "AHU1"),
}

src, dst = sys.argv[1], sys.argv[2]
gt = pd.read_parquet(src)
rows, dropped = [], 0
for r in gt.itertuples():
    desc = " ".join(str(v).lower() for v in r._asdict().values())
    hit = next((v for k, v in TYPE_MAP.items() if k in desc), None)
    if not hit:
        dropped += 1
        continue
    start = getattr(r, "_5", None) or getattr(r, "start", None) or r[-2]
    end = getattr(r, "_6", None) or getattr(r, "end", None) or r[-1]
    rows.append({"fault_type": hit[0], "target_uri": hit[1], "start": start, "end": end, "note": desc[:80]})
pd.DataFrame(rows).to_csv(dst, index=False)
print(f"wrote {len(rows)} labelled faults to {dst}; dropped {dropped} unmapped rows")
