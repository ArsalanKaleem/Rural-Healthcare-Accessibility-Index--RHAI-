#!/usr/bin/env python
"""
rhai_20_final_audit.py — Verify every number that appears in the paper.

Recomputes each figure the manuscript claims, straight from the data files, and prints
them in a form you can check against the text line by line. Anything the paper asserts
that this script cannot reproduce is a number to fix or delete.

    python scripts/rhai_20_final_audit.py

Writes data/rhai_paper_numbers.txt — a plain-text record of every reported quantity,
suitable for attaching to a submission or pasting into a chat.

WHY THIS EXISTS
    During drafting, one value in Table 4 (the Scenario B 90th percentile) was carried
    into the manuscript without ever having been computed. It looked plausible and
    survived several readings. This script exists so that class of error cannot recur:
    every number in the paper either appears in this output or does not belong in the
    paper.
"""

from __future__ import annotations

import io
import math
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "rhai_paper_numbers.txt"

A_CSV = DATA / "rhai_traveltimes.csv"
B_CSV = DATA / "rhai_traveltimes_scenarioB.csv"
POP = DATA / "village_population.csv"
FAC_A = DATA / "facilities_tiered.gpkg"
FAC_B = DATA / "facilities_merged_final.gpkg"
PPHI_GEO = DATA / "pphi_geocoded_reviewed.gpkg"
PPHI_CSV = DATA / "pphi_facilities.csv"
SUMMARY = DATA / "facility_source_summary.csv"
SCORES_A = DATA / "rhai_district_scores.csv"
SCORES_B = DATA / "rhai_district_scores_B.csv"
AUDIT = DATA / "rhai_layer_audit.csv"
VALID = DATA / "validation_sample.gpkg"
CIRC = DATA / "rhai_circularity_check.csv"

TIME = "min_any"
VID = "village_id"


def wmedian(v, w):
    """Population-weighted median."""
    v = np.asarray(v, float); w = np.asarray(w, float)
    o = np.argsort(v); v, w = v[o], w[o]
    c = np.cumsum(w)
    return float(v[np.searchsorted(c, c[-1] / 2)])


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def rule(t):
    print()
    print("=" * 76)
    print(t)
    print("=" * 76)


def main() -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        print(f"RHAI — every number reported in the manuscript")
        print(f"Regenerated {datetime.now():%Y-%m-%d %H:%M}")
        print("Check each against the text. Anything in the paper but not here is unverified.")

        try:
            import geopandas as gpd
        except ImportError:
            print("\n[FATAL] geopandas required")
            return 1

        # ---------------- travel times ----------------
        if not (A_CSV.exists() and B_CSV.exists()):
            print("\n[FATAL] travel time files missing")
            return 1
        A = pd.read_csv(A_CSV)
        B = pd.read_csv(B_CSV)
        for d in (A, B):
            d[TIME] = pd.to_numeric(d[TIME], errors="coerce").replace([np.inf, -np.inf], np.nan)

        rule("ABSTRACT / SECTION 4.2 — TABLE 4  province-level travel time")
        a, b = A[TIME].dropna(), B[TIME].dropna()
        rows = [
            ("Median travel time (min)", a.median(), b.median()),
            ("75th percentile (min)", a.quantile(.75), b.quantile(.75)),
            ("90th percentile (min)", a.quantile(.90), b.quantile(.90)),
            ("95th percentile (min)", a.quantile(.95), b.quantile(.95)),
            ("Maximum (min)", a.max(), b.max()),
            ("Mean (min)", a.mean(), b.mean()),
        ]
        print(f"{'Measure':<34}{'Scenario A':>12}{'Scenario B':>12}{'Factor':>10}")
        print("-" * 68)
        for lab, x, y in rows:
            f = x / y if y else float("nan")
            print(f"{lab:<34}{x:>12.1f}{y:>12.1f}{f:>10.2f}")
        for t in (30, 60, 120):
            pa = (a > t).mean() * 100
            pb = (b > t).mean() * 100
            f = pa / pb if pb else float("inf")
            print(f"{'Villages over ' + str(t) + ' min (%)':<34}{pa:>12.1f}{pb:>12.1f}{f:>10.2f}")

        # ---------------- population weighted ----------------
        if POP.exists() and VID in A.columns and VID in B.columns:
            P = pd.read_csv(POP)
            pcol = next((c for c in P.columns if c.lower() in
                         ("pop_sum", "population", "pop", "people")), None)
            if pcol:
                j = (A[[VID, TIME]].merge(B[[VID, TIME]], on=VID, suffixes=("_A", "_B"))
                     .merge(P[[VID, pcol]], on=VID).dropna())
                rule("ABSTRACT / SECTION 4.3 — population-weighted results")
                print(f"Villages with population data : {len(j):,}")
                print(f"Total population covered      : {j[pcol].sum()/1e6:.1f} million")
                wa = wmedian(j[TIME + "_A"], j[pcol])
                wb = wmedian(j[TIME + "_B"], j[pcol])
                print(f"Population-weighted median A  : {wa:.1f} min")
                print(f"Population-weighted median B  : {wb:.1f} min")
                print(f"Overstatement factor          : {wa/wb:.2f}x")
                print()
                print(f"{'Threshold':<18}{'Scenario A':>16}{'Scenario B':>16}{'Factor':>10}")
                print("-" * 60)
                for t in (30, 60, 120):
                    ma = j.loc[j[TIME + "_A"] > t, pcol].sum() / 1e6
                    mb = j.loc[j[TIME + "_B"] > t, pcol].sum() / 1e6
                    f = ma / mb if mb else float("inf")
                    print(f"{'over ' + str(t) + ' min':<18}{ma:>13.2f} M{mb:>13.2f} M{f:>10.1f}")

                # robustness
                rule("SECTION 4.2 — robustness of the overstatement factor")
                allr = j[TIME + "_A"].median() / j[TIME + "_B"].median()
                k = j[j[TIME + "_B"] > 0]
                m = j[j[TIME + "_B"] >= 1]
                print(f"all villages           : {allr:.2f}x  (n={len(j):,})")
                print(f"excluding B zeros      : "
                      f"{k[TIME+'_A'].median()/k[TIME+'_B'].median():.2f}x  (n={len(k):,})")
                print(f"excluding B under 1min : "
                      f"{m[TIME+'_A'].median()/m[TIME+'_B'].median():.2f}x  (n={len(m):,})")

                rule("SECTION 6 — degenerate and anomalous cases")
                nz = int((j[TIME + "_B"] <= 0).sum())
                print(f"Villages at 0 min under B  : {nz:,}  ({nz/len(j):.1%})")
                slower = j[j[TIME + "_B"] > j[TIME + "_A"] + 0.01]
                if len(slower):
                    d = slower[TIME + "_B"] - slower[TIME + "_A"]
                    print(f"Villages slower under B    : {len(slower):,}  "
                          f"({len(slower)/len(j):.1%})")
                    print(f"  median increase          : +{d.median():.1f} min")
                    print(f"  maximum increase         : +{d.max():.1f} min")

                # district ranks
                from scipy.stats import spearmanr
                rule("SECTION 4.4 — district rank correlation")
                g = j.copy()
                if "district" in A.columns:
                    g = g.merge(A[[VID, "district"]], on=VID, how="left")
                    dd = g.groupby("district").agg(
                        n=(TIME + "_A", "size"),
                        A=(TIME + "_A", "median"), B=(TIME + "_B", "median"))
                    r_all = spearmanr(dd.A, dd.B)
                    big = dd[dd.n >= 10]
                    r_big = spearmanr(big.A, big.B)
                    print(f"all districts (n={len(dd)})      : rho={r_all[0]:.3f}  p={r_all[1]:.2g}")
                    print(f"districts with >=10 villages (n={len(big)}) : "
                          f"rho={r_big[0]:.3f}  p={r_big[1]:.2g}")
                    dd["rA"] = dd.A.rank(); dd["rB"] = dd.B.rank()
                    dd["rank_shift"] = (dd["rA"] - dd["rB"]).abs()
                    print(f"largest rank shift            : {dd['rank_shift'].max():.0f} places "
                          f"({dd['rank_shift'].idxmax()})")

        # ---------------- facilities ----------------
        rule("SECTION 4.1 — facility counts")
        if FAC_A.exists() and FAC_B.exists():
            fa, fb = gpd.read_file(FAC_A), gpd.read_file(FAC_B)
            print(f"Scenario A facilities : {len(fa):,}")
            print(f"Scenario B facilities : {len(fb):,}  (+{100*(len(fb)-len(fa))/len(fa):.0f}%)")
        if PPHI_GEO.exists() and PPHI_CSV.exists():
            pg = gpd.read_file(PPHI_GEO)
            pc = pd.read_csv(PPHI_CSV)
            print(f"PPHI register total   : {len(pc):,}")
            print(f"PPHI geocoded         : {len(pg):,}  ({len(pg)/len(pc):.1%})")
        if FAC_B.exists() and "source" in gpd.read_file(FAC_B).columns:
            fb = gpd.read_file(FAC_B)
            print(f"By source             : {fb['source'].value_counts().to_dict()}")

        # overlap
        if FAC_A.exists() and PPHI_GEO.exists():
            try:
                old = gpd.read_file(FAC_A).to_crs(32642)
                new = gpd.read_file(PPHI_GEO).to_crs(32642).reset_index(drop=True)
                near = gpd.sjoin_nearest(new, old[["geometry"]], how="left",
                                         max_distance=250, distance_col="_d")
                near = near[~near.index.duplicated(keep="first")]
                n_ov = int(near["_d"].notna().sum())
                print(f"PPHI within 250 m of open data : {n_ov:,} of {len(new):,} "
                      f"({n_ov/len(new):.1%})   <- the 'near-disjoint' figure")
            except Exception as e:
                print(f"[overlap check failed] {e}")

        if SUMMARY.exists():
            rule("SECTION 4.1 — TABLE 3  facilities per district")
            s = pd.read_csv(SUMMARY)
            idc = s.columns[0]
            if {"open_data", "pphi_geocoded"}.issubset(s.columns):
                s["TOTAL"] = s["open_data"] + s["pphi_geocoded"]
                s["multiplier"] = (s["TOTAL"] / s["open_data"].replace(0, np.nan)).round(1)
            if PPHI_CSV.exists():
                pc = pd.read_csv(PPHI_CSV)
                cw = DATA / "district_crosswalk.csv"
                mapping = {}
                if cw.exists():
                    c = pd.read_csv(cw)
                    mapping = dict(zip(c["pphi_name"], c["gadm_name"]))
                reg = pc["district"].replace(mapping).value_counts().rename("register_total")
                s = s.merge(reg, left_on=idc, right_index=True, how="left")
            print(s.sort_values("multiplier", ascending=False).to_string(index=False))
            print()
            print("NOTE: the `multiplier` printed here is authoritative. If Figure 2's")
            print("      annotations disagree, regenerate the figure — do not edit the table.")

        # ---------------- district scores ----------------
        if SCORES_A.exists() and SCORES_B.exists():
            rule("SECTION 4.4 — underservice burden, top districts")
            sa, sb = pd.read_csv(SCORES_A), pd.read_csv(SCORES_B)
            k = "underservice_burden"
            dc = "district"
            if k in sa.columns and k in sb.columns:
                m = (sa[[dc, k, "villages"]].rename(columns={k: "burden_A"})
                     .merge(sb[[dc, k]].rename(columns={k: "burden_B"}), on=dc))
                m = m[m.villages >= 10]
                m["rank_A"] = m.burden_A.rank(ascending=False)
                m["rank_B"] = m.burden_B.rank(ascending=False)
                m["shift"] = (m.rank_A - m.rank_B).abs()
                print(m.sort_values("rank_A").round(0).to_string(index=False))
                print()
                topA = m.loc[m.rank_A.idxmin(), dc]
                topB = m.loc[m.rank_B.idxmin(), dc]
                print(f"Highest burden under A : {topA}")
                print(f"Highest burden under B : {topB}")
                print(f"  -> identity changes  : {'YES' if topA != topB else 'NO'}")

        # ---------------- layer audit ----------------
        if AUDIT.exists():
            rule("SECTION 6 — village layer density spread")
            au = pd.read_csv(AUDIT)
            if "villages_per_1000km2" in au.columns:
                d = au.loc[au.villages > 0, "villages_per_1000km2"]
                print(f"range      : {d.min():.1f} to {d.max():.1f} per 1,000 km2")
                print(f"fold spread: {d.max()/max(d.min(),1e-9):.0f}-fold")
                print(f"median     : {d.median():.1f}")

        # ---------------- circularity ----------------
        if CIRC.exists():
            rule("SECTION 4.5 — circularity check")
            txt = CIRC.read_text(encoding="utf-8", errors="ignore")
            if "# correlations" in txt:
                tail = txt.split("# correlations", 1)[1].strip()
                print(pd.read_csv(io.StringIO(tail)).to_string(index=False))
            else:
                print("(correlation block not found in file — rerun rhai_14)")

        # ---------------- validation ----------------
        if VALID.exists():
            rule("SECTION 4.6 — satellite validation")
            v = gpd.read_file(VALID)
            if "verdict" in v.columns:
                v["verdict"] = v["verdict"].fillna("").astype(str).str.strip().str.lower()
                v = v[v.verdict != ""]
                yes = int((v.verdict == "yes").sum())
                no = int((v.verdict == "no").sum())
                unc = int((v.verdict == "unclear").sum())
                n, clear = len(v), yes + no
                print(f"scored: {n}   yes {yes}   no {no}   unclear {unc}")
                if clear:
                    lo, hi = wilson(yes, clear)
                    print(f"among clear verdicts : {yes}/{clear} = {yes/clear:.1%} "
                          f"(95% CI {lo:.1%}-{hi:.1%})")
                lo2, hi2 = wilson(yes, n)
                print(f"conservative         : {yes}/{n} = {yes/n:.1%} "
                      f"(95% CI {lo2:.1%}-{hi2:.1%})   <- headline")

        rule("UNVERIFIED IN THE MANUSCRIPT — check or remove")
        print("""  These appear in the text but are NOT produced by any pipeline output.
  Confirm each from its source or delete the claim.

  1. Figure 1 embedded footnote reads 3.1%; the overlap figure above is the
     correct one. Fix the caption string in rhai_17_figures.py and regenerate.

  2. Seven references could not be verified against the published articles:
     Falchetta et al. (2020), Friesen et al. (2025), Iqbal et al. (2025),
     Nardi et al. (2021), Singh & Kumar (2023), Wang & Xu (2024), Ali et al.
     (2019). Author lists and DOIs were assembled from search results, not
     from the papers. Open each DOI and confirm authors, year, volume, pages.
     A fabricated reference is a more serious finding than any similarity score.

  3. Independent routing validation (Shah Bandar, 103.8 min model vs 101 min
     observed) is a single manual check and is not reproduced by any script.

  4. The claim that 23% of OSM place names in Sindh are Urdu script derives
     from an intermediate run. Recompute it if it stays in the paper.

  5. Declarations contain no AI-use statement. Most journals and HEC now
     require disclosure where drafting assistance was used.""")

    text = buf.getvalue()
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\nWrote {OUT}")
    print("Attach this to the submission, or paste it when asking for a numbers check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
