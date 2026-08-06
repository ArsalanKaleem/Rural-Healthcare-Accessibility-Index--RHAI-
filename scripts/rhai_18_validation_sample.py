#!/usr/bin/env python
"""
rhai_18_validation_sample.py — Draw the satellite validation sample.

WHY
    616 facility coordinates were produced by matching names against a gazetteer.
    Nobody has looked at any of them. This draws a stratified random sample so you can
    check, on satellite imagery, whether a plausible facility structure is actually
    there.

    This validates TIER 2 (physically present). It cannot establish that a building is
    a health facility, is staffed, or is open — that is tier 3, and outside the reach
    of open data.

USAGE
    python scripts/rhai_18_validation_sample.py
    python scripts/rhai_18_validation_sample.py --n 50 --seed 42

OUTPUT
    data/validation_sample.gpkg   open this in QGIS over satellite imagery

THEN
    1. QGIS: Browser > XYZ Tiles > right-click > New Connection
         Name: Satellite
         URL:  https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}
    2. Add validation_sample.gpkg above it. Style: transparent fill, magenta outline,
       width 0.6, size 4 — a filled marker hides the thing you are trying to see.
    3. Open the attribute table, click the pencil to edit.
    4. Select row 1, press Ctrl+J to zoom, judge, type into `verdict`, next row.
    5. Save edits, then run rhai_19_validation_report.py.

SCORING
    yes      a walled compound or standalone building consistent with a small rural
             facility, within ~500 m
    no       bare ground, cropland, or only undifferentiated housing
    unclear  imagery too coarse, cloud, shadow, or genuinely cannot tell

    `unclear` is a legitimate answer. Do not hunt for a reason to say yes — the number
    is only worth reporting if it could have come out badly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SRC = DATA / "pphi_geocoded_reviewed.gpkg"      # falls back to pphi_geocoded.gpkg
FALLBACK = DATA / "pphi_geocoded.gpkg"
OUT = DATA / "validation_sample.gpkg"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="sample size (default 50)")
    ap.add_argument("--seed", type=int, default=42, help="random seed — report this")
    args = ap.parse_args()

    src = SRC if SRC.exists() else FALLBACK
    if not src.exists():
        print(f"[FATAL] neither {SRC.name} nor {FALLBACK.name} found. Run rhai_11 first.")
        return 1
    print(f"[INFO] sampling from {src.name}")

    g = gpd.read_file(src).to_crs(4326)
    print(f"[INFO] {len(g):,} facilities available")

    if "district" not in g.columns:
        print("[WARN] no district column — drawing a simple random sample")
        s = g.sample(min(args.n, len(g)), random_state=args.seed)
    else:
        # Stratify by district so the estimate is not dominated by the two or three
        # districts holding most of the geocodes.
        counts = g.groupby("district").size()
        alloc = np.maximum(1, np.round(counts / counts.sum() * args.n)).astype(int)
        parts = []
        for d, k in alloc.items():
            sub = g[g["district"] == d]
            parts.append(sub.sample(min(int(k), len(sub)), random_state=args.seed))
        s = pd.concat(parts)
        # Proportional allocation with a minimum of 1 overshoots; trim at random.
        if len(s) > args.n:
            s = s.sample(args.n, random_state=args.seed)
        s = gpd.GeoDataFrame(s, crs=g.crs)

    s = s.reset_index(drop=True)
    s["sample_id"] = range(1, len(s) + 1)
    s["verdict"] = ""            # yes / no / unclear  <- you fill this in QGIS
    s["structure"] = ""          # compound / building / none
    s["notes"] = ""

    keep = ["sample_id", "verdict", "structure", "notes", "district", "name",
            "settlement", "matched_place", "score", "hf_type", "geometry"]
    s = s[[c for c in keep if c in s.columns]]

    s.to_file(OUT, driver="GPKG")

    print()
    print("=" * 70)
    print(f"Wrote {OUT.name}: {len(s)} points across {s['district'].nunique()} districts")
    print("=" * 70)
    print(f"seed = {args.seed}  (report this in the methods section)")
    print()
    print("Per district:")
    print(s.groupby("district").size().sort_values(ascending=False).to_string())
    print()
    print("NEXT — in QGIS")
    print("  1. Browser > XYZ Tiles > right-click > New Connection")
    print("     Name: Satellite")
    print("     URL:  https://server.arcgisonline.com/ArcGIS/rest/services/"
          "World_Imagery/MapServer/tile/{z}/{y}/{x}")
    print("  2. Add validation_sample.gpkg ABOVE the imagery layer.")
    print("  3. Style: transparent fill, magenta stroke, width 0.6, size 4.")
    print("  4. Attribute table > pencil icon > select row > Ctrl+J > judge > type")
    print("     yes / no / unclear into `verdict` > next row.")
    print("  5. Save edits, then: python scripts/rhai_19_validation_report.py")
    print()
    print("  Roughly 60-90 seconds per point. `unclear` is a legitimate answer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
