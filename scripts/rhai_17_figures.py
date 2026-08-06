#!/usr/bin/env python
"""
rhai_17_figures.py — Generate the paper's figure set.

Produces six publication figures at 300 dpi from files already in data/.
Each figure is written independently; a missing input skips that figure rather
than aborting the run.

    python scripts/rhai_17_figures.py
    python scripts/rhai_17_figures.py --only 1 3 6     # regenerate specific ones

FIGURES
    1  Facility density, Scenario A vs B          the urban/rural bias, made visual
    2  Coverage gap by district                   PPHI listed vs open data
    3  Travel time choropleth, A vs B             the consequence, mapped
    4  Scenario comparison dumbbell               per-district medians, A vs B
    5  Population beyond time thresholds          6.95M -> 0.62M over 30 min
    6  District burden rank shift                 the ranking changes, not just the values

DESIGN NOTES
    Colour is used sparingly and consistently: Scenario A is red (#c0392b) throughout,
    Scenario B green (#2b7a4b). Sequential maps use a perceptually uniform ramp so they
    survive greyscale printing and colour-vision deficiency. No chartjunk, no 3D, no
    unnecessary gridlines — journal figures are read small.

OUTPUTS
    figures/fig1_facility_density.png
    figures/fig2_coverage_gap.png
    figures/fig3_traveltime_map.png
    figures/fig4_scenario_dumbbell.png
    figures/fig5_population_thresholds.png
    figures/fig6_rank_shift.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIGS = ROOT / "figures"

A_RED = "#c0392b"
B_GREEN = "#2b7a4b"
GREY = "#9aa0a6"
INK = "#222222"

DPI = 300


def setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 9,
        "axes.edgecolor": "#cccccc",
        "axes.linewidth": 0.8,
        "xtick.color": INK, "ytick.color": INK,
        "text.color": INK, "axes.labelcolor": INK,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "legend.frameon": False,
    })
    return plt


def save(fig, name: str, plt) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    p = FIGS / name
    fig.savefig(p, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {p.relative_to(ROOT)}")


def load_districts():
    import geopandas as gpd
    f = DATA / "gadm41_PAK_3.shp"
    if not f.exists():
        return None
    g = gpd.read_file(f)
    return (g[g["NAME_1"] == "Sindh"][["NAME_3", "geometry"]]
            .rename(columns={"NAME_3": "district"})
            .dissolve(by="district", as_index=False).to_crs(4326))


# ---------------------------------------------------------------------------
def fig1_facility_density(plt) -> None:
    """Two panels of the same province: open data, then open data + PPHI.

    This is the figure that makes the argument without numbers — the left panel is
    a dense blot over Karachi and near-empty elsewhere; the right fills in.
    """
    import geopandas as gpd
    fa, fb = DATA / "facilities_tiered.gpkg", DATA / "facilities_merged_final.gpkg"
    if not (fa.exists() and fb.exists()):
        print("  [skip] fig1: facility layers missing")
        return
    d = load_districts()
    if d is None:
        print("  [skip] fig1: GADM missing")
        return

    A = gpd.read_file(fa).to_crs(4326)
    B = gpd.read_file(fb).to_crs(4326)

    fig, axes = plt.subplots(1, 2, figsize=(10, 6.5))
    for ax, layer, title, col in (
            (axes[0], A, f"Scenario A — open data only\n{len(A):,} facilities", A_RED),
            (axes[1], B, f"Scenario B — open data + PPHI register\n{len(B):,} facilities",
             B_GREEN)):
        d.boundary.plot(ax=ax, color="#d8d8d8", linewidth=0.5, zorder=1)
        d.plot(ax=ax, color="#fafafa", zorder=0)
        layer.plot(ax=ax, color=col, markersize=3, alpha=0.55, linewidth=0, zorder=2)
        ax.set_title(title, loc="left")
        ax.set_axis_off()
        ax.set_aspect("equal")

    # Annotate the Karachi cluster on the left panel — it is the whole point.
    axes[0].annotate("Karachi:\n82% of all mapped\nfacilities in ~1%\nof the land area",
                     xy=(67.05, 24.9), xytext=(66.6, 26.6), fontsize=8,
                     color=INK,
                     arrowprops=dict(arrowstyle="->", color="#666666", lw=0.8))

    fig.suptitle("Health facility coverage in open geospatial data, Sindh",
                 fontsize=12, fontweight="bold", x=0.02, ha="left", y=0.97)
    fig.text(0.02, 0.03,
             "Open sources capture private urban clinics well and rural public "
             "primary care poorly. Only 5.2% of PPHI facilities\nfall within 250 m of "
             "any facility in the open data — the two sources describe near-disjoint "
             "sets of buildings.",
             fontsize=7.5, color="#555555")
    save(fig, "fig1_facility_density.png", plt)


def fig2_coverage_gap(plt) -> None:
    """Paired bars: what PPHI operates vs what open data records, per district."""
    f = DATA / "facility_source_summary.csv"
    pf = DATA / "pphi_district_counts.csv"
    if not f.exists():
        print("  [skip] fig2: facility_source_summary.csv missing")
        return
    s = pd.read_csv(f)
    idcol = s.columns[0]
    s = s.set_index(idcol)
    if "open_data" not in s.columns:
        print("  [skip] fig2: unexpected columns")
        return

    s = s[s["TOTAL"] > 0].sort_values("TOTAL", ascending=True)
    # Drop the Karachi metro districts: they compress the axis and are not the subject.
    drop = [i for i in s.index if str(i).lower().startswith("karachi") or i == "Malir"]
    s = s.drop(index=drop, errors="ignore")

    y = np.arange(len(s))
    h = 0.38
    fig, ax = plt.subplots(figsize=(8, max(5, 0.32 * len(s))))
    ax.barh(y + h/2, s["open_data"], height=h, color=A_RED, label="Open data (Scenario A)")
    ax.barh(y - h/2, s["TOTAL"], height=h, color=B_GREEN,
            label="Open data + PPHI (Scenario B)")
    ax.set_yticks(y)
    ax.set_yticklabels(s.index, fontsize=8)
    ax.set_xlabel("Health facilities")
    ax.set_title("Facilities recorded per district, before and after adding the "
                 "operator's register", loc="left")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="x", alpha=0.2)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)

    # Multiplier labels on the districts where the gap is largest.
    for i, (name, row) in enumerate(s.iterrows()):
        if row["open_data"] > 0:
            m = row["TOTAL"] / row["open_data"]
            if m >= 5:
                ax.text(row["TOTAL"] + 2, i, f"{m:.0f}x", va="center",
                        fontsize=7.5, color=B_GREEN, fontweight="bold")
        else:
            ax.text(row["TOTAL"] + 2, i, "from zero", va="center",
                    fontsize=7.5, color=B_GREEN, fontweight="bold")

    fig.text(0.02, -0.01,
             "Karachi metropolitan districts omitted: they gain nothing and compress "
             "the axis.",
             fontsize=7.5, color="#555555")
    save(fig, "fig2_coverage_gap.png", plt)


def fig3_traveltime_map(plt) -> None:
    """Village-level travel time, mapped under both scenarios, shared colour scale."""
    import geopandas as gpd
    import matplotlib as mpl
    a, b = DATA / "rhai_traveltimes.csv", DATA / "rhai_traveltimes_scenarioB.csv"
    if not (a.exists() and b.exists()):
        print("  [skip] fig3: travel time files missing")
        return
    d = load_districts()
    if d is None:
        print("  [skip] fig3: GADM missing")
        return

    A, B = pd.read_csv(a), pd.read_csv(b)
    for df in (A, B):
        if not {"X", "Y", "min_any"}.issubset(df.columns):
            print("  [skip] fig3: need X, Y, min_any columns")
            return

    # Shared bands so the two panels are directly comparable.
    bounds = [0, 15, 30, 60, 120, 300]
    labels = ["<15", "15–30", "30–60", "60–120", ">120"]
    cmap = mpl.colors.ListedColormap(
        ["#1a6b3c", "#7fbf7b", "#fee08b", "#f46d43", "#8c2d04"])
    norm = mpl.colors.BoundaryNorm(bounds, cmap.N)

    fig, axes = plt.subplots(1, 2, figsize=(10, 6.5))
    for ax, df, title in (
            (axes[0], A, "Scenario A — open data only"),
            (axes[1], B, "Scenario B — open data + PPHI register")):
        g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["X"], df["Y"]),
                             crs=4326)
        d.plot(ax=ax, color="#fafafa", zorder=0)
        d.boundary.plot(ax=ax, color="#d8d8d8", linewidth=0.5, zorder=1)
        g.plot(ax=ax, column="min_any", cmap=cmap, norm=norm, markersize=2.5,
               linewidth=0, zorder=2)
        med = df["min_any"].median()
        ax.set_title(f"{title}\nmedian {med:.1f} min", loc="left")
        ax.set_axis_off()
        ax.set_aspect("equal")

    sm = mpl.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, ax=axes, orientation="horizontal", fraction=0.04,
                      pad=0.04, ticks=[7.5, 22.5, 45, 90, 210])
    cb.ax.set_xticklabels(labels)
    cb.set_label("Travel time to nearest health facility (minutes)", fontsize=8)
    cb.outline.set_visible(False)

    fig.suptitle("Estimated travel time to the nearest health facility, "
                 "5,159 villages in Sindh",
                 fontsize=12, fontweight="bold", x=0.02, ha="left", y=0.98)
    save(fig, "fig3_traveltime_map.png", plt)


def fig4_dumbbell(plt) -> None:
    """District medians under both scenarios, connected."""
    f = DATA / "rhai_scenario_comparison.csv"
    if not f.exists():
        print("  [skip] fig4: rhai_scenario_comparison.csv missing")
        return
    d = pd.read_csv(f)
    dcol = "district" if "district" in d.columns else d.columns[0]
    d = d[d["villages"] >= 10].sort_values("median_A")

    fig, ax = plt.subplots(figsize=(8, max(5, 0.34 * len(d))))
    y = np.arange(len(d))
    ax.hlines(y, d["median_B"], d["median_A"], color="#d0d0d0", lw=2.2, zorder=1)
    ax.scatter(d["median_A"], y, s=46, color=A_RED, zorder=3, label="Scenario A")
    ax.scatter(d["median_B"], y, s=46, color=B_GREEN, zorder=3, label="Scenario B")
    ax.set_yticks(y)
    ax.set_yticklabels(d[dcol], fontsize=8)
    ax.set_xlabel("Median travel time to nearest health facility (minutes)")
    ax.set_title("Effect of missing facility data on estimated travel time",
                 loc="left")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="x", alpha=0.2)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    fig.text(0.02, -0.01,
             "Districts with fewer than 10 villages excluded. Larger gaps indicate "
             "districts where open-data estimates were most misleading.",
             fontsize=7.5, color="#555555")
    save(fig, "fig4_scenario_dumbbell.png", plt)


def fig5_population_thresholds(plt) -> None:
    """How many PEOPLE are beyond each time threshold, under each scenario."""
    a, b = DATA / "rhai_traveltimes.csv", DATA / "rhai_traveltimes_scenarioB.csv"
    p = DATA / "village_population.csv"
    if not (a.exists() and b.exists() and p.exists()):
        print("  [skip] fig5: inputs missing")
        return
    A = pd.read_csv(a)[["village_id", "min_any"]]
    B = pd.read_csv(b)[["village_id", "min_any"]]
    P = pd.read_csv(p)
    popcol = next((c for c in P.columns if c.lower() in
                   ("pop_sum", "population", "pop", "people")), None)
    if popcol is None:
        print("  [skip] fig5: no population column")
        return
    j = (A.merge(B, on="village_id", suffixes=("_A", "_B"))
          .merge(P[["village_id", popcol]], on="village_id").dropna())
    tot = j[popcol].sum()

    ths = [30, 60, 120]
    va = [j.loc[j["min_any_A"] > t, popcol].sum() / 1e6 for t in ths]
    vb = [j.loc[j["min_any_B"] > t, popcol].sum() / 1e6 for t in ths]

    x = np.arange(len(ths))
    w = 0.36
    fig, ax = plt.subplots(figsize=(7, 4.6))
    ax.bar(x - w/2, va, w, color=A_RED, label="Scenario A — open data only")
    ax.bar(x + w/2, vb, w, color=B_GREEN, label="Scenario B — open data + PPHI")
    for i, (u, v) in enumerate(zip(va, vb)):
        ax.text(i - w/2, u + 0.12, f"{u:.2f}M", ha="center", fontsize=8,
                color=A_RED, fontweight="bold")
        ax.text(i + w/2, v + 0.12, f"{v:.2f}M", ha="center", fontsize=8,
                color=B_GREEN, fontweight="bold")
        if u > 0:
            ax.text(i, max(u, v) + 0.55, f"{u/max(v,1e-9):.0f}x", ha="center",
                    fontsize=8.5, color="#555555")
    ax.set_xticks(x)
    ax.set_xticklabels([f"over {t} minutes" for t in ths])
    ax.set_ylabel("Population (millions)")
    ax.set_title("People estimated to live beyond each travel-time threshold",
                 loc="left")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.set_ylim(0, max(va) * 1.28)
    fig.text(0.02, -0.02,
             f"Total population covered: {tot/1e6:.1f} million across "
             f"{len(j):,} villages. Open-data-only estimates overstate the population\n"
             f"beyond 30 minutes by a factor of {va[0]/max(vb[0],1e-9):.0f}.",
             fontsize=7.5, color="#555555")
    save(fig, "fig5_population_thresholds.png", plt)


def fig6_rank_shift(plt) -> None:
    """Slope chart: district priority ranking under each scenario.

    This is the figure for the strongest claim — that open data misidentifies WHICH
    districts are worst served, not merely by how much.
    """
    fa, fb = DATA / "rhai_district_scores.csv", DATA / "rhai_district_scores_B.csv"
    if not (fa.exists() and fb.exists()):
        print("  [skip] fig6: district score files missing "
              "(run rhai_07 and rhai_07b)")
        return
    A, B = pd.read_csv(fa), pd.read_csv(fb)
    key = "underservice_burden"
    if key not in A.columns or key not in B.columns:
        print("  [skip] fig6: no underservice_burden column")
        return
    dcol = "district" if "district" in A.columns else A.columns[0]

    m = (A[[dcol, key, "villages"]].rename(columns={key: "A"})
         .merge(B[[dcol, key]].rename(columns={key: "B"}), on=dcol))
    m = m[(m["villages"] >= 10) & m["A"].notna() & m["B"].notna()]
    if m.empty:
        print("  [skip] fig6: no districts with population-weighted burden")
        return
    m["rA"] = m["A"].rank(ascending=False)
    m["rB"] = m["B"].rank(ascending=False)
    m["shift"] = (m["rA"] - m["rB"]).abs()
    m = m.sort_values("rA")

    n = len(m)
    fig, ax = plt.subplots(figsize=(7.2, max(5.5, 0.38 * n)))
    for _, r in m.iterrows():
        big = r["shift"] >= 5
        ax.plot([0, 1], [r["rA"], r["rB"]],
                color=(A_RED if big else "#d5d5d5"),
                lw=(1.8 if big else 1.0), zorder=(3 if big else 1),
                alpha=(0.95 if big else 0.8))
        ax.text(-0.03, r["rA"], f"{r[dcol]}", ha="right", va="center",
                fontsize=8, color=(INK if big else "#777777"),
                fontweight=("bold" if big else "normal"))
        ax.text(1.03, r["rB"], f"{r[dcol]}", ha="left", va="center",
                fontsize=8, color=(INK if big else "#777777"),
                fontweight=("bold" if big else "normal"))
    ax.scatter([0]*n, m["rA"], s=26, color=A_RED, zorder=4)
    ax.scatter([1]*n, m["rB"], s=26, color=B_GREEN, zorder=4)

    ax.set_xlim(-0.42, 1.42)
    ax.set_ylim(n + 0.6, 0.4)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Scenario A\nopen data only",
                        "Scenario B\nopen data + PPHI"], fontsize=9)
    ax.set_ylabel("Priority rank (1 = greatest underservice burden)")
    ax.set_title("Which districts most need investment depends on the facility data used",
                 loc="left")
    ax.grid(axis="y", alpha=0.15)
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="x", length=0)

    big = m[m["shift"] >= 5]
    fig.text(0.02, -0.015,
             "Ranked by population-weighted underservice burden. Districts shifting "
             f"5+ places highlighted ({len(big)} of {n}).\n"
             "Open-data-only analysis misidentifies which districts are worst served, "
             "not merely by how much.",
             fontsize=7.5, color="#555555")
    save(fig, "fig6_rank_shift.png", plt)


# ---------------------------------------------------------------------------
FIGURES = {
    1: ("Facility density, A vs B", fig1_facility_density),
    2: ("Coverage gap by district", fig2_coverage_gap),
    3: ("Travel time choropleth, A vs B", fig3_traveltime_map),
    4: ("Scenario dumbbell", fig4_dumbbell),
    5: ("Population beyond thresholds", fig5_population_thresholds),
    6: ("District rank shift", fig6_rank_shift),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", type=int, default=None,
                    help="figure numbers to generate, e.g. --only 1 3 6")
    args = ap.parse_args()

    try:
        plt = setup()
    except ImportError:
        print("[FATAL] pip install matplotlib --break-system-packages")
        return 1

    wanted = args.only or sorted(FIGURES)
    print("=" * 70)
    print("RHAI FIGURES")
    print("=" * 70)
    for n in wanted:
        if n not in FIGURES:
            print(f"[skip] no figure {n}")
            continue
        label, fn = FIGURES[n]
        print(f"\nFigure {n}: {label}")
        try:
            fn(plt)
        except Exception as e:  # noqa: BLE001
            print(f"  [error] {type(e).__name__}: {e}")

    print()
    print("=" * 70)
    print(f"Figures in {FIGS.relative_to(ROOT)}/")
    print("Check each at 100% zoom before submission — journal figures are read small,")
    print("and text that looks fine on screen often disappears in print.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
