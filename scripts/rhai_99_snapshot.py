#!/usr/bin/env python
"""
rhai_99_snapshot.py — Dump a compact, shareable summary of the whole project state.

Produces ONE text file describing every data file, its shape, columns, key value
counts, and the current headline numbers. Paste it into a chat to bring someone
(or a fresh session) fully up to speed without uploading data.

    python scripts/rhai_99_snapshot.py

Output
    data/rhai_snapshot.txt

PRIVACY: writes column names, dtypes, aggregate statistics and a few example values
per column. It does not dump full tables. Facility and place names may appear in the
example values — these are public data from PPHI, GeoNames and OSM, but glance at the
file before sharing.
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
OUT = DATA / "rhai_snapshot.txt"

MAX_EXAMPLES = 3
MAX_VALUE_COUNTS = 12
SKIP_COLS = {"geometry"}

# Columns worth a full value-count rather than just examples.
CATEGORICAL_HINTS = {"district", "district_gadm", "tier", "hf_type", "hf_code",
                     "match_status", "gaz_source", "source", "match_scope",
                     "region", "district_exact", "district_ok", "type_confirmed",
                     "access_band", "landed_in", "layer", "match_label"}


def describe_table(df: pd.DataFrame, name: str) -> None:
    print(f"\n  shape: {df.shape[0]:,} rows x {df.shape[1]} cols")
    print(f"  columns:")
    for c in df.columns:
        if c in SKIP_COLS:
            print(f"    - {c:<28} (geometry)")
            continue
        s = df[c]
        dt = str(s.dtype)
        nn = s.notna().sum()
        line = f"    - {c:<28} {dt:<10} non-null {nn:,}/{len(s):,}"
        if pd.api.types.is_numeric_dtype(s) and nn:
            line += (f"  min {s.min():.4g}  med {s.median():.4g}  max {s.max():.4g}")
        print(line)
        if c.lower() in CATEGORICAL_HINTS and nn:
            vc = s.value_counts().head(MAX_VALUE_COUNTS)
            if len(vc) <= MAX_VALUE_COUNTS:
                print(f"        values: "
                      + ", ".join(f"{k}={v}" for k, v in vc.items()))
            else:
                print(f"        top {MAX_VALUE_COUNTS}: "
                      + ", ".join(f"{k}={v}" for k, v in vc.items()))
        elif s.dtype == object and nn:
            ex = s.dropna().astype(str).unique()[:MAX_EXAMPLES]
            print(f"        e.g. {' | '.join(x[:40] for x in ex)}")


def main() -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        print("=" * 78)
        print("RHAI PROJECT SNAPSHOT")
        print(f"Generated {datetime.now():%Y-%m-%d %H:%M}")
        print("=" * 78)

        # ---- scripts -------------------------------------------------------
        print("\n\nSCRIPTS")
        print("-" * 78)
        if SCRIPTS.exists():
            for p in sorted(SCRIPTS.glob("*.py")):
                lines = sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
                print(f"  {p.name:<42} {lines:>5} lines")
        else:
            print("  scripts/ not found")

        # ---- figures -------------------------------------------------------
        print("\n\nFIGURES")
        print("-" * 78)
        if FIGURES.exists():
            figs = sorted(FIGURES.glob("*"))
            for p in figs:
                print(f"  {p.name:<42} {p.stat().st_size/1e3:>8.0f} KB")
            if not figs:
                print("  (none)")
        else:
            print("  figures/ not found")

        # ---- data files ----------------------------------------------------
        print("\n\nDATA FILES")
        print("-" * 78)
        if not DATA.exists():
            print("  data/ not found")
        else:
            for p in sorted(DATA.iterdir()):
                if p.is_dir():
                    n = len(list(p.glob("*")))
                    print(f"\n[DIR ] {p.name}  ({n} files)")
                    if p.name == "district_results":
                        csvs = sorted(p.glob("*.csv"))
                        print(f"       {', '.join(c.stem for c in csvs)}")
                        if csvs:
                            try:
                                d0 = pd.read_csv(csvs[0], nrows=0)
                                print(f"       columns: {list(d0.columns)}")
                                tot = sum(sum(1 for _ in c.open(encoding='utf-8',
                                                                errors='ignore')) - 1
                                          for c in csvs)
                                print(f"       total data rows across files: {tot:,}")
                            except Exception as e:
                                print(f"       [unreadable] {e}")
                    continue

                size = p.stat().st_size
                sz = f"{size/1e6:.1f} MB" if size >= 1e6 else f"{size/1e3:.0f} KB"
                print(f"\n[FILE] {p.name}  ({sz})")

                try:
                    if p.suffix.lower() == ".csv":
                        df = pd.read_csv(p, low_memory=False)
                        describe_table(df, p.name)
                    elif p.suffix.lower() == ".gpkg":
                        import geopandas as gpd
                        g = gpd.read_file(p)
                        print(f"  CRS: {g.crs}")
                        print(f"  geometry types: "
                              f"{g.geometry.geom_type.value_counts().to_dict()}")
                        b = g.total_bounds
                        print(f"  bounds: {b[0]:.3f}, {b[1]:.3f}, "
                              f"{b[2]:.3f}, {b[3]:.3f}")
                        describe_table(pd.DataFrame(g.drop(columns="geometry")), p.name)
                    elif p.suffix.lower() == ".shp":
                        import geopandas as gpd
                        g = gpd.read_file(p, rows=1)
                        print(f"  CRS: {g.crs}   columns: {list(g.columns)}")
                    elif p.suffix.lower() in (".txt",):
                        with p.open(encoding="utf-8", errors="ignore") as fh:
                            head = [next(fh, "") for _ in range(2)]
                        print(f"  first lines: {[h[:90] for h in head]}")
                    elif p.suffix.lower() == ".geojson":
                        import geopandas as gpd
                        g = gpd.read_file(p)
                        print(f"  {len(g):,} features, CRS {g.crs}")
                        print(f"  columns: {list(g.columns)[:20]}")
                    else:
                        print("  (not parsed)")
                except Exception as e:
                    print(f"  [could not read] {type(e).__name__}: {e}")

        # ---- key cross-tabs ------------------------------------------------
        print("\n\nKEY CROSS-TABS")
        print("-" * 78)

        try:
            pf = pd.read_csv(DATA / "pphi_facilities.csv")
            import geopandas as gpd
            gc = gpd.read_file(DATA / "pphi_geocoded.gpkg")
            t = pf.groupby("district").size().rename("pphi_total")
            g = gc.groupby("district").size().rename("geocoded")
            x = pd.concat([t, g], axis=1).fillna(0).astype(int)
            x["rate_pct"] = (x["geocoded"] / x["pphi_total"] * 100).round(1)
            print("\nPPHI facilities vs geocoded, by district:")
            print(x.sort_values("rate_pct", ascending=False).to_string())
        except Exception as e:
            print(f"\n[skip PPHI cross-tab] {e}")

        try:
            au = pd.read_csv(DATA / "rhai_layer_audit.csv")
            keep = [c for c in ("district", "area_km2", "villages",
                                "villages_per_1000km2", "facilities",
                                "facilities_per_1000km2") if c in au.columns]
            print("\n\nLayer audit (open data), by district:")
            print(au[keep].sort_values("villages_per_1000km2",
                                       ascending=False).round(1).to_string(index=False))
        except Exception as e:
            print(f"\n[skip layer audit] {e}")

        try:
            ds = pd.read_csv(DATA / "rhai_district_scores.csv")
            print("\n\nDistrict scores (Scenario A, open data only):")
            print(ds.round(1).to_string(index=False))
        except Exception as e:
            print(f"\n[skip district scores] {e}")

        print("\n\nEND OF SNAPSHOT")

    text = buf.getvalue()
    print(text)
    OUT.write_text(text, encoding="utf-8")
    kb = OUT.stat().st_size / 1e3
    print(f"\nWrote {OUT}  ({kb:.0f} KB)")
    if kb > 200:
        print("[NOTE] Large file. If pasting into a chat, the KEY CROSS-TABS section")
        print("       at the end is usually the most useful part on its own.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
