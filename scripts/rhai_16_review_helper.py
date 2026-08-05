#!/usr/bin/env python
"""
rhai_16_review_helper.py — Make the 175-row geocode review fast and consistent.

WHAT IT DOES
    Reads pphi_geocode_review.csv (the 78-87 score band), sorts it so the easy
    decisions cluster, pre-fills a suggested decision for rows where the evidence is
    one-sided, and writes a clean review sheet with only the columns you need.

    You then open the sheet, fill or correct the `decision` column, save it as
    pphi_geocode_review_done.csv, and run this script again with --apply to fold the
    accepted rows into the geocoded layer.

WHY PRE-FILL
    Roughly half of these rows are decidable mechanically:
      - landed_in != district_gadm            -> reject (wrong district)
      - matched_place is a canal/farm/office  -> reject (not a settlement)
      - score >= 86 and district matches      -> likely accept
    Pre-filling those leaves you judging the genuinely ambiguous middle, which is
    where human judgement actually adds something.

    Everything pre-filled is marked in `suggested_reason` so you can audit it. Nothing
    is applied until you save the _done file yourself.

USAGE
    python scripts/rhai_16_review_helper.py            # build the review sheet
    python scripts/rhai_16_review_helper.py --apply    # fold decisions back in

OUTPUTS
    data/pphi_geocode_review_sheet.csv    open this in Excel
    data/pphi_geocoded_reviewed.gpkg      after --apply: verified + accepted rows
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

REVIEW_IN = DATA / "pphi_geocode_review.csv"
SHEET = DATA / "pphi_geocode_review_sheet.csv"
DONE = DATA / "pphi_geocode_review_done.csv"
GEOCODED = DATA / "pphi_geocoded.gpkg"
OUT_GPKG = DATA / "pphi_geocoded_reviewed.gpkg"

# Matched place is clearly not a settlement.
NOT_SETTLEMENT = re.compile(
    r"\b(distributary|minor|canal|branch|wah|farm|office|scheme|society|"
    r"colony\s+block|airport|railway|station|dam|barrage|reserve|forest)\b", re.I)

HIGH_CONF = 86.0


def build() -> int:
    if not REVIEW_IN.exists():
        print(f"[FATAL] {REVIEW_IN.name} not found. Run rhai_11 first.")
        return 1

    df = pd.read_csv(REVIEW_IN)
    print(f"[INFO] {len(df):,} rows in the review band")

    for c in ("settlement", "matched_place", "score", "district"):
        if c not in df.columns:
            print(f"[FATAL] expected column {c!r} missing. Columns: {list(df.columns)}")
            return 1

    has_district_cols = {"landed_in", "district_gadm"}.issubset(df.columns)

    df["suggested"] = ""
    df["suggested_reason"] = ""

    # 1. Wrong district — reject regardless of name similarity. This is the failure
    #    mode that made the first geocoder 26% correct.
    if has_district_cols:
        wrong = df["landed_in"].notna() & (df["landed_in"] != df["district_gadm"])
        df.loc[wrong, "suggested"] = "reject"
        df.loc[wrong, "suggested_reason"] = "landed in a different district"
        print(f"[INFO] {int(wrong.sum()):,} rows land outside their district")

    # 2. Matched a canal, farm or office rather than a settlement.
    notset = df["matched_place"].astype(str).str.contains(NOT_SETTLEMENT, na=False)
    notset &= df["suggested"] == ""
    df.loc[notset, "suggested"] = "reject"
    df.loc[notset, "suggested_reason"] = "matched a non-settlement feature"
    print(f"[INFO] {int(notset.sum()):,} rows matched a canal/farm/office")

    # 3. High score and district agrees — likely correct.
    high = (df["score"] >= HIGH_CONF) & (df["suggested"] == "")
    if has_district_cols:
        high &= (df["landed_in"] == df["district_gadm"])
    df.loc[high, "suggested"] = "accept"
    df.loc[high, "suggested_reason"] = f"score >= {HIGH_CONF:.0f}, district agrees"
    print(f"[INFO] {int(high.sum()):,} rows suggested accept")

    undecided = int((df["suggested"] == "").sum())
    print(f"[INFO] {undecided:,} rows need your judgement\n")

    df["decision"] = df["suggested"]

    cols = ["decision", "suggested", "suggested_reason", "district", "name",
            "settlement", "matched_place", "score"]
    if has_district_cols:
        cols += ["district_gadm", "landed_in"]
    cols += [c for c in ("hf_type", "gaz_source", "lon", "lat") if c in df.columns]

    out = df[[c for c in cols if c in df.columns]].copy()
    # Undecided first, then by score descending, so the hard rows are at the top
    # while you are fresh.
    out["_order"] = (out["suggested"] != "").astype(int)
    out = out.sort_values(["_order", "score"], ascending=[True, False]).drop(
        columns="_order")
    out.to_csv(SHEET, index=False)

    print("=" * 74)
    print(f"Wrote {SHEET.name}")
    print("=" * 74)
    print("""
HOW TO REVIEW

  Open the sheet in Excel. The `decision` column is pre-filled where the evidence
  was one-sided; blank rows need you. Undecided rows are at the top.

  For each blank row, compare `settlement` (what PPHI called it) with
  `matched_place` (what the gazetteer found) and ask: same place, different
  spelling?

    accept   transliteration variants of the same settlement
             Therhi/Teri · Sethar Ja/Setharja · Kot Bhutto/Kot Bhuto
             Ghari Khuda Bux/Gari Khuda Bakhsh

    reject   two different real places
             Kandhar/Kandhkot · Napirabad/Nasirabad
             anything where landed_in differs from district_gadm

  When unsure, reject. A wrong coordinate corrupts a travel time; a missing
  facility just leaves you where Scenario A already was. The costs are asymmetric.

  Spot-check the pre-filled rows too — `suggested_reason` says why each was set.

  Save as pphi_geocode_review_done.csv (keep the decision column), then run:
      python scripts/rhai_16_review_helper.py --apply
""")
    return 0


def apply() -> int:
    if not DONE.exists():
        print(f"[FATAL] {DONE.name} not found.")
        print("        Fill in the decision column in "
              f"{SHEET.name} and save it under that name.")
        return 1
    try:
        import geopandas as gpd
    except ImportError:
        print("[FATAL] geopandas required")
        return 1

    rev = pd.read_csv(DONE)
    if "decision" not in rev.columns:
        print("[FATAL] no `decision` column in the done file")
        return 1

    rev["decision"] = rev["decision"].astype(str).str.strip().str.lower()
    n_acc = int((rev["decision"] == "accept").sum())
    n_rej = int((rev["decision"] == "reject").sum())
    n_blank = int((~rev["decision"].isin(["accept", "reject"])).sum())

    print(f"[INFO] accept {n_acc:,} · reject {n_rej:,} · undecided {n_blank:,}")
    if n_blank:
        print(f"[WARN] {n_blank:,} rows have no decision — treated as reject.")

    acc = rev[rev["decision"] == "accept"].copy()
    if acc.empty:
        print("[INFO] nothing accepted; not writing a new layer.")
        return 0
    if not {"lon", "lat"}.issubset(acc.columns):
        print("[FATAL] the done file needs lon/lat columns to build geometry.")
        return 1

    add = gpd.GeoDataFrame(
        acc, geometry=gpd.points_from_xy(acc["lon"], acc["lat"]), crs=4326)
    add["geocode_method"] = "settlement_centroid_fuzzy_manual_review"
    add["positional_uncertainty_km"] = 2.0

    if GEOCODED.exists():
        base = gpd.read_file(GEOCODED)
        merged = pd.concat([base, add], ignore_index=True, sort=False)
        merged = gpd.GeoDataFrame(merged, geometry="geometry", crs=4326)
    else:
        merged = add

    merged.to_file(OUT_GPKG, driver="GPKG")
    print()
    print(f"Wrote {OUT_GPKG.name}: {len(merged):,} facilities "
          f"({len(base) if GEOCODED.exists() else 0:,} auto-verified + {len(add):,} "
          f"manually accepted)")
    print()
    print("NEXT: point rhai_12_merge_facilities.py at pphi_geocoded_reviewed.gpkg")
    print("      (change PPHI_FAC at the top), rerun it, then reroute.")
    print()
    print("      Report the manual review in the paper: how many rows were reviewed,")
    print("      how many accepted, and that the reviewer was the author. If a second")
    print("      person can code a subset, report Cohen's kappa.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="fold decisions from the _done file into a new layer")
    args = ap.parse_args()
    sys.exit(apply() if args.apply else build())
