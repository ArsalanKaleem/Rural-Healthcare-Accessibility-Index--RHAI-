#!/usr/bin/env python
"""
rhai_21_build_web.py — Prepare data files for the RHAI web tool.

Converts the analysis outputs into compact JSON the browser can load without a server.
Coordinates are rounded to four decimal places (roughly 11 m, well inside the 0-2 km
positional uncertainty of the facility layer) and only the fields the interface needs
are retained.

    python scripts/rhai_21_build_web.py

Outputs, written to docs/data/ :
    villages.json    one record per village: id, name, district, lon, lat, tA, tB, pop
    districts.json   per-district summary used by the district picker and cards
    facilities.json  facility points with source, for the optional overlay
    meta.json        headline figures and provenance, rendered in the About panel

DESIGN NOTE
    The tool is a lookup interface, not an argument. It answers "what does the model
    say about my district" for someone who already works there. That framing drives
    two decisions: Scenario B is shown by default because it is the better estimate,
    and every screen states which districts remain undercounted, because a health
    officer in Tando Allahyar must not read a green map as good news.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data"

A_CSV = DATA / "rhai_traveltimes.csv"
B_CSV = DATA / "rhai_traveltimes_scenarioB.csv"
POP = DATA / "village_population.csv"
FAC = DATA / "facilities_merged_final.gpkg"
SUMMARY = DATA / "facility_source_summary.csv"
PPHI_CSV = DATA / "pphi_facilities.csv"
CROSSWALK = DATA / "district_crosswalk.csv"

TIME = "min_any"
VID = "village_id"
PREC = 4          # decimal places for coordinates

# Districts where geocoding recovered little; their Scenario B times are upper bounds.
UNDERCOUNT_THRESHOLD = 35.0


def r(x, n=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def main() -> int:
    for f in (A_CSV, B_CSV):
        if not f.exists():
            print(f"[FATAL] {f.name} not found.")
            return 1
    try:
        import geopandas as gpd
    except ImportError:
        print("[FATAL] geopandas required")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)

    # ---------------- villages ----------------
    A = pd.read_csv(A_CSV)
    B = pd.read_csv(B_CSV)
    for d in (A, B):
        d[TIME] = pd.to_numeric(d[TIME], errors="coerce").replace([np.inf, -np.inf], np.nan)

    need = {VID, "X", "Y", "district"}
    if not need.issubset(A.columns):
        print(f"[FATAL] {A_CSV.name} needs {sorted(need)}; has {list(A.columns)}")
        return 1

    v = (A[[VID, "name", "district", "X", "Y", TIME]]
         .rename(columns={TIME: "tA"})
         .merge(B[[VID, TIME]].rename(columns={TIME: "tB"}), on=VID, how="left"))

    if POP.exists():
        P = pd.read_csv(POP)
        pcol = next((c for c in P.columns if c.lower() in
                     ("pop_sum", "population", "pop", "people")), None)
        if pcol:
            v = v.merge(P[[VID, pcol]].rename(columns={pcol: "pop"}), on=VID, how="left")
    if "pop" not in v.columns:
        v["pop"] = np.nan

    v["name"] = v["name"].fillna("").astype(str)
    print(f"[INFO] villages: {len(v):,}")

    # Compact array-of-arrays rather than array-of-objects: roughly 40% smaller,
    # and the browser rehydrates it on load.
    recs = []
    for t in v.itertuples(index=False):
        recs.append([
            int(getattr(t, VID)) if pd.notna(getattr(t, VID)) else None,
            t.name,
            t.district,
            round(float(t.X), PREC),
            round(float(t.Y), PREC),
            r(t.tA), r(t.tB),
            None if pd.isna(t.pop) else int(round(float(t.pop))),
        ])
    (OUT / "villages.json").write_text(json.dumps({
        "fields": ["id", "name", "district", "lon", "lat", "tA", "tB", "pop"],
        "rows": recs,
    }, separators=(",", ":")), encoding="utf-8")

    # ---------------- districts ----------------
    fac_summary = {}
    if SUMMARY.exists():
        s = pd.read_csv(SUMMARY)
        idc = s.columns[0]
        for t in s.itertuples(index=False):
            fac_summary[getattr(t, idc)] = {
                "open": int(getattr(t, "open_data", 0) or 0),
                "total": int(getattr(t, "TOTAL", 0) or 0),
            }

    # register totals and geocode rate, for the undercount warning
    reg, geo_rate = {}, {}
    if PPHI_CSV.exists():
        pc = pd.read_csv(PPHI_CSV)
        mapping = {}
        if CROSSWALK.exists():
            c = pd.read_csv(CROSSWALK)
            mapping = dict(zip(c["pphi_name"], c["gadm_name"]))
        reg = pc["district"].replace(mapping).value_counts().to_dict()
        gpkg = DATA / "pphi_geocoded_reviewed.gpkg"
        if gpkg.exists():
            g = gpd.read_file(gpkg)
            if "district" in g.columns:
                got = g["district"].replace(mapping).value_counts().to_dict()
                for k, tot in reg.items():
                    if tot:
                        geo_rate[k] = got.get(k, 0) / tot * 100

    rows = []
    for name, grp in v.groupby("district"):
        ta = grp["tA"].dropna()
        tb = grp["tB"].dropna()
        pop = grp["pop"].fillna(0)
        has_pop = pop.sum() > 0

        def wmed(col):
            if not has_pop:
                return r(grp[col].median())
            sub = grp[[col, "pop"]].dropna()
            if sub.empty:
                return None
            o = sub.sort_values(col)
            c = o["pop"].cumsum()
            return r(float(o[col].iloc[int(np.searchsorted(c, c.iloc[-1] / 2))]))

        def pop_over(col, t):
            if not has_pop:
                return None
            return int(grp.loc[grp[col] > t, "pop"].fillna(0).sum())

        f = fac_summary.get(name, {})
        rows.append({
            "d": name,
            "n": int(len(grp)),
            "pop": int(pop.sum()) if has_pop else None,
            "medA": r(ta.median()), "medB": r(tb.median()),
            "wmedA": wmed("tA"), "wmedB": wmed("tB"),
            "p90A": r(ta.quantile(.90)), "p90B": r(tb.quantile(.90)),
            "maxB": r(tb.max()),
            "over30A": pop_over("tA", 30), "over30B": pop_over("tB", 30),
            "over60A": pop_over("tA", 60), "over60B": pop_over("tB", 60),
            "vOver30B": int((tb > 30).sum()), "vOver60B": int((tb > 60).sum()),
            "facOpen": f.get("open"), "facTotal": f.get("total"),
            "regTotal": int(reg.get(name, 0)) or None,
            "geoRate": r(geo_rate.get(name), 0),
            "undercounted": bool(geo_rate.get(name, 100) < UNDERCOUNT_THRESHOLD),
        })
    rows.sort(key=lambda x: -(x["medB"] or 0))
    (OUT / "districts.json").write_text(json.dumps(rows, separators=(",", ":")),
                                        encoding="utf-8")
    print(f"[INFO] districts: {len(rows)}")
    nu = sum(1 for x in rows if x["undercounted"])
    print(f"[INFO] flagged as undercounted: {nu}")

    # ---------------- facilities ----------------
    if FAC.exists():
        g = gpd.read_file(FAC).to_crs(4326)
        poly = g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        if poly.any():
            g.loc[poly, "geometry"] = (
                g.loc[poly].to_crs(32642).geometry.centroid.to_crs(4326))
        src = g["source"] if "source" in g.columns else pd.Series(["open_data"] * len(g))
        pts = [[round(float(p.x), PREC), round(float(p.y), PREC),
                0 if s == "open_data" else 1]
               for p, s in zip(g.geometry, src)]
        (OUT / "facilities.json").write_text(json.dumps({
            "fields": ["lon", "lat", "src"], "srcNames": ["open data", "PPHI register"],
            "rows": pts,
        }, separators=(",", ":")), encoding="utf-8")
        print(f"[INFO] facilities: {len(pts):,}")

    # ---------------- meta ----------------
    ta_all = v["tA"].dropna()
    tb_all = v["tB"].dropna()
    meta = {
        "villages": int(len(v)),
        "districts": int(v["district"].nunique()),
        "medA": r(ta_all.median()), "medB": r(tb_all.median()),
        "facA": fac_summary and sum(x["open"] for x in fac_summary.values()) or None,
        "facB": fac_summary and sum(x["total"] for x in fac_summary.values()) or None,
        "note": ("Scenario B adds facilities recovered from the PPHI Sindh register. "
                 "It is the better estimate but remains an undercount: only 45.4% of "
                 "the register could be geocoded. Districts flagged as undercounted "
                 "have travel times that are upper bounds."),
        "generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")

    total = sum(f.stat().st_size for f in OUT.glob("*.json"))
    print()
    for f in sorted(OUT.glob("*.json")):
        print(f"  {f.name:<20} {f.stat().st_size/1024:>8.0f} KB")
    print(f"  {'TOTAL':<20} {total/1024:>8.0f} KB")
    print()
    print("NEXT")
    print("  1. Commit docs/ and enable GitHub Pages on the docs/ folder.")
    print("  2. Site will be at https://<user>.github.io/<repo>/")
    if total > 3_000_000:
        print("\n[WARN] over 3 MB — slow on mobile connections. Consider dropping the")
        print("       facilities layer or rounding coordinates to 3 decimal places.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
