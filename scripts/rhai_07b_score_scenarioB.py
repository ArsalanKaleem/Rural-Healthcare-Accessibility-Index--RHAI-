#!/usr/bin/env python
"""
rhai_07_score.py — Turn travel times into an accessibility index.

Run from the project root:
    python scripts/rhai_07_score.py

Inputs
    data/rhai_traveltimes.csv      (output of rhai_06_check_coverage.py)
    data/village_population.csv    (reused from SWAI; optional but recommended)

Outputs
    data/rhai_village_scores.csv   village-level scores
    data/rhai_district_scores.csv  district-level aggregation + underservice burden
    data/rhai_sensitivity.csv      how district ranks move under alternative assumptions

Two scores are produced deliberately:

  score_log       SWAI-style. Winsorise at p1/p99, log1p transform, invert, rescale 0-100.
                  Relative: tells you where a village sits within Sindh.
                  Weakness: not comparable to any other study or any clinical standard.

  score_clinical  Piecewise-linear on fixed time anchors (default 15/30/60/120 min).
                  Absolute: 100 means "within 15 minutes", 0 means "over two hours".
                  Comparable across studies and interpretable to a health ministry.

Report score_clinical as the headline and score_log as the robustness check, or vice
versa — but report the Spearman correlation between them either way. If they disagree
on district ranks, that disagreement is a finding, not a bug to hide.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
TRAVEL = ROOT / "data" / "rhai_traveltimes_scenarioB.csv"
POP = ROOT / "data" / "village_population.csv"

OUT_VILLAGE = ROOT / "data" / "rhai_village_scores_B.csv"
OUT_DISTRICT = ROOT / "data" / "rhai_district_scores_B.csv"
OUT_SENS = ROOT / "data" / "rhai_sensitivity_B.csv"

TIME_COL_PREFERRED = "min_any"
DISTRICT_COL = "district"

# Clinical anchors: (minutes, score). Interpolated linearly between points.
# 60 min is the common "golden hour" / emergency obstetric care benchmark;
# 30 min is a routine-primary-care benchmark. Both are defensible, both are choices.
CLINICAL_ANCHORS = [(0, 100), (15, 100), (30, 85), (60, 55), (120, 15), (240, 0)]

# Winsorisation bounds for the log score.
WINSOR = (0.01, 0.99)

# Sensitivity variants: alternative anchor sets to test rank stability.
SENSITIVITY_ANCHORS = {
    "strict_30":   [(0, 100), (10, 100), (30, 60), (60, 20), (120, 0)],
    "lenient_120": [(0, 100), (30, 100), (60, 80), (120, 40), (300, 0)],
}


# ----------------------------------------------------------------------------
def detect(df: pd.DataFrame, preferred: str, pattern: str, numeric: bool = True) -> str | None:
    if preferred in df.columns:
        return preferred
    cands = [c for c in df.columns if re.search(pattern, c, re.I)]
    if numeric:
        cands = [c for c in cands if pd.api.types.is_numeric_dtype(df[c])]
    return cands[0] if cands else None


def detect_id(df: pd.DataFrame) -> str | None:
    for c in ("village_id", "vill_id", "id", "osm_id", "fid"):
        if c in df.columns:
            return c
    return None


def clinical_score(t: pd.Series, anchors: list[tuple[float, float]]) -> pd.Series:
    """Piecewise-linear interpolation of time -> score, clamped at both ends."""
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    out = np.interp(t.astype(float), xs, ys, left=ys[0], right=ys[-1])
    return pd.Series(out, index=t.index)


def log_score(t: pd.Series, lo_q: float, hi_q: float) -> pd.Series:
    lo, hi = t.quantile(lo_q), t.quantile(hi_q)
    w = t.clip(lower=lo, upper=hi)
    lw = np.log1p(w)
    rng = lw.max() - lw.min()
    if rng == 0:
        return pd.Series(100.0, index=t.index)
    return 100.0 * (1.0 - (lw - lw.min()) / rng)


# ----------------------------------------------------------------------------
def main() -> int:
    if not TRAVEL.exists():
        print(f"[FATAL] {TRAVEL} not found. Run rhai_06_check_coverage.py first.")
        return 1

    df = pd.read_csv(TRAVEL)
    time_col = detect(df, TIME_COL_PREFERRED, r"(min_any|time|minutes|tt_)")
    if time_col is None:
        print(f"[FATAL] No travel-time column found. Columns: {list(df.columns)}")
        return 1
    if DISTRICT_COL not in df.columns:
        print(f"[FATAL] No {DISTRICT_COL!r} column. Run rhai_06 to add it.")
        return 1

    id_col = detect_id(df)
    print(f"[INFO] time column   : {time_col}")
    print(f"[INFO] id column     : {id_col or 'NONE (population join will be skipped)'}")
    print(f"[INFO] rows loaded   : {len(df):,}")

    # --- clean --------------------------------------------------------------
    df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
    df[time_col] = df[time_col].replace([np.inf, -np.inf], np.nan)

    n_unreach = int(df[time_col].isna().sum())
    if n_unreach:
        print(f"[INFO] {n_unreach:,} unreachable villages ({n_unreach/len(df):.1%}). "
              f"These get score 0 and are counted separately — do NOT silently drop them, "
              f"they are the most underserved places in the dataset.")

    if id_col:
        before = len(df)
        df = df.drop_duplicates(subset=[id_col], keep="first")
        if len(df) < before:
            print(f"[INFO] dropped {before - len(df):,} duplicate villages from overlapping "
                  f"district halos (kept first occurrence).")

    reachable = df[time_col].notna()

    # --- scores -------------------------------------------------------------
    df["score_log"] = np.nan
    df.loc[reachable, "score_log"] = log_score(df.loc[reachable, time_col], *WINSOR)
    df["score_log"] = df["score_log"].fillna(0.0)

    df["score_clinical"] = clinical_score(df[time_col].fillna(np.inf), CLINICAL_ANCHORS)

    rho_scores, _ = spearmanr(df.loc[reachable, "score_log"],
                              df.loc[reachable, "score_clinical"])
    print(f"[INFO] Spearman rho(score_log, score_clinical) at village level = {rho_scores:.3f}")

    # Access bands — the thing a health ministry will actually read.
    df["access_band"] = pd.cut(
        df[time_col].fillna(np.inf),
        bins=[-0.01, 15, 30, 60, 120, np.inf],
        labels=["<15 min", "15-30 min", "30-60 min", "60-120 min", ">120 min / unreachable"],
    )

    # --- population join ----------------------------------------------------
    have_pop = False
    if POP.exists() and id_col:
        pop = pd.read_csv(POP)
        pop_id = detect_id(pop)
        pop_col = detect(pop, "population", r"(pop|people|persons|inhab)")
        if pop_id and pop_col:
            df = df.merge(pop[[pop_id, pop_col]].rename(columns={pop_id: id_col,
                                                                pop_col: "population"}),
                          on=id_col, how="left")
            matched = int(df["population"].notna().sum())
            print(f"[INFO] population joined on {id_col!r}: "
                  f"{matched:,}/{len(df):,} matched ({matched/len(df):.1%})")
            if matched / len(df) < 0.9:
                print("[WARN] Under 90% matched. Check the id key before trusting any "
                      "population-weighted number.")
            have_pop = matched > 0
        else:
            print(f"[WARN] Could not identify id/population columns in {POP.name}: "
                  f"{list(pop.columns)}")
    elif not POP.exists():
        print(f"[WARN] {POP.name} not found — skipping population weighting.")

    if not have_pop:
        df["population"] = np.nan

    # --- district aggregation ----------------------------------------------
    def agg_district(g: pd.DataFrame) -> pd.Series:
        t = g[time_col]
        pop = g["population"]
        w = pop.fillna(0)
        has_w = w.sum() > 0
        return pd.Series({
            "villages": len(g),
            "population": w.sum() if has_w else np.nan,
            "median_min": t.median(),
            "p90_min": t.quantile(0.90),
            "unreachable": int(t.isna().sum()),
            "score_log": g["score_log"].mean(),
            "score_clinical": g["score_clinical"].mean(),
            "score_clinical_popw": (
                np.average(g["score_clinical"], weights=w) if has_w else np.nan),
            "pct_villages_over_60min": float((t.fillna(np.inf) > 60).mean() * 100),
            "pct_pop_over_60min": (
                float(w[t.fillna(np.inf) > 60].sum() / w.sum() * 100) if has_w else np.nan),
            # The metric that ranks where the most PEOPLE are poorly served.
            "underservice_burden": (
                float((((100 - g["score_clinical"]) / 100) * w).sum()) if has_w else np.nan),
        })

    dist = df.groupby(DISTRICT_COL).apply(agg_district).reset_index()
    sort_key = "underservice_burden" if have_pop else "median_min"
    dist = dist.sort_values(sort_key, ascending=False)

    # --- sensitivity --------------------------------------------------------
    base_rank = dist.set_index(DISTRICT_COL)["score_clinical"].rank(ascending=False)
    sens_rows = []
    for label, anchors in SENSITIVITY_ANCHORS.items():
        alt = clinical_score(df[time_col].fillna(np.inf), anchors)
        alt_dist = alt.groupby(df[DISTRICT_COL]).mean()
        alt_rank = alt_dist.rank(ascending=False)
        joined = pd.concat([base_rank, alt_rank], axis=1, keys=["base", label]).dropna()
        rho, p = spearmanr(joined["base"], joined[label])
        sens_rows.append({"variant": label, "spearman_rho": rho, "p_value": p,
                          "max_rank_shift": int((joined["base"] - joined[label]).abs().max())})
        print(f"[SENS] {label:<12} rho={rho:.3f}  max rank shift={sens_rows[-1]['max_rank_shift']}")

    # Also test log vs clinical at district level.
    rho_d, _ = spearmanr(dist["score_log"], dist["score_clinical"])
    sens_rows.append({"variant": "log_vs_clinical_district", "spearman_rho": rho_d,
                      "p_value": np.nan, "max_rank_shift": np.nan})
    print(f"[SENS] district-level rho(score_log, score_clinical) = {rho_d:.3f}")

    sens = pd.DataFrame(sens_rows)

    # --- write --------------------------------------------------------------
    df.to_csv(OUT_VILLAGE, index=False)
    dist.round(2).to_csv(OUT_DISTRICT, index=False)
    sens.round(4).to_csv(OUT_SENS, index=False)

    print()
    print("=" * 74)
    print("DISTRICT RANKING — worst access first")
    print("=" * 74)
    cols = [DISTRICT_COL, "villages", "median_min", "pct_villages_over_60min",
            "score_clinical", "underservice_burden"]
    pd.set_option("display.width", 130)
    print(dist[cols].round(1).to_string(index=False))
    print()
    print("SANITY CHECK: Karachi/Hyderabad districts should sit near the BEST end and "
          "Tharparkar/Mithi, Kachho, Rann of Kutch near the WORST. If they don't, stop "
          "and debug before writing anything up.")
    print()
    print(f"Wrote {OUT_VILLAGE.name}, {OUT_DISTRICT.name}, {OUT_SENS.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
