#!/usr/bin/env python
"""
rhai_14_circularity_check.py — Is the correction independent of the bias?

THE QUESTION
    The paper argues open geospatial data under-represents rural health facilities.
    The correction (geocoding PPHI facility names against gazetteers) is itself derived
    from mapping data. If geocoding succeeded mainly in already-well-mapped districts,
    Scenario B fixes the districts that needed it least and carries the bias forward.

    A referee will ask. Answer with a number.

TWO REFINEMENTS OVER v1
    1. RURAL-ONLY IS PRIMARY. PPHI's Karachi facilities are named after colonies
       ("ED Junejo Colony", "ED Machar Colony"), not settlements, so name-based
       geocoding fails there for reasons of naming convention rather than data
       quality. Including them confounds urban/rural with mapping intensity.
    2. USES EXACT-CONTAINMENT MATCHES ONLY, consistent with rhai_11 v3. The looser
       12 km-buffer set is tautological (candidates were drawn from the buffered
       district, so every match passes) and must not be used as a success measure.

USAGE
    python scripts/rhai_14_circularity_check.py

OUTPUTS
    data/rhai_circularity_check.csv     per-district table plus correlations
    figures/fig_circularity.png         scatter, Karachi greyed out
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

PPHI_ALL = DATA / "pphi_facilities.csv"
GEOCODED = DATA / "pphi_geocoded.gpkg"
AUDIT = DATA / "rhai_layer_audit.csv"
CROSSWALK = DATA / "district_crosswalk.csv"

OUT_CSV = DATA / "rhai_circularity_check.csv"
OUT_FIG = FIGURES / "fig_circularity.png"

KARACHI = {"Karachi East", "Karachi West", "Karachi west", "Karachi South",
           "Karachi Central", "Malir", "Keamari", "Kemari"}

FALLBACK_CROSSWALK = {
    "Tharparkar": "Mithi", "Naushero Feroze": "Naushahro Firoz",
    "Shaheed Benazirabad": "Nawab Shah", "Jacobabad": "Jakobabad",
    "Tando Muhammad Khan": "Tando M. Khan", "Mirpurkhas": "Mirphurkhas",
    "Karachi West": "Karachi west", "Kamber": "Larkana",
    "Sujawal": "Thatta", "Keamari": "Karachi west",
}

TESTS = [
    ("villages_per_1000km2", "geocode rate vs village density"),
    ("facilities", "geocode rate vs open facility count"),
    ("facilities_per_1000km2", "geocode rate vs open facility density"),
    ("area_km2", "geocode rate vs district area"),
]


def describe(rho: float, p: float) -> str:
    if np.isnan(rho):
        return "not computable"
    s = ("negligible" if abs(rho) < 0.2 else "weak" if abs(rho) < 0.4 else
         "moderate" if abs(rho) < 0.6 else "strong")
    return f"{s}, {'significant' if p < 0.05 else 'not significant'}"


def run_tests(m: pd.DataFrame, label: str) -> list[dict]:
    print(f"\n{label}  (n = {len(m)} districts)")
    print("-" * 74)
    if len(m) < 5:
        print("  too few districts to test")
        return []
    out = []
    for col, name in TESTS:
        if col not in m.columns:
            continue
        sub = m[["geocode_rate", col]].dropna()
        if len(sub) < 5:
            continue
        rho, p = spearmanr(sub["geocode_rate"], sub[col])
        print(f"  {name:<40} rho={rho:+.3f}  p={p:.3f}   ({describe(rho, p)})")
        out.append({"sample": label, "test": name, "variable": col, "n": len(sub),
                    "spearman_rho": round(float(rho), 4),
                    "p_value": round(float(p), 4)})
    return out


def main() -> int:
    for f in (PPHI_ALL, GEOCODED, AUDIT):
        if not f.exists():
            print(f"[FATAL] {f.name} not found."
                  + ("  Run rhai_08_layer_audit.py first." if f is AUDIT else ""))
            return 1
    try:
        import geopandas as gpd
    except ImportError:
        print("[FATAL] geopandas required")
        return 1

    allf = pd.read_csv(PPHI_ALL)
    geo = gpd.read_file(GEOCODED)
    if "district" not in allf.columns or "district" not in geo.columns:
        print("[FATAL] both inputs need a district column")
        return 1

    # Use exact-containment matches only, if the flag is present.
    if "district_exact" in geo.columns:
        n_before = len(geo)
        geo = geo[geo["district_exact"].astype(str).str.lower().isin(["true", "1"])
                  | (geo["district_exact"] == True)]  # noqa: E712
        print(f"[INFO] restricted to exact-containment matches: {len(geo):,} "
              f"of {n_before:,}")
    else:
        print("[WARN] no district_exact column — using all rows in the gpkg.")
        print("       Rerun rhai_11 v3 so the containment flag is written.")

    total = allf.groupby("district").size().rename("pphi_total")
    matched = geo.groupby("district").size().rename("pphi_geocoded")
    rate = pd.concat([total, matched], axis=1).fillna(0)
    rate["geocode_rate"] = rate["pphi_geocoded"] / rate["pphi_total"] * 100
    rate.index.name = "district"
    rate = rate.reset_index()

    if CROSSWALK.exists():
        cw = pd.read_csv(CROSSWALK)
        mapping = dict(zip(cw["pphi_name"], cw["gadm_name"]))
        print(f"[INFO] using {CROSSWALK.name} ({len(mapping)} mappings)")
    else:
        mapping = FALLBACK_CROSSWALK
        print(f"[INFO] {CROSSWALK.name} not found — using built-in fallback")
    rate["district_gadm"] = rate["district"].replace(mapping)

    audit = pd.read_csv(AUDIT)

    # Districts that share a GADM target (Kamber->Larkana, Sujawal->Thatta) would each
    # inherit the same audit row; aggregate them so the unit of analysis is the GADM
    # district, not the PPHI label.
    agg = (rate.groupby("district_gadm")
               .agg(pphi_total=("pphi_total", "sum"),
                    pphi_geocoded=("pphi_geocoded", "sum"),
                    pphi_labels=("district", lambda s: "/".join(sorted(s))))
               .reset_index())
    agg["geocode_rate"] = agg["pphi_geocoded"] / agg["pphi_total"] * 100

    m = agg.merge(audit, left_on="district_gadm", right_on="district", how="inner")
    missing = sorted(set(agg["district_gadm"]) - set(audit["district"]))
    if missing:
        lost = int(agg.loc[agg["district_gadm"].isin(missing), "pphi_total"].sum())
        print(f"[WARN] {len(missing)} districts did not join: {missing}")
        print(f"       {lost} facilities excluded. Fix district_crosswalk.csv.")

    m["is_karachi"] = m["district_gadm"].isin(KARACHI) | m["pphi_labels"].isin(KARACHI)
    rural = m[~m["is_karachi"]].copy()

    print()
    print("=" * 74)
    print("CIRCULARITY CHECK")
    print("=" * 74)
    print("Does geocoding succeed preferentially in already-well-mapped districts?")

    res_rural = run_tests(rural, "RURAL DISTRICTS (primary)")
    res_all = run_tests(m, "ALL DISTRICTS (secondary, confounded)")

    print()
    print("VERDICT")
    print("-" * 74)
    prim = next((r for r in res_rural if r["variable"] == "villages_per_1000km2"), None)
    fac_t = next((r for r in res_rural if r["variable"] == "facilities"), None)
    area_t = next((r for r in res_rural if r["variable"] == "area_km2"), None)

    if prim is None:
        print("  Primary test not computable.")
    else:
        rho, p, n = prim["spearman_rho"], prim["p_value"], prim["n"]
        if abs(rho) < 0.3 or p >= 0.05:
            print("  No meaningful association among rural districts. Suggested text:")
            print()
            print('    "Among rural districts, geocoding success was not significantly')
            print(f'     associated with prior OSM mapping density (Spearman rho =')
            print(f'     {rho:+.2f}, p = {p:.2f}, n = {n}), indicating that the facility')
            print('     correction is independent of the mapping bias it addresses."')
        elif abs(rho) < 0.6:
            print(f"  Moderate association (rho={rho:+.2f}, p={p:.3f}). Disclose in")
            print("  limitations: the correction is partial and residual bias runs in")
            print("  the same direction as the original.")
        else:
            print(f"  Strong association (rho={rho:+.2f}). Scenario B corrects the")
            print("  districts needing it least. State this prominently.")

    if fac_t and fac_t["spearman_rho"] < -0.2:
        print()
        print(f"  NEGATIVE correlation with open facility count "
              f"(rho={fac_t['spearman_rho']:+.2f}, p={fac_t['p_value']:.3f}):")
        print("  geocoding worked BEST where open data was thinnest — the opposite of")
        print("  circularity. Report this explicitly.")

    if area_t and abs(area_t["spearman_rho"]) > 0.4:
        print()
        print(f"  [CHECK] geocode rate correlates with district AREA "
              f"(rho={area_t['spearman_rho']:+.2f}). Large districts have larger")
        print("  gazetteer candidate sets, so this may be a method artefact rather")
        print("  than a property of the data. Worth a sentence in limitations.")

    if len(m) > len(rural):
        print()
        print(f"  {len(m) - len(rural)} Karachi district(s) excluded from the primary")
        print("  test: PPHI's urban facilities are named after colonies, not")
        print("  settlements, so name-based geocoding fails for reasons of naming")
        print("  convention rather than data quality.")

    cols = (["district_gadm", "pphi_labels", "is_karachi", "pphi_total",
             "pphi_geocoded", "geocode_rate"]
            + [c for c in ("villages", "villages_per_1000km2", "facilities",
                           "facilities_per_1000km2", "area_km2") if c in m.columns])
    out = m[cols].sort_values("geocode_rate", ascending=False)
    out.round(2).to_csv(OUT_CSV, index=False)

    print()
    print("PER-DISTRICT")
    print("-" * 74)
    print(out.round(1).to_string(index=False))
    print()

    if res_rural or res_all:
        with open(OUT_CSV, "a", encoding="utf-8") as fh:
            fh.write("\n# correlations\n")
            pd.DataFrame(res_rural + res_all).to_csv(fh, index=False)
    print(f"Wrote {OUT_CSV.name}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return 0
    if "villages_per_1000km2" not in m.columns:
        return 0

    fig, ax = plt.subplots(figsize=(9, 6.5))
    r, k = m[~m["is_karachi"]], m[m["is_karachi"]]
    ax.scatter(r["villages_per_1000km2"], r["geocode_rate"], s=70, color="#2b7a4b",
               alpha=0.9, edgecolor="white", zorder=3, label="Rural districts")
    if len(k):
        ax.scatter(k["villages_per_1000km2"], k["geocode_rate"], s=70, color="#b0b0b0",
                   alpha=0.9, edgecolor="white", zorder=3,
                   label="Karachi (excluded — colony naming)")
    for _, row in m.iterrows():
        ax.annotate(str(row["district_gadm"]),
                    (row["villages_per_1000km2"], row["geocode_rate"]),
                    fontsize=7, xytext=(4, 3), textcoords="offset points",
                    color="#555555")
    ax.set_xlabel("Village density in OSM (villages per 1,000 km²)")
    ax.set_ylabel("PPHI geocode success rate, exact containment (%)")
    if prim:
        ax.set_title("Is the correction independent of the bias?\n"
                     f"Rural districts: Spearman rho = {prim['spearman_rho']:+.3f}, "
                     f"p = {prim['p_value']:.3f}, n = {prim['n']}",
                     fontsize=11, weight="bold", loc="left")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.grid(alpha=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    plt.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {OUT_FIG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())