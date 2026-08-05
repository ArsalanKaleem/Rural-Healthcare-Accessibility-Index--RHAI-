#!/usr/bin/env python
"""
rhai_13_compare_scenarios.py — The paper's central result.

    Scenario A: open data only          -> upper bound on travel time
    Scenario B: open data + PPHI        -> lower bound on travel time

Reports per district: median under each, the ratio, and how much the ranking moves.
The claim this supports is:

    "Open-data-only estimates overstate median rural travel time by a factor of N."

and, if ranks hold while magnitudes do not:

    "Open data can support relative ranking of districts but not absolute travel-time
     estimates."

That second finding is the useful one for other researchers, because it tells them
exactly what the data they have can and cannot be used for.

USAGE
    python scripts/rhai_13_compare_scenarios.py

INPUTS
    data/rhai_traveltimes.csv             Scenario A
    data/rhai_traveltimes_scenarioB.csv   Scenario B
    data/village_population.csv           optional but strongly recommended

OUTPUTS
    data/rhai_scenario_comparison.csv     the table
    figures/fig_scenario_comparison.png   the figure
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIGURES = ROOT / "figures"

A_CSV = DATA / "rhai_traveltimes.csv"
B_CSV = DATA / "rhai_traveltimes_scenarioB.csv"
POP = DATA / "village_population.csv"

OUT_CSV = DATA / "rhai_scenario_comparison.csv"
OUT_FIG = FIGURES / "fig_scenario_comparison.png"

TIME_COL = "min_any"
ID_COL = "village_id"
DIST_COL = "district"


def load(path: Path, tag: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if TIME_COL not in df.columns:
        print(f"[FATAL] {path.name} has no {TIME_COL!r} column: {list(df.columns)}")
        sys.exit(1)
    df[TIME_COL] = pd.to_numeric(df[TIME_COL], errors="coerce").replace(
        [np.inf, -np.inf], np.nan)
    keep = [c for c in (ID_COL, DIST_COL, TIME_COL) if c in df.columns]
    df = df[keep].rename(columns={TIME_COL: f"min_{tag}"})
    if ID_COL in df.columns:
        df = df.drop_duplicates(subset=[ID_COL])
    print(f"[INFO] {path.name}: {len(df):,} villages")
    return df


def main() -> int:
    if not A_CSV.exists():
        print(f"[FATAL] {A_CSV.name} not found.")
        return 1
    if not B_CSV.exists():
        print(f"[FATAL] {B_CSV.name} not found — run the Scenario B reroute first.")
        return 1

    a = load(A_CSV, "A")
    b = load(B_CSV, "B")

    if ID_COL not in a.columns or ID_COL not in b.columns:
        print(f"[FATAL] both files need a {ID_COL!r} column to join on.")
        return 1

    m = a.merge(b[[ID_COL, "min_B"]], on=ID_COL, how="inner")
    print(f"[INFO] villages in both scenarios: {len(m):,}")
    if len(m) < 0.95 * len(a):
        print(f"[WARN] {len(a) - len(m):,} villages missing from Scenario B — "
              f"check the reroute completed all districts")

    # --- population ---------------------------------------------------------
    have_pop = False
    if POP.exists():
        pop = pd.read_csv(POP)
        pcol = next((c for c in pop.columns
                     if c.lower() in ("population", "pop", "people", "pop_sum")), None)
        if ID_COL in pop.columns and pcol:
            m = m.merge(pop[[ID_COL, pcol]].rename(columns={pcol: "population"}),
                        on=ID_COL, how="left")
            have_pop = m["population"].notna().sum() > 0
            print(f"[INFO] population matched: {int(m['population'].notna().sum()):,}")
    if not have_pop:
        m["population"] = np.nan
        print("[WARN] no population data — population-weighted figures skipped")

    # --- village-level ------------------------------------------------------
    both = m["min_A"].notna() & m["min_B"].notna()
    m["delta"] = m["min_A"] - m["min_B"]
    m["ratio"] = m["min_A"] / m["min_B"].replace(0, np.nan)

    print()
    print("=" * 74)
    print("PROVINCE-LEVEL")
    print("=" * 74)
    print(f"Median travel time, Scenario A : {m.loc[both,'min_A'].median():.1f} min")
    print(f"Median travel time, Scenario B : {m.loc[both,'min_B'].median():.1f} min")
    print(f"Median reduction               : {m.loc[both,'delta'].median():.1f} min")
    ov = m.loc[both, "min_A"].median() / max(m.loc[both, "min_B"].median(), 1e-9)
    print(f"Overstatement factor           : {ov:.2f}x")
    print()
    for thr in (30, 60, 120):
        pa = (m.loc[both, "min_A"] > thr).mean() * 100
        pb = (m.loc[both, "min_B"] > thr).mean() * 100
        print(f"  villages over {thr:>3} min : {pa:5.1f}% (A)  ->  {pb:5.1f}% (B)")
    print()

    # --- district-level -----------------------------------------------------
    if DIST_COL not in m.columns:
        print("[WARN] no district column — skipping district comparison")
        m.to_csv(OUT_CSV, index=False)
        return 0

    def agg(g: pd.DataFrame) -> pd.Series:
        w = g["population"].fillna(0)
        hw = w.sum() > 0
        return pd.Series({
            "villages": len(g),
            "median_A": g["min_A"].median(),
            "median_B": g["min_B"].median(),
            "delta_min": g["min_A"].median() - g["min_B"].median(),
            "ratio": g["min_A"].median() / max(g["min_B"].median(), 1e-9),
            "pct_over60_A": (g["min_A"] > 60).mean() * 100,
            "pct_over60_B": (g["min_B"] > 60).mean() * 100,
            "pop_median_B": (np.average(g["min_B"].fillna(g["min_B"].median()),
                                        weights=w) if hw else np.nan),
        })

    d = m[both].groupby(DIST_COL).apply(agg).reset_index()
    d["rank_A"] = d["median_A"].rank(ascending=False)
    d["rank_B"] = d["median_B"].rank(ascending=False)
    d["rank_shift"] = (d["rank_A"] - d["rank_B"]).abs()
    d = d.sort_values("delta_min", ascending=False)

    rho, p = spearmanr(d["median_A"], d["median_B"])

    print("=" * 74)
    print("DISTRICT COMPARISON — largest reduction first")
    print("=" * 74)
    cols = [DIST_COL, "villages", "median_A", "median_B", "delta_min", "ratio",
            "pct_over60_A", "pct_over60_B", "rank_shift"]
    pd.set_option("display.width", 140)
    print(d[cols].round(1).to_string(index=False))
    print()
    print(f"Spearman rho(district rank A, rank B) = {rho:.3f}  (p={p:.4g})")
    print(f"Largest rank shift: {int(d['rank_shift'].max())} places")
    print()
    if rho > 0.8:
        print("INTERPRETATION: district ranks are largely preserved despite large")
        print("  magnitude changes. Open data can support RELATIVE ranking but not")
        print("  ABSOLUTE travel-time estimates. State this explicitly — it is the")
        print("  most directly useful finding for other researchers.")
    else:
        print("INTERPRETATION: ranks are NOT preserved. Open-data-only accessibility")
        print("  studies of rural Pakistan risk misidentifying which districts are")
        print("  worst served, not merely misestimating by how much. Stronger claim,")
        print("  so check the reroute and crosswalk carefully before relying on it.")
    print()

    d.round(3).to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV.name}")

    # --- figure -------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed — skipping figure")
        return 0

    dd = d.sort_values("median_A", ascending=True)
    fig, ax = plt.subplots(figsize=(10, max(5, 0.34 * len(dd))))
    y = range(len(dd))
    ax.hlines(list(y), dd["median_B"], dd["median_A"], color="#cccccc", lw=2, zorder=1)
    ax.scatter(dd["median_B"], list(y), s=42, color="#2b7a4b", zorder=3,
               label="Scenario B (open + PPHI)")
    ax.scatter(dd["median_A"], list(y), s=42, color="#c0392b", zorder=3,
               label="Scenario A (open data only)")
    ax.set_yticks(list(y))
    ax.set_yticklabels(dd[DIST_COL], fontsize=9)
    ax.set_xlabel("Median travel time to nearest health facility (minutes)")
    ax.set_title("Effect of missing facility data on estimated travel time, by district",
                 fontsize=12, weight="bold", loc="left")
    ax.legend(frameon=False, loc="lower right")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="x", alpha=0.25)
    plt.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {OUT_FIG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
