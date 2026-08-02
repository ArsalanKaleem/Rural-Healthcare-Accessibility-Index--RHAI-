#!/usr/bin/env python
"""
rhai_08_layer_audit.py — Diagnose the inputs before trusting the outputs.

Run from the project root:
    python scripts/rhai_08_layer_audit.py

Answers four questions:
  1. Is the village layer a fair sample of Sindh, or an OSM convenience sample?
     (villages per 1,000 km2 by district, flagged against the province median)
  2. Which districts were routed with which script version?
     (exact column-schema diff across data/district_results/*.csv)
  3. How many facilities does each district actually contain, and how many are
     name-tiered vs unclassified?
  4. Which districts contain zero villages (i.e. are legitimately empty, not failed)?

Writes data/rhai_layer_audit.csv. Read-only otherwise.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
GADM = ROOT / "data" / "gadm41_PAK_3.shp"
VILLAGES = ROOT / "data" / "sindh_villages.gpkg"
FACILITIES = ROOT / "data" / "facilities_tiered.gpkg"
RESULTS_DIR = ROOT / "data" / "district_results"
OUT = ROOT / "data" / "rhai_layer_audit.csv"

PROVINCE_COL, PROVINCE, DISTRICT_COL = "NAME_1", "Sindh", "NAME_3"
METRIC_CRS = 32642  # UTM 42N — same as SWAI, correct for Sindh

# A district whose village density is more than this factor away from the
# province median is flagged. 3x is generous; real settlement density does not
# vary 200-fold between irrigated districts.
DENSITY_FLAG_FACTOR = 3.0


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


# ----------------------------------------------------------------------------
def main() -> int:
    if not GADM.exists() or not VILLAGES.exists():
        print(f"[FATAL] Need {GADM.name} and {VILLAGES.name} in data/.")
        return 1

    gadm = gpd.read_file(GADM)
    sindh = gadm[gadm[PROVINCE_COL] == PROVINCE].copy()
    sindh = sindh[[DISTRICT_COL, "geometry"]].rename(columns={DISTRICT_COL: "district"})

    # Dissolve in case GADM splits a district into multiple polygons.
    sindh = sindh.dissolve(by="district", as_index=False)
    sindh_m = sindh.to_crs(METRIC_CRS)
    sindh["area_km2"] = sindh_m.geometry.area / 1e6

    # --- 1. villages per district ------------------------------------------
    vil = gpd.read_file(VILLAGES).to_crs(sindh.crs)
    if vil.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any():
        vil["geometry"] = vil.to_crs(METRIC_CRS).geometry.centroid.to_crs(vil.crs)

    joined = gpd.sjoin(vil[["geometry"]], sindh[["district", "geometry"]],
                       how="left", predicate="within")
    vcount = joined.groupby("district").size().rename("villages")
    unassigned = int(joined["district"].isna().sum())

    audit = sindh[["district", "area_km2"]].merge(
        vcount, left_on="district", right_index=True, how="left")
    audit["villages"] = audit["villages"].fillna(0).astype(int)
    audit["villages_per_1000km2"] = audit["villages"] / audit["area_km2"] * 1000

    dens = audit.loc[audit["villages"] > 0, "villages_per_1000km2"]
    med_dens = dens.median()
    audit["density_ratio"] = audit["villages_per_1000km2"] / med_dens
    audit["density_flag"] = np.where(
        audit["villages"] == 0, "EMPTY",
        np.where(audit["density_ratio"] > DENSITY_FLAG_FACTOR, "OVER-SAMPLED",
                 np.where(audit["density_ratio"] < 1 / DENSITY_FLAG_FACTOR,
                          "UNDER-SAMPLED", "ok")))

    # --- 2. facilities per district ----------------------------------------
    if FACILITIES.exists():
        fac = gpd.read_file(FACILITIES)
        if fac.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any():
            fac["geometry"] = fac.to_crs(METRIC_CRS).geometry.centroid.to_crs(fac.crs)
        fac = fac.to_crs(sindh.crs)
        fj = gpd.sjoin(fac, sindh[["district", "geometry"]], how="left", predicate="within")
        fcount = fj.groupby("district").size().rename("facilities")
        audit = audit.merge(fcount, left_on="district", right_index=True, how="left")
        audit["facilities"] = audit["facilities"].fillna(0).astype(int)

        tier_col = next((c for c in fj.columns if re.fullmatch(r"tier|level|category", c, re.I)),
                        None)
        if tier_col:
            named = fj[fj[tier_col].astype(str).str.lower() != "unclassified"]
            ncount = named.groupby("district").size().rename("facilities_named_tier")
            audit = audit.merge(ncount, left_on="district", right_index=True, how="left")
            audit["facilities_named_tier"] = audit["facilities_named_tier"].fillna(0).astype(int)
            audit["pct_unclassified"] = np.where(
                audit["facilities"] > 0,
                (1 - audit["facilities_named_tier"] / audit["facilities"]) * 100, np.nan)
        audit["facilities_per_1000km2"] = audit["facilities"] / audit["area_km2"] * 1000
    else:
        print(f"[WARN] {FACILITIES.name} not found — skipping facility density. "
              f"Regenerate it for all Sindh with rhai_03b before rerouting.")

    # --- 3. schema diff across district CSVs -------------------------------
    print("=" * 78)
    print("SCHEMA DIFF — which districts were routed by which script version")
    print("=" * 78)
    schemas: dict[frozenset, list[str]] = defaultdict(list)
    if RESULTS_DIR.exists():
        for p in sorted(RESULTS_DIR.glob("*.csv")):
            try:
                cols = frozenset(pd.read_csv(p, nrows=0).columns)
            except Exception as e:  # noqa: BLE001
                print(f"   [unreadable] {p.name}: {e}")
                continue
            schemas[cols].append(p.stem)

        ordered = sorted(schemas.items(), key=lambda kv: -len(kv[1]))
        base = ordered[0][0] if ordered else frozenset()
        for i, (cols, files) in enumerate(ordered):
            tag = "MAJORITY" if i == 0 else f"VARIANT {i}"
            print(f"\n{tag} — {len(files)} district(s), {len(cols)} columns")
            print(f"   districts: {', '.join(files)}")
            if i > 0:
                extra, missing = sorted(cols - base), sorted(base - cols)
                if extra:
                    print(f"   extra vs majority   : {extra}")
                if missing:
                    print(f"   missing vs majority : {missing}")
        if len(ordered) > 1:
            print(f"\n[BLOCKER] {len(ordered)} schema variants. These districts were not "
                  f"produced by the same method and cannot be pooled into one study. "
                  f"Delete district_results/ and rerun rhai_05 once against a single "
                  f"facilities_tiered.gpkg before computing any province-level statistic.")
    print()

    # --- 4. report ----------------------------------------------------------
    print("=" * 78)
    print("VILLAGE LAYER COVERAGE — is this a sample of Sindh, or of OSM?")
    print("=" * 78)
    print(f"Villages in layer        : {len(vil):,}")
    print(f"Unassigned to a district : {unassigned:,}"
          + ("   <-- outside Sindh polygons, check clipping" if unassigned else ""))
    print(f"Median district density  : {med_dens:.1f} villages / 1,000 km2")
    if len(dens):
        print(f"Range                    : {dens.min():.1f} to {dens.max():.1f} "
              f"({dens.max()/max(dens.min(), 1e-9):.0f}-fold)")
    print()

    show = ["district", "area_km2", "villages", "villages_per_1000km2",
            "density_ratio", "density_flag"]
    show += [c for c in ("facilities", "facilities_per_1000km2", "pct_unclassified")
             if c in audit.columns]
    pd.set_option("display.width", 140)
    print(audit[show].sort_values("villages_per_1000km2", ascending=False)
                     .round(1).to_string(index=False))
    print()

    n_over = int((audit["density_flag"] == "OVER-SAMPLED").sum())
    n_under = int((audit["density_flag"] == "UNDER-SAMPLED").sum())
    n_empty = int((audit["density_flag"] == "EMPTY").sum())
    print(f"OVER-SAMPLED  : {n_over}   UNDER-SAMPLED : {n_under}   EMPTY : {n_empty}")
    print()
    if n_empty:
        print("EMPTY districts are legitimately excluded (no village points), not failed "
              "routing runs. Make rhai_05 write an empty CSV with headers for these and "
              "state the exclusion in the paper.")
    if n_over or n_under:
        print("Any province-wide statistic (median travel time, % of villages over 60 min) "
              "computed by treating these villages as equally representative is a statement "
              "about OSM mapping density, not about Sindh. Population-weight every aggregate, "
              "and report this table as a limitation figure.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    audit.round(3).to_csv(OUT, index=False)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
