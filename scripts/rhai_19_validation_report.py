#!/usr/bin/env python
"""
rhai_19_validation_report.py — Turn the scored sample into a reportable statistic.

    python scripts/rhai_19_validation_report.py

Reads data/validation_sample.gpkg after you have filled the `verdict` column in QGIS,
and reports the presence rate with Wilson confidence intervals.

TWO FIGURES, BOTH REPORTED
    among clear verdicts   yes / (yes + no)      — the optimistic reading
    conservative           yes / all             — unclear counted as failures

    Lead with the conservative figure. It is the one that survives a hostile read.

WHY WILSON
    At n = 50 with a proportion near 0.8, the normal approximation is unreliable and
    can produce intervals extending past 1.0. Wilson is well behaved at small n and
    near the boundaries.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SAMPLE = DATA / "validation_sample.gpkg"
OUT_CSV = DATA / "geocode_satellite_validation.csv"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — stable at small n and near 0 or 1."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main() -> int:
    if not SAMPLE.exists():
        print(f"[FATAL] {SAMPLE.name} not found. Run rhai_18_validation_sample.py first.")
        return 1

    g = gpd.read_file(SAMPLE)
    if "verdict" not in g.columns:
        print("[FATAL] no `verdict` column.")
        return 1

    g["verdict"] = g["verdict"].fillna("").astype(str).str.strip().str.lower()
    blank = int((g["verdict"] == "").sum())
    if blank:
        print(f"[WARN] {blank} of {len(g)} points not yet scored.")
        if blank == len(g):
            print("       Nothing to report. Score them in QGIS first.")
            return 1
        print("       Reporting on the scored subset only.\n")

    v = g[g["verdict"] != ""]
    n = len(v)
    yes = int((v["verdict"] == "yes").sum())
    no = int((v["verdict"] == "no").sum())
    unclear = int((v["verdict"] == "unclear").sum())
    other = n - yes - no - unclear
    if other:
        print(f"[WARN] {other} verdicts are not yes/no/unclear: "
              f"{sorted(set(v['verdict']) - {'yes','no','unclear'})}")

    clear = yes + no

    print("=" * 70)
    print("SATELLITE VALIDATION")
    print("=" * 70)
    print(f"Points scored : {n}")
    print(f"  yes         : {yes}")
    print(f"  no          : {no}")
    print(f"  unclear     : {unclear}")
    print()

    if clear:
        lo, hi = wilson(yes, clear)
        print(f"Among clear verdicts : {yes}/{clear} = {yes/clear:.1%}"
              f"   95% CI [{lo:.1%}, {hi:.1%}]")
    lo2, hi2 = wilson(yes, n)
    print(f"Conservative         : {yes}/{n} = {yes/n:.1%}"
          f"   95% CI [{lo2:.1%}, {hi2:.1%}]   <- lead with this")
    print()

    if unclear / max(n, 1) > 0.25:
        print(f"[NOTE] {unclear/n:.0%} of verdicts were unclear. That is high enough to")
        print("       report prominently: imagery resolution is a binding constraint")
        print("       on validation in rural Sindh, which is itself a finding.")
        print()

    if "district" in v.columns:
        by = v.groupby("district")["verdict"].agg(
            n="size", yes=lambda s: (s == "yes").sum())
        by["rate"] = (by["yes"] / by["n"] * 100).round(0)
        print("By district (small n each — indicative only):")
        print(by.sort_values("rate").to_string())
        print()

    v.drop(columns="geometry").to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV.name}")
    print()
    print("SUGGESTED METHODS TEXT")
    print("-" * 70)
    print(f"  A stratified random sample of {n} geocoded facilities was assessed")
    print(f"  against high-resolution satellite imagery for the presence of a")
    print(f"  structure consistent with a small health facility within 500 m.")
    if clear:
        lo, hi = wilson(yes, clear)
        print(f"  {yes} of {clear} clear verdicts were positive ({yes/clear:.0%},")
        print(f"  95% CI {lo:.0%}-{hi:.0%}); treating unclear cases as negative gives")
        print(f"  {yes/n:.0%} ({lo2:.0%}-{hi2:.0%}).")
    print()
    print("  Imagery confirms physical presence only. It cannot establish that a")
    print("  structure is a health facility, nor that it is staffed or operational.")
    print()
    print("  Do NOT publish a list of facilities judged absent. Report rates and")
    print("  district aggregates only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
