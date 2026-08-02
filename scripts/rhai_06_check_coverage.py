#!/usr/bin/env python
"""
rhai_06_check_coverage.py — RHAI coverage audit, stitch, and QA.

Run from the project root:
    python scripts/rhai_06_check_coverage.py

What it does (read-only on district CSVs, safe to rerun):
  1. Reads GADM, filters to Sindh, lists every district the router should have produced.
  2. Diffs that list against data/district_results/*.csv.
  3. Flags missing districts, empty files, and districts with suspicious statistics.
  4. Stitches everything present into data/rhai_traveltimes.csv.
  5. Prints a QA report you can paste into a chat or into the paper's methods section.

Nothing is deleted or overwritten except rhai_traveltimes.csv.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# CONFIG — edit only these
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent  # assumes script lives in scripts/
GADM = ROOT / "data" / "gadm41_PAK_3.shp"
PROVINCE_COL = "NAME_1"
PROVINCE = "Sindh"
DISTRICT_COL = "NAME_3"          # your handoff says level-3 names are districts
RESULTS_DIR = ROOT / "data" / "district_results"
STITCHED = ROOT / "data" / "rhai_traveltimes.csv"

# Column in the district CSVs holding travel time to nearest facility of any type.
# Auto-detected if this exact name isn't found.
TIME_COL_PREFERRED = "min_any"

# Sanity thresholds for flagging, not for filtering.
MAX_PLAUSIBLE_MIN = 600          # 10 h to nearest facility is almost certainly a bug
MIN_VILLAGES_WARN = 5            # tiny districts are possible but worth eyeballing


# ----------------------------------------------------------------------------
def key(name: str) -> str:
    """Normalise a district name to a comparable key: 'Karachi West' -> 'karachi_west'."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def detect_time_col(df: pd.DataFrame) -> str | None:
    if TIME_COL_PREFERRED in df.columns:
        return TIME_COL_PREFERRED
    candidates = [c for c in df.columns if re.search(r"(min_any|time|minutes|tt_)", c, re.I)]
    numeric = [c for c in candidates if pd.api.types.is_numeric_dtype(df[c])]
    return numeric[0] if numeric else None


def detect_id_col(df: pd.DataFrame) -> str | None:
    for c in ("village_id", "vill_id", "id", "osm_id", "fid"):
        if c in df.columns:
            return c
    return None


# ----------------------------------------------------------------------------
def main() -> int:
    if not GADM.exists():
        print(f"[FATAL] GADM not found at {GADM}")
        return 1
    if not RESULTS_DIR.exists():
        print(f"[FATAL] {RESULTS_DIR} does not exist — has the router run at all?")
        return 1

    # --- expected districts -------------------------------------------------
    gadm = gpd.read_file(GADM)
    if PROVINCE_COL not in gadm.columns or DISTRICT_COL not in gadm.columns:
        print(f"[FATAL] Expected columns {PROVINCE_COL!r}/{DISTRICT_COL!r}. "
              f"Found: {list(gadm.columns)}")
        return 1

    sindh = gadm[gadm[PROVINCE_COL] == PROVINCE]
    expected = sorted(sindh[DISTRICT_COL].dropna().unique().tolist())
    expected_keys = {key(d): d for d in expected}

    # --- what we actually have ----------------------------------------------
    csvs = sorted(RESULTS_DIR.glob("*.csv"))
    found_keys = {key(p.stem): p for p in csvs}

    missing = [expected_keys[k] for k in sorted(set(expected_keys) - set(found_keys))]
    orphans = [found_keys[k].name for k in sorted(set(found_keys) - set(expected_keys))]

    print("=" * 74)
    print(f"RHAI COVERAGE AUDIT — {PROVINCE}")
    print("=" * 74)
    print(f"GADM districts expected : {len(expected)}")
    print(f"CSV files present       : {len(csvs)}")
    print(f"Matched                 : {len(set(expected_keys) & set(found_keys))}")
    print()

    if missing:
        print(f"MISSING ({len(missing)}) — rerun rhai_05 to pick these up:")
        for d in missing:
            print(f"   - {d}")
    else:
        print("MISSING: none. Full province coverage.")
    print()

    if orphans:
        print(f"UNMATCHED CSVs ({len(orphans)}) — filename doesn't match any GADM name.")
        print("   Usually a spelling/underscore mismatch, not a real problem:")
        for o in orphans:
            print(f"   - {o}")
        print()

    # --- load and stitch ----------------------------------------------------
    frames, empties, bad = [], [], []
    for k, path in found_keys.items():
        try:
            df = pd.read_csv(path)
        except Exception as e:  # noqa: BLE001
            bad.append((path.name, str(e)))
            continue
        if df.empty:
            empties.append(path.name)
            continue
        df["district"] = expected_keys.get(k, path.stem)
        df["source_file"] = path.name
        frames.append(df)

    if bad:
        print(f"UNREADABLE FILES ({len(bad)}):")
        for n, e in bad:
            print(f"   - {n}: {e}")
        print()
    if empties:
        print(f"EMPTY FILES ({len(empties)}) — delete these so rhai_05 retries them:")
        for n in empties:
            print(f"   - {n}")
        print()

    if not frames:
        print("[FATAL] Nothing loadable. Stopping.")
        return 1

    # Align columns across districts; warn if schemas drifted between runs.
    colsets = {frozenset(f.columns) for f in frames}
    if len(colsets) > 1:
        print(f"[WARN] {len(colsets)} different column schemas across district CSVs.")
        print("       Likely you reran the router after editing it. Columns will be")
        print("       unioned and missing values left as NaN. Check before publishing.\n")

    all_df = pd.concat(frames, ignore_index=True, sort=False)

    time_col = detect_time_col(all_df)
    if time_col is None:
        print("[FATAL] Could not find a travel-time column. Columns present:")
        print(f"        {list(all_df.columns)}")
        return 1
    if time_col != TIME_COL_PREFERRED:
        print(f"[INFO] Using {time_col!r} as the travel-time column.\n")

    id_col = detect_id_col(all_df)

    # --- QA -----------------------------------------------------------------
    print("=" * 74)
    print("QA REPORT")
    print("=" * 74)
    print(f"Villages routed         : {len(all_df):,}")
    print(f"Travel-time column      : {time_col}")

    n_null = int(all_df[time_col].isna().sum())
    print(f"Null / unreachable      : {n_null:,} ({n_null / len(all_df):.1%})")

    n_inf = int(np.isinf(all_df[time_col].replace({np.inf: np.inf})).sum())
    if n_inf:
        print(f"Infinite values         : {n_inf:,}  <-- disconnected graph components")

    finite = all_df[time_col].replace([np.inf, -np.inf], np.nan).dropna()
    if len(finite):
        print(f"Median (all Sindh)      : {finite.median():.1f} min")
        print(f"Mean                    : {finite.mean():.1f} min")
        print(f"p90 / p95 / p99         : {finite.quantile(0.90):.1f} / "
              f"{finite.quantile(0.95):.1f} / {finite.quantile(0.99):.1f} min")
        print(f"Max                     : {finite.max():.1f} min")
        n_zero = int((finite <= 0).sum())
        if n_zero:
            print(f"[WARN] {n_zero} villages at <=0 min — village snapped to the same "
                  f"graph node as a facility. Defensible, but say so in the paper.")
        n_wild = int((finite > MAX_PLAUSIBLE_MIN).sum())
        if n_wild:
            print(f"[WARN] {n_wild} villages above {MAX_PLAUSIBLE_MIN} min — inspect these, "
                  f"they are usually island/disconnected-road artefacts, not real.")

    if id_col:
        dupes = int(all_df[id_col].duplicated().sum())
        print(f"Duplicate {id_col:<14}: {dupes:,}"
              + ("   <-- overlapping district halos double-counting villages" if dupes else ""))
    else:
        print("[WARN] No village id column found — cannot check duplicates. "
              "Add one in the router; you need it for the population join.")

    print()
    print("PER-DISTRICT SUMMARY")
    print("-" * 74)
    g = (all_df.assign(_t=all_df[time_col].replace([np.inf, -np.inf], np.nan))
                .groupby("district")["_t"]
                .agg(villages="size", median="median", p90=lambda s: s.quantile(0.90),
                     max="max", null=lambda s: s.isna().sum())
                .sort_values("median", ascending=False))
    pd.set_option("display.width", 120)
    print(g.round(1).to_string())
    print()

    thin = g[g["villages"] < MIN_VILLAGES_WARN]
    if len(thin):
        print(f"[WARN] {len(thin)} district(s) with < {MIN_VILLAGES_WARN} villages — "
              f"check the village layer clipped correctly:")
        print("       " + ", ".join(thin.index.tolist()))
        print()

    # --- write --------------------------------------------------------------
    STITCHED.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(STITCHED, index=False)
    print(f"Stitched -> {STITCHED}  ({len(all_df):,} rows, {len(all_df.columns)} cols)")

    if missing:
        print()
        print(f"NOT COMPLETE: {len(missing)} district(s) still missing. "
              f"Rerun rhai_05_route_by_district.py before scoring.")
        return 2

    print("\nCoverage complete. Safe to run rhai_07_score.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
