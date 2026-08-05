#!/usr/bin/env python
"""
rhai_15_sanity_check.py — Verify the pipeline is producing what we think it is.

Read-only. Runs every check that has caught a real bug in this project, plus the
standard integrity checks. Prints PASS / WARN / FAIL per check and a summary.

    python scripts/rhai_15_sanity_check.py

Exit code 0 if no FAILs, 1 otherwise — so it can gate the reroute.

CHECKS INCLUDED, AND WHY
    Every FAIL-level check below corresponds to a bug that actually occurred here and
    produced plausible-looking wrong numbers. They are cheap to run and worth running
    after any change to the pipeline.

      1. .gitignore holds patterns, not the PowerShell script that generates it
      2. data/ is genuinely ignored by git
      3. Geocoded facilities fall inside their stated district
      4. Boundary-tolerance layer has NOT been merged into the primary layer
      5. Positional uncertainty is not understated
      6. Facility layers are in EPSG:4326 with plausible Sindh bounds
      7. Village ids are unique and join to population
      8. Travel times are plausible and complete
      9. District crosswalk covers every PPHI district
     10. Scenario B has more facilities than A, everywhere
     11. Scenario B travel times are <= Scenario A, everywhere (if B exists)
     12. No facility is duplicated across sources within the dedupe distance
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SINDH_BOUNDS = (66.0, 23.0, 72.0, 29.0)   # lon_min, lat_min, lon_max, lat_max
DEDUPE_METRES = 250
METRIC_CRS = 32642

results: list[tuple[str, str, str]] = []   # (level, name, detail)


def rec(level: str, name: str, detail: str = "") -> None:
    results.append((level, name, detail))
    tag = {"PASS": "  PASS", "WARN": "  WARN", "FAIL": "  FAIL", "SKIP": "  skip"}[level]
    print(f"{tag}  {name}")
    if detail:
        for line in detail.splitlines():
            print(f"          {line}")


def gdf(path: Path):
    import geopandas as gpd
    return gpd.read_file(path)


# ---------------------------------------------------------------------------
def check_gitignore() -> None:
    p = ROOT / ".gitignore"
    if not p.exists():
        rec("WARN", ".gitignore exists", "not found")
        return
    txt = p.read_text(encoding="utf-8", errors="ignore")
    # The real bug: the PowerShell generator script was saved AS the file.
    if any(tok in txt for tok in ("$rules", "WriteAllLines", "New-Object", '","')):
        rec("FAIL", ".gitignore holds patterns, not code",
            "File contains PowerShell syntax. It is the generator script, not the\n"
            "ignore list. Rewrite it with plain patterns, one per line.")
        return
    if "data/" not in txt:
        rec("WARN", ".gitignore holds patterns, not code", "no data/ rule found")
        return
    rec("PASS", ".gitignore holds patterns, not code")


def check_git_ignoring_data() -> None:
    try:
        out = subprocess.run(["git", "check-ignore", "-v", "data/rhai_traveltimes.csv"],
                             cwd=ROOT, capture_output=True, text=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        rec("SKIP", "git is ignoring data/", f"{type(e).__name__}: {e}")
        return
    if out.stdout.strip():
        rec("PASS", "git is ignoring data/", out.stdout.strip())
    else:
        tracked = subprocess.run(["git", "ls-files", "data/"], cwd=ROOT,
                                 capture_output=True, text=True)
        n = len([l for l in tracked.stdout.splitlines() if l.strip()])
        rec("FAIL", "git is ignoring data/",
            f"check-ignore returned nothing; {n} files tracked under data/.\n"
            f"Either the rule is not matching, or files were committed before it\n"
            f"existed (git ignores rules for already-tracked files).")


def check_geocode_containment() -> None:
    f = DATA / "pphi_geocoded.gpkg"
    if not f.exists():
        rec("SKIP", "geocoded facilities are in the right district", "no gpkg")
        return
    g = gdf(f)
    if "district_exact" not in g.columns:
        rec("WARN", "geocoded facilities are in the right district",
            "no district_exact column — rerun rhai_11 v4")
        return
    vals = g["district_exact"]
    bad = int((~vals.astype(bool)).sum())
    if bad == 0:
        rec("PASS", "geocoded facilities are in the right district",
            f"all {len(g):,} verified")
    else:
        rec("FAIL", "geocoded facilities are in the right district",
            f"{bad:,} of {len(g):,} have district_exact=False.\n"
            f"The primary layer must contain only exact-containment matches.")


def check_boundary_not_merged() -> None:
    prim, bnd = DATA / "pphi_geocoded.gpkg", DATA / "pphi_geocoded_boundary.gpkg"
    if not (prim.exists() and bnd.exists()):
        rec("SKIP", "boundary-tolerance layer kept separate", "one or both missing")
        return
    p, b = gdf(prim), gdf(bnd)
    if len(p) >= len(b):
        rec("WARN", "boundary-tolerance layer kept separate",
            f"primary ({len(p):,}) >= boundary ({len(b):,}). Expected primary to be\n"
            f"the smaller, stricter set. Check which layer is which.")
    else:
        rec("PASS", "boundary-tolerance layer kept separate",
            f"primary {len(p):,}, boundary {len(b):,}")


def check_uncertainty_honest() -> None:
    f = DATA / "facilities_merged_final.gpkg"
    if not f.exists():
        rec("SKIP", "positional uncertainty is not understated", "no merged layer")
        return
    g = gdf(f)
    if "positional_uncertainty_km" not in g.columns:
        rec("WARN", "positional uncertainty is not understated", "column absent")
        return
    u = pd.to_numeric(g["positional_uncertainty_km"], errors="coerce")
    if (u > 5).any():
        n = int((u > 5).sum())
        rec("FAIL", "positional uncertainty is not understated",
            f"{n:,} facilities carry >5 km uncertainty in the routing layer.\n"
            f"12 km is 20-30 min of rural travel — these should not be merged.")
    else:
        rec("PASS", "positional uncertainty is not understated",
            f"max {u.max():.1f} km")


def check_crs_and_bounds() -> None:
    for name in ("facilities_tiered.gpkg", "pphi_geocoded.gpkg",
                 "facilities_merged_final.gpkg", "sindh_villages.gpkg"):
        f = DATA / name
        if not f.exists():
            continue
        g = gdf(f)
        epsg = g.crs.to_epsg() if g.crs else None
        b = g.total_bounds
        inside = (b[0] >= SINDH_BOUNDS[0] and b[1] >= SINDH_BOUNDS[1]
                  and b[2] <= SINDH_BOUNDS[2] and b[3] <= SINDH_BOUNDS[3])
        detail = (f"EPSG:{epsg}  bounds {b[0]:.2f},{b[1]:.2f},{b[2]:.2f},{b[3]:.2f}")
        if epsg != 4326:
            rec("FAIL", f"{name} CRS and bounds", detail + "  <- expected EPSG:4326")
        elif not inside:
            rec("WARN", f"{name} CRS and bounds",
                detail + "  <- extends outside Sindh")
        else:
            rec("PASS", f"{name} CRS and bounds", detail)


def check_villages_and_population() -> None:
    tt = DATA / "rhai_traveltimes.csv"
    if not tt.exists():
        rec("SKIP", "village ids unique and join to population", "no traveltimes")
        return
    t = pd.read_csv(tt)
    if "village_id" not in t.columns:
        rec("FAIL", "village ids unique and join to population",
            "no village_id column in rhai_traveltimes.csv")
        return
    dup = int(t["village_id"].duplicated().sum())
    if dup:
        rec("FAIL", "village ids unique", f"{dup:,} duplicate village_id values")
    else:
        rec("PASS", "village ids unique", f"{len(t):,} villages")

    pop = DATA / "village_population.csv"
    if not pop.exists():
        rec("WARN", "population data joins",
            "village_population.csv not present — all population-weighted metrics\n"
            "will be NaN. Copy it from the SWAI project.")
        return
    p = pd.read_csv(pop)
    if "village_id" not in p.columns:
        rec("FAIL", "population data joins",
            f"no village_id in village_population.csv. Columns: {list(p.columns)}")
        return
    matched = t["village_id"].isin(p["village_id"]).sum()
    frac = matched / max(len(t), 1)
    lvl = "PASS" if frac >= 0.95 else ("WARN" if frac >= 0.8 else "FAIL")
    rec(lvl, "population data joins",
        f"{matched:,}/{len(t):,} villages matched ({frac:.1%})")


def check_traveltimes(path: Path, label: str) -> None:
    if not path.exists():
        rec("SKIP", f"{label} travel times plausible", "file not present")
        return
    t = pd.read_csv(path)
    col = "min_any" if "min_any" in t.columns else None
    if col is None:
        rec("FAIL", f"{label} travel times plausible", "no min_any column")
        return
    s = pd.to_numeric(t[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    n_null = int(s.isna().sum())
    n_neg = int((s < 0).sum())
    n_wild = int((s > 600).sum())
    msg = (f"n={len(s):,}  median {s.median():.1f} min  max {s.max():.1f} min\n"
           f"null {n_null}  negative {n_neg}  over 600 min {n_wild}")
    if n_neg:
        rec("FAIL", f"{label} travel times plausible", msg)
    elif n_wild or n_null > 0.02 * len(s):
        rec("WARN", f"{label} travel times plausible", msg)
    else:
        rec("PASS", f"{label} travel times plausible", msg)


def check_crosswalk() -> None:
    pf, cw = DATA / "pphi_facilities.csv", DATA / "district_crosswalk.csv"
    gadm = DATA / "gadm41_PAK_3.shp"
    if not (pf.exists() and gadm.exists()):
        rec("SKIP", "district crosswalk complete", "inputs missing")
        return
    p = pd.read_csv(pf)
    g = gdf(gadm)
    names = set(g.loc[g["NAME_1"] == "Sindh", "NAME_3"].dropna())
    mapping = {}
    if cw.exists():
        c = pd.read_csv(cw)
        mapping = dict(zip(c["pphi_name"], c["gadm_name"]))
    mapped = p["district"].replace(mapping)
    missing = sorted(set(mapped) - names)
    if missing:
        n = int(mapped.isin(missing).sum())
        rec("FAIL", "district crosswalk complete",
            f"{len(missing)} PPHI districts do not map to GADM: {missing}\n"
            f"{n} facilities affected — they will be dropped or mis-assigned.")
    else:
        rec("PASS", "district crosswalk complete",
            f"all {p['district'].nunique()} PPHI districts map to GADM")


def check_scenario_b_facilities() -> None:
    a, m = DATA / "facilities_tiered.gpkg", DATA / "facilities_merged_final.gpkg"
    if not (a.exists() and m.exists()):
        rec("SKIP", "Scenario B has more facilities than A", "inputs missing")
        return
    na, nm = len(gdf(a)), len(gdf(m))
    if nm > na:
        rec("PASS", "Scenario B has more facilities than A",
            f"{na:,} -> {nm:,}  (+{100*(nm-na)/na:.0f}%)")
    else:
        rec("FAIL", "Scenario B has more facilities than A", f"{na:,} -> {nm:,}")


def check_scenario_b_times() -> None:
    a, b = DATA / "rhai_traveltimes.csv", DATA / "rhai_traveltimes_scenarioB.csv"
    if not b.exists():
        rec("SKIP", "Scenario B times <= Scenario A", "reroute not run yet")
        return
    da, db = pd.read_csv(a), pd.read_csv(b)
    if "village_id" not in da.columns or "village_id" not in db.columns:
        rec("SKIP", "Scenario B times <= Scenario A", "no village_id to join on")
        return
    j = da[["village_id", "min_any"]].merge(
        db[["village_id", "min_any"]], on="village_id", suffixes=("_A", "_B"))
    worse = j[j["min_any_B"] > j["min_any_A"] + 0.01]
    if len(worse) == 0:
        rec("PASS", "Scenario B times <= Scenario A",
            f"{len(j):,} villages compared; median reduction "
            f"{(j['min_any_A'] - j['min_any_B']).median():.1f} min")
    else:
        rec("FAIL", "Scenario B times <= Scenario A",
            f"{len(worse):,} villages got SLOWER after adding facilities.\n"
            f"Adding facilities can only reduce travel time. Check the merge\n"
            f"and that both runs used the same village layer and speeds.")


def check_no_duplicate_facilities() -> None:
    f = DATA / "facilities_merged_final.gpkg"
    if not f.exists():
        rec("SKIP", "no duplicate facilities in merged layer", "no merged layer")
        return
    import geopandas as gpd
    g = gdf(f).to_crs(METRIC_CRS).reset_index(drop=True)
    if "source" not in g.columns:
        rec("SKIP", "no duplicate facilities in merged layer", "no source column")
        return
    a = g[g["source"] == "pphi_geocoded"]
    b = g[g["source"] == "open_data"]
    if a.empty or b.empty:
        rec("SKIP", "no duplicate facilities in merged layer", "one source empty")
        return
    near = gpd.sjoin_nearest(a, b[["geometry"]], how="left",
                            max_distance=DEDUPE_METRES, distance_col="_d")
    n = int(near["_d"].notna().sum())
    if n == 0:
        rec("PASS", "no duplicate facilities in merged layer",
            f"no PPHI point within {DEDUPE_METRES} m of an open-data point")
    else:
        rec("WARN", "no duplicate facilities in merged layer",
            f"{n:,} PPHI points within {DEDUPE_METRES} m of an open-data point —\n"
            f"dedupe may not have been applied")


# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 74)
    print("RHAI SANITY CHECK")
    print("=" * 74)

    print("\nREPO HYGIENE")
    check_gitignore()
    check_git_ignoring_data()

    print("\nGEOCODING INTEGRITY")
    check_geocode_containment()
    check_boundary_not_merged()
    check_uncertainty_honest()
    check_crosswalk()

    print("\nSPATIAL DATA")
    check_crs_and_bounds()
    check_no_duplicate_facilities()

    print("\nROUTING DATA")
    check_villages_and_population()
    check_traveltimes(DATA / "rhai_traveltimes.csv", "Scenario A")
    check_traveltimes(DATA / "rhai_traveltimes_scenarioB.csv", "Scenario B")

    print("\nSCENARIO COMPARISON")
    check_scenario_b_facilities()
    check_scenario_b_times()

    n_fail = sum(1 for l, _, _ in results if l == "FAIL")
    n_warn = sum(1 for l, _, _ in results if l == "WARN")
    n_pass = sum(1 for l, _, _ in results if l == "PASS")
    n_skip = sum(1 for l, _, _ in results if l == "SKIP")

    print()
    print("=" * 74)
    print(f"SUMMARY   {n_pass} pass · {n_warn} warn · {n_fail} fail · {n_skip} skipped")
    print("=" * 74)

    if n_fail:
        print("\nFAILURES — fix before trusting any downstream number:")
        for l, name, detail in results:
            if l == "FAIL":
                print(f"  - {name}")
    if n_warn:
        print("\nWarnings — worth a look, not blocking:")
        for l, name, detail in results:
            if l == "WARN":
                print(f"  - {name}")
    if not n_fail:
        print("\nNo failures. Safe to proceed.")

    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
