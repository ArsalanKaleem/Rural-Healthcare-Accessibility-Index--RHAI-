#!/usr/bin/env python
"""
rhai_12_merge_facilities.py — Build the Scenario B facility layer.

    Scenario A = facilities_tiered.gpkg          open data only (~2,725 facilities)
    Scenario B = Scenario A + pphi_geocoded.gpkg adds ~691 verified PPHI facilities

Deduplicates spatially so a facility present in both sources is not double-counted,
normalises district names between PPHI and GADM spellings, and writes the merged layer
for rerouting.

WHAT GOES IN
    Only pphi_geocoded.gpkg — the exact-containment layer from rhai_11 v4.
    pphi_geocoded_boundary.gpkg is NOT merged: those points carry up to 12 km of
    positional uncertainty, which is 20-30 minutes of rural travel time. Route them
    separately if you want a sensitivity bound, never silently mixed in.

DEDUPE DISTANCE
    250 m, wider than the 100 m used for point-to-point OSM comparison, because PPHI
    points are settlement centroids rather than building locations. A BHU mapped in
    OSM 200 m from its village centroid is the same facility.

USAGE
    python scripts/rhai_12_merge_facilities.py

OUTPUTS
    data/facilities_merged_final.gpkg   Scenario B layer — route against this
    data/facility_source_summary.csv    per-district counts by source
    data/district_crosswalk.csv         written if absent

THEN
    Copy rhai_05_route_by_district.py -> rhai_05b_route_scenarioB.py and change:
        facility input -> data/facilities_merged_final.gpkg
        output folder  -> data/district_results_B/
        stitched CSV   -> data/rhai_traveltimes_scenarioB.csv
    Run it, then rhai_13_compare_scenarios.py.
"""

from __future__ import annotations

import sys
import numpy as np
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

OPEN_FAC = DATA / "facilities_tiered.gpkg"
PPHI_FAC = DATA / "pphi_geocoded_reviewed.gpkg"
PPHI_BOUNDARY = DATA / "pphi_geocoded_boundary.gpkg"
PPHI_CSV = DATA / "pphi_facilities.csv"
GADM = DATA / "gadm41_PAK_3.shp"
BOUNDARY = DATA / "sindh_boundary.gpkg"

OUT_MERGED = DATA / "facilities_merged_final.gpkg"
OUT_SUMMARY = DATA / "facility_source_summary.csv"
CROSSWALK_CSV = DATA / "district_crosswalk.csv"

METRIC_CRS = 32642
DEDUPE_METRES = 250

CROSSWALK = {
    "Tharparkar": "Mithi",
    "Naushero Feroze": "Naushahro Firoz",
    "Shaheed Benazirabad": "Nawab Shah",
    "Jacobabad": "Jakobabad",
    "Tando Muhammad Khan": "Tando M. Khan",
    "Mirpurkhas": "Mirphurkhas",
    "Karachi West": "Karachi west",
    "Kamber": "Larkana",
    "Sujawal": "Thatta",
    "Keamari": "Karachi west",
}

# Districts geocoding below this rate are still likely under-counted in Scenario B.
UNDERCOUNT_WARN_RATE = 35.0


def to_points(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = g.to_crs(4326)
    poly = g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if poly.any():
        g.loc[poly, "geometry"] = (
            g.loc[poly].to_crs(METRIC_CRS).geometry.centroid.to_crs(4326))
    return g


def main() -> int:
    if not OPEN_FAC.exists():
        print(f"[FATAL] {OPEN_FAC.name} not found.")
        return 1
    if not PPHI_FAC.exists():
        print(f"[FATAL] {PPHI_FAC.name} not found. Run rhai_11 first.")
        return 1

    # --- crosswalk ----------------------------------------------------------
    cw = pd.DataFrame(sorted(CROSSWALK.items()), columns=["pphi_name", "gadm_name"])
    if GADM.exists():
        gadm = gpd.read_file(GADM)
        sindh_names = set(gadm.loc[gadm["NAME_1"] == "Sindh", "NAME_3"].dropna())
        cw["gadm_name_exists"] = cw["gadm_name"].isin(sindh_names)
        bad = cw[~cw["gadm_name_exists"]]
        if len(bad):
            print("[WARN] crosswalk targets missing from GADM NAME_3:")
            for _, r in bad.iterrows():
                print(f"   {r['pphi_name']} -> {r['gadm_name']}   FIX THIS")
            print(f"   available: {sorted(sindh_names)}\n")
    cw.to_csv(CROSSWALK_CSV, index=False)

    # --- load ---------------------------------------------------------------
    old = to_points(gpd.read_file(OPEN_FAC))
    new = to_points(gpd.read_file(PPHI_FAC))
    print(f"[INFO] open-data facilities        : {len(old):,}")
    print(f"[INFO] PPHI verified geocodes      : {len(new):,}")

    if PPHI_BOUNDARY.exists():
        nb = len(gpd.read_file(PPHI_BOUNDARY))
        print(f"[INFO] PPHI boundary-tolerance     : {nb:,}  (NOT merged — "
              f"up to 12 km error)")

    if "district" in new.columns:
        new["district_gadm"] = new["district"].replace(CROSSWALK)

    # --- dedupe -------------------------------------------------------------
    new = new.reset_index(drop=True)
    a = new.to_crs(METRIC_CRS)
    b = old.to_crs(METRIC_CRS)
    near = gpd.sjoin_nearest(a, b[["geometry"]], how="left",
                             max_distance=DEDUPE_METRES, distance_col="_d")
    near = near[~near.index.duplicated(keep="first")]
    dup_mask = near["_d"].notna().reindex(new.index, fill_value=False).values

    n_dup = int(dup_mask.sum())
    n_new = len(new) - n_dup
    print()
    print(f"[INFO] PPHI points within {DEDUPE_METRES} m of an existing facility: {n_dup:,}")
    print(f"[INFO] genuinely new facilities   : {n_new:,}")
    print(f"[INFO] Scenario B total           : {len(old) + n_new:,}  "
          f"(was {len(old):,}, +{100*n_new/max(len(old),1):.0f}%)")
    if len(new):
        print(f"[NOTE] only {100*n_dup/len(new):.1f}% of PPHI facilities overlap the open")
        print( "       data at all. The two sources are near-disjoint — a cleaner way to")
        print( "       state the coverage gap than any percentage of the total.")
    print()

    # --- merge --------------------------------------------------------------
    old_out = old.copy()
    old_out["source"] = "open_data"
    old_out["positional_uncertainty_km"] = 0.1

    new_out = new[~dup_mask].copy()
    new_out["source"] = "pphi_geocoded"
    if "positional_uncertainty_km" not in new_out.columns:
        new_out["positional_uncertainty_km"] = 2.0

    keep = ["geometry", "source", "positional_uncertainty_km"]
    for c in ("name", "tier", "hf_type", "hf_code", "district", "district_gadm",
              "score", "matched_place", "gaz_source", "landed_in"):
        if c in old_out.columns or c in new_out.columns:
            keep.append(c)

    merged = pd.concat(
        [old_out.reindex(columns=[c for c in keep if c in old_out.columns]),
         new_out.reindex(columns=[c for c in keep if c in new_out.columns])],
        ignore_index=True, sort=False)
    merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=4326)

    if BOUNDARY.exists():
        sindh = gpd.read_file(BOUNDARY).to_crs(4326)
        before = len(merged)
        merged = gpd.sjoin(merged, sindh[["geometry"]], how="inner",
                           predicate="within").drop(columns=["index_right"])
        merged = merged[~merged.index.duplicated(keep="first")]
        if len(merged) < before:
            print(f"[INFO] clipped to Sindh: {before:,} -> {len(merged):,}")

    merged = merged.reset_index(drop=True)
    merged.to_file(OUT_MERGED, driver="GPKG")
    print(f"Wrote {OUT_MERGED.name}: {len(merged):,} facilities")

    # --- per-district summary ----------------------------------------------
    if not GADM.exists():
        print("[WARN] no GADM — skipping district summary")
        return 0

    # NOTE: name the joined column gadm_district, not district. `merged` already
    # carries a `district` column from the PPHI rows, and a name collision makes
    # geopandas emit district_left / district_right, breaking the groupby.
    gadm = gpd.read_file(GADM)
    sindh_d = (gadm[gadm["NAME_1"] == "Sindh"][["NAME_3", "geometry"]]
               .rename(columns={"NAME_3": "gadm_district"})
               .dissolve(by="gadm_district", as_index=False).to_crs(4326))

    j = gpd.sjoin(merged, sindh_d, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]

    n_outside = int(j["gadm_district"].isna().sum())
    if n_outside:
        print(f"[INFO] {n_outside:,} facilities fell outside every district polygon "
              f"(boundary precision) — excluded from the table below")

    summ = (j.dropna(subset=["gadm_district"])
             .groupby(["gadm_district", "source"]).size().unstack(fill_value=0))
    for c in ("open_data", "pphi_geocoded"):
        if c not in summ.columns:
            summ[c] = 0
    summ["TOTAL"] = summ["open_data"] + summ["pphi_geocoded"]
    summ["multiplier"] = (summ["TOTAL"] /
                          summ["open_data"].replace(0, np.nan)).round(1)
    summ = summ.sort_values("pphi_geocoded", ascending=False)
    summ.to_csv(OUT_SUMMARY)

    print()
    print("=" * 74)
    print("FACILITIES PER DISTRICT — Scenario A vs B")
    print("=" * 74)
    print(summ.to_string())
    print()
    print(f"Wrote {OUT_SUMMARY.name}")
    print()
    print("`multiplier` is Scenario B total / Scenario A total. Districts with the")
    print("highest multipliers are where Scenario A travel times were most wrong, and")
    print("where the paper's comparison will be most striking.")

    # --- undercount warning -------------------------------------------------
    if PPHI_CSV.exists():
        try:
            pf = pd.read_csv(PPHI_CSV)
            tot = pf.groupby("district").size()
            got = gpd.read_file(PPHI_FAC).groupby("district").size()
            rate = (got.reindex(tot.index).fillna(0) / tot * 100).sort_values()
            low = rate[rate < UNDERCOUNT_WARN_RATE]
            if len(low):
                print()
                print("STILL LIKELY UNDER-COUNTED IN SCENARIO B")
                print("-" * 74)
                for d, v in low.items():
                    print(f"  {d:<24} only {v:.0f}% of PPHI facilities geocoded")
                print()
                print("  Their Scenario B travel times remain UPPER BOUNDS. Say so when")
                print("  discussing these districts — do not present them as corrected.")
        except Exception as e:  # noqa: BLE001
            print(f"[skip undercount check] {e}")

    print()
    print("NEXT")
    print("  1. Copy rhai_05_route_by_district.py -> rhai_05b_route_scenarioB.py")
    print("  2. Change three paths in the copy:")
    print("       facilities -> data/facilities_merged_final.gpkg")
    print("       output dir -> data/district_results_B/")
    print("       stitched   -> data/rhai_traveltimes_scenarioB.csv")
    print("  3. Run it. Hours of unattended compute — start it, then do the 175-row")
    print("     review and the QGIS validation while it runs.")
    print("  4. python scripts/rhai_13_compare_scenarios.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())