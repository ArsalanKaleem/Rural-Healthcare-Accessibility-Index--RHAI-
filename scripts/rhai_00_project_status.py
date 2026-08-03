#!/usr/bin/env python
"""
rhai_00_project_status.py — Inspect the whole project and report progress.

Read-only. Scans scripts/ and data/, checks which pipeline stages have produced their
outputs, computes headline numbers from whatever exists, and writes a progress figure.

    python scripts/rhai_00_project_status.py

Outputs
    figures/rhai_progress.png       progress figure
    data/rhai_status_report.txt     the same report as text

Safe to run any time. Nothing is modified.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCRIPTS = ROOT / "scripts"
FIGURES = ROOT / "figures"

REPORT_TXT = DATA / "rhai_status_report.txt"
FIG_PNG = FIGURES / "rhai_progress.png"

# ---------------------------------------------------------------------------
# Pipeline definition: (stage label, script, expected outputs, phase)
# An output listed as None means the stage has no file artefact.
# ---------------------------------------------------------------------------
PIPELINE = [
    ("Pilot district (Thatta)",      "rhai_01_setup_thatta.py",              ["test_villages.gpkg"],            "Build"),
    ("First router",                 "rhai_02_route.py",                     ["test_traveltimes.csv"],          "Build"),
    ("Facility tiering",             "rhai_03b_facilities_honest_tiers.py",  ["facilities_tiered.gpkg"],        "Build"),
    ("Single-district router",       "rhai_04_route_final.py",               [],                                "Build"),
    ("Province router",              "rhai_05_route_by_district.py",         ["district_results"],              "Build"),
    ("Coverage audit + stitch",      "rhai_06_check_coverage.py",            ["rhai_traveltimes.csv"],          "Analyse"),
    ("Scoring + sensitivity",        "rhai_07_score.py",                     ["rhai_village_scores.csv",
                                                                             "rhai_district_scores.csv",
                                                                             "rhai_sensitivity.csv"],           "Analyse"),
    ("Layer bias audit",             "rhai_08_layer_audit.py",               ["rhai_layer_audit.csv"],          "Analyse"),
    ("OSM name sweep",               "rhai_09b_shp_name_sweep.py",           ["shp_name_sweep.gpkg"],           "Analyse"),
    ("PPHI PDF parse",               "rhai_10_parse_pphi.py",                ["pphi_facilities.csv",
                                                                             "pphi_district_counts.csv"],       "Denominator"),
    ("PPHI geocode",                 "rhai_11_geocode_pphi.py",              ["pphi_geocoded.gpkg"],            "Denominator"),
]

# Manual checkpoints — things no script can verify. Detected by the presence of a
# file you create when you finish the task.
CHECKPOINTS = [
    ("Review 80-89 geocode band",    ["pphi_geocode_review_done.csv"],                  "Validate"),
    ("Satellite validation (n=50)",  ["geocode_satellite_validation.csv"],              "Validate"),
    ("Circularity check",            ["rhai_circularity_check.csv"],                    "Validate"),
    ("District name crosswalk",      ["district_crosswalk.csv"],                        "Validate"),
    ("Population data present",      ["village_population.csv"],                        "Validate"),
    ("Merged facility layer",        ["facilities_merged_final.gpkg"],                  "Experiment"),
    ("Scenario B reroute",           ["rhai_traveltimes_scenarioB.csv"],                "Experiment"),
    ("Scenario A vs B comparison",   ["rhai_scenario_comparison.csv"],                  "Experiment"),
    ("Figures produced",             ["../figures/fig1_coverage_gap.png"],              "Write-up"),
    ("Paper draft",                  ["../paper/draft.md", "../paper/draft.docx"],      "Write-up"),
]

PHASE_ORDER = ["Build", "Analyse", "Denominator", "Validate", "Experiment", "Write-up"]


def exists(name: str) -> bool:
    p = (DATA / name).resolve()
    return p.exists()


def any_exists(names: list[str]) -> bool:
    return any(exists(n) for n in names)


def fmt_size(p: Path) -> str:
    if not p.exists():
        return "-"
    if p.is_dir():
        n = len(list(p.glob("*")))
        return f"{n} files"
    mb = p.stat().st_size / 1e6
    return f"{mb:.1f} MB" if mb >= 1 else f"{p.stat().st_size/1e3:.0f} KB"


def headline_numbers() -> dict:
    """Pull real numbers from whatever outputs exist."""
    out = {}

    tt = DATA / "rhai_traveltimes.csv"
    if tt.exists():
        try:
            df = pd.read_csv(tt)
            out["villages_routed"] = len(df)
            col = next((c for c in ("min_any",) if c in df.columns), None)
            if col:
                s = pd.to_numeric(df[col], errors="coerce").dropna()
                out["median_min"] = round(float(s.median()), 1)
                out["p90_min"] = round(float(s.quantile(0.9)), 1)
            if "district" in df.columns:
                out["districts_routed"] = int(df["district"].nunique())
        except Exception:
            pass

    dr = DATA / "district_results"
    if dr.exists():
        out["district_csvs"] = len(list(dr.glob("*.csv")))

    pf = DATA / "pphi_facilities.csv"
    if pf.exists():
        try:
            df = pd.read_csv(pf)
            out["pphi_facilities"] = len(df)
            if "district" in df.columns:
                out["pphi_districts"] = int(df["district"].nunique())
        except Exception:
            pass

    for name, key in (("pphi_geocoded.gpkg", "geocoded"),
                      ("pphi_geocode_review.csv", "geocode_review"),
                      ("pphi_unmatched.csv", "geocode_unmatched")):
        p = DATA / name
        if not p.exists():
            continue
        try:
            if name.endswith(".gpkg"):
                import geopandas as gpd
                out[key] = len(gpd.read_file(p))
            else:
                out[key] = len(pd.read_csv(p))
        except Exception:
            pass

    if "geocoded" in out and "pphi_facilities" in out and out["pphi_facilities"]:
        out["geocode_rate"] = round(out["geocoded"] / out["pphi_facilities"] * 100, 1)

    la = DATA / "rhai_layer_audit.csv"
    if la.exists():
        try:
            df = pd.read_csv(la)
            if "villages_per_1000km2" in df.columns:
                d = df.loc[df["villages"] > 0, "villages_per_1000km2"]
                if len(d):
                    out["density_spread"] = f"{d.min():.1f}-{d.max():.1f} per 1000km2"
                    out["density_fold"] = int(d.max() / max(d.min(), 1e-9))
            if "facilities" in df.columns:
                out["open_facilities"] = int(df["facilities"].sum())
        except Exception:
            pass

    return out


def build_report() -> tuple[str, list, list]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        print("=" * 78)
        print("RHAI PROJECT STATUS")
        print(f"Generated {datetime.now():%Y-%m-%d %H:%M}")
        print("=" * 78)
        print()

        # ---- pipeline ----
        print("PIPELINE")
        print("-" * 78)
        print(f"{'Stage':<32} {'Script':<8} {'Output':<8} {'Size':<12} {'Phase'}")
        print("-" * 78)
        rows = []
        for label, script, outputs, phase in PIPELINE:
            has_script = (SCRIPTS / script).exists()
            has_output = any_exists(outputs) if outputs else has_script
            size = ""
            for o in outputs:
                p = DATA / o
                if p.exists():
                    size = fmt_size(p)
                    break
            print(f"{label:<32} {'yes' if has_script else 'NO':<8} "
                  f"{'yes' if has_output else 'no':<8} {size:<12} {phase}")
            rows.append((label, phase, has_script and has_output))
        print()

        # ---- checkpoints ----
        print("MANUAL CHECKPOINTS  (no script can verify these)")
        print("-" * 78)
        cps = []
        for label, markers, phase in CHECKPOINTS:
            done = any_exists(markers)
            print(f"  [{'x' if done else ' '}] {label:<40} {phase}")
            cps.append((label, phase, done))
        print()
        print("  Create the marker file when a task is finished so this script")
        print("  can see it. Expected filenames are listed in CHECKPOINTS at the")
        print("  top of this script.")
        print()

        # ---- numbers ----
        n = headline_numbers()
        if n:
            print("HEADLINE NUMBERS  (computed from files present)")
            print("-" * 78)
            label_map = [
                ("villages_routed", "Villages routed"),
                ("districts_routed", "Districts in stitched output"),
                ("district_csvs", "District result CSVs"),
                ("median_min", "Median travel time (min)"),
                ("p90_min", "p90 travel time (min)"),
                ("open_facilities", "Facilities in open data"),
                ("pphi_facilities", "Facilities in PPHI lists"),
                ("pphi_districts", "PPHI districts"),
                ("geocoded", "PPHI facilities geocoded"),
                ("geocode_rate", "Geocode success rate (%)"),
                ("geocode_review", "Awaiting manual review"),
                ("geocode_unmatched", "Geocode failures"),
                ("density_spread", "Village density range"),
                ("density_fold", "Density spread (fold)"),
            ]
            for k, lab in label_map:
                if k in n:
                    print(f"  {lab:<34} {n[k]}")
            print()

            if "open_facilities" in n and "pphi_facilities" in n:
                print("  NOTE: open-data facility count includes ~2,246 in Karachi.")
                print("        The rural comparison is the one that matters — see")
                print("        pphi_district_counts.csv against rhai_layer_audit.csv.")
                print()

        # ---- progress ----
        all_items = rows + cps
        done_n = sum(1 for _, _, d in all_items if d)
        print("PROGRESS")
        print("-" * 78)
        for phase in PHASE_ORDER:
            items = [(l, d) for l, p, d in all_items if p == phase]
            if not items:
                continue
            d = sum(1 for _, x in items if x)
            bar = "#" * int(20 * d / len(items)) + "." * (20 - int(20 * d / len(items)))
            print(f"  {phase:<13} [{bar}] {d}/{len(items)}")
        pct = 100 * done_n / len(all_items)
        bar = "#" * int(20 * done_n / len(all_items)) + "." * (20 - int(20 * done_n / len(all_items)))
        print(f"  {'OVERALL':<13} [{bar}] {done_n}/{len(all_items)}  ({pct:.0f}%)")
        print()

        # ---- next actions ----
        print("NEXT ACTIONS")
        print("-" * 78)
        todo = [(l, p) for l, p, d in all_items if not d]
        if not todo:
            print("  Nothing outstanding. Write the paper.")
        else:
            for l, p in todo[:6]:
                print(f"  - [{p}] {l}")
            if len(todo) > 6:
                print(f"  ... and {len(todo) - 6} more")
        print()

        print("KNOWN ISSUES — carry these forward")
        print("-" * 78)
        print("  - rhai_09b name sweep searched a `name` column that is ~23% Urdu")
        print("    script. Its result is INVALID. Rerun against name:en / name:ur")
        print("    before making any claim about OSM facility coverage.")
        print("  - District names differ between PPHI and GADM (Tharparkar/Mithi,")
        print("    Kamber/Qambar, Naushero Feroze/Naushahro Firoz, and others).")
        print("    Joins will silently drop rows without a crosswalk.")
        print("  - Districts with <10 villages cannot support a district statistic.")
        print("  - ED (n~46) and USK (n=3) PPHI facility codes are unconfirmed.")
        print()

    return buf.getvalue(), rows, cps


def make_figure(rows: list, cps: list) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch
    except ImportError:
        print("[WARN] matplotlib not installed — skipping figure.")
        print("       pip install matplotlib --break-system-packages")
        return False

    all_items = rows + cps
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 12), gridspec_kw={"height_ratios": [1, 3]})

    # --- top: phase completion ---
    phases, done, total = [], [], []
    for ph in PHASE_ORDER:
        items = [d for _, p, d in all_items if p == ph]
        if not items:
            continue
        phases.append(ph)
        done.append(sum(items))
        total.append(len(items))

    y = range(len(phases))
    ax1.barh(list(y), total, color="#e8e8e8", edgecolor="#cccccc")
    ax1.barh(list(y), done, color="#2b7a4b")
    ax1.set_yticks(list(y))
    ax1.set_yticklabels(phases)
    ax1.invert_yaxis()
    ax1.set_xlabel("tasks complete")
    overall_d, overall_t = sum(done), sum(total)
    ax1.set_title(f"RHAI progress by phase — {overall_d}/{overall_t} "
                  f"({100*overall_d/overall_t:.0f}%)  ·  {datetime.now():%Y-%m-%d}",
                  fontsize=13, weight="bold", loc="left")
    for i, (d, t) in enumerate(zip(done, total)):
        ax1.text(t + 0.1, i, f"{d}/{t}", va="center", fontsize=9, color="#555555")
    ax1.set_xlim(0, max(total) + 1.2)
    for s in ("top", "right"):
        ax1.spines[s].set_visible(False)

    # --- bottom: task checklist ---
    labels = [f"{l}" for l, _, _ in all_items]
    states = [d for _, _, d in all_items]
    phase_of = [p for _, p, _ in all_items]
    colors = {"Build": "#2b7a4b", "Analyse": "#2b7a4b", "Denominator": "#2b7a4b",
              "Validate": "#c46a1f", "Experiment": "#c46a1f", "Write-up": "#8a2f4b"}

    yy = range(len(labels))
    ax2.barh(list(yy), [1] * len(labels), color="#f2f2f2", edgecolor="#e0e0e0")
    ax2.barh(list(yy), [1 if s else 0 for s in states],
             color=[colors[p] for p in phase_of])
    ax2.set_yticks(list(yy))
    ax2.set_yticklabels(
        [f"{'✓' if s else '○'}  {l}" for l, s in zip(labels, states)], fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xticks([])
    ax2.set_xlim(0, 1)
    for s in ("top", "right", "bottom"):
        ax2.spines[s].set_visible(False)
    ax2.set_title("Task detail", fontsize=11, loc="left", color="#444444")

    ax2.legend(handles=[Patch(color="#2b7a4b", label="Pipeline"),
                        Patch(color="#c46a1f", label="Validation / experiment"),
                        Patch(color="#8a2f4b", label="Write-up"),
                        Patch(color="#f2f2f2", label="Not done")],
               loc="lower right", frameon=False, fontsize=9)

    plt.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def main() -> int:
    report, rows, cps = build_report()
    print(report)

    DATA.mkdir(parents=True, exist_ok=True)
    REPORT_TXT.write_text(report, encoding="utf-8")
    print(f"Report -> {REPORT_TXT}")

    if make_figure(rows, cps):
        print(f"Figure -> {FIG_PNG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())