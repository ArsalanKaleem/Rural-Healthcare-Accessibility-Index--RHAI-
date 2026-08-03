#!/usr/bin/env python
"""
rhai_11_geocode_pphi.py — Give the parsed PPHI facilities coordinates.

THE METHOD
    PPHI facilities are named for the settlement they sit in:
        "BHU Setharja"  ->  Setharja  ->  a populated place with known coordinates
    Strip the type prefix, fuzzy-match the remainder against gazetteers, place the
    facility at the matched settlement.

WHY GEONAMES IS THE PRIMARY SOURCE
    The Geofabrik OSM extract stores Sindh place names in URDU SCRIPT in the `name`
    column (خیرپور, سکھر, نوشہرو فیروز). PPHI facility names are Latin script, so
    matching against OSM place names is mostly impossible — it produced a 36% match
    rate and returned score 0 for towns as large as Dokri and Ratodero.

    GeoNames stores asciiname (Latin) plus an alternatenames column holding every
    known spelling variant, which is exactly what inconsistent transliteration needs
    (Ratodero/Rato Dero, Setharja/Sethar Ja). It also covers 36,472 populated places
    in Sindh against roughly 11,500 from OSM.

    OSM places are retained as a secondary source for the minority tagged in Latin.

CAVEAT — STATE THIS IN THE PAPER
    The facility is placed at the SETTLEMENT CENTROID, not the building. Positional
    error is typically 0-2 km, roughly 0-5 min at rural driving speeds. Small against
    travel times of 20-100 min, and it biases toward UNDERestimating travel time. Far
    smaller than the error from a facility being absent entirely.

INPUTS
    data/pphi_facilities.csv     from rhai_10
    data/geonames_PK.txt         from geonames.org/export/dump/PK.zip  (CC-BY 4.0 — cite it)
    data/sindh_villages.gpkg     secondary
    gis_osm_places_free_1.shp    secondary

    pip install rapidfuzz --break-system-packages

OUTPUTS
    data/pphi_geocoded.gpkg          accepted matches, ready for routing
    data/pphi_geocode_review.csv     80-89 band — MANUAL REVIEW
    data/pphi_unmatched.csv          failures, counted and reported
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PPHI_CSV = DATA / "pphi_facilities.csv"
GEONAMES = DATA / "geonames_PK.txt"
VILLAGES = DATA / "sindh_villages.gpkg"
BOUNDARY = DATA / "sindh_boundary.gpkg"
GEOFABRIK_DIR = Path(r"C:\Users\Abbasi\Desktop\pakistan-260712-free.shp")
PLACES_SHP = "gis_osm_places_free_1.shp"

OUT_GPKG = DATA / "pphi_geocoded.gpkg"
OUT_REVIEW = DATA / "pphi_geocode_review.csv"
OUT_UNMATCHED = DATA / "pphi_unmatched.csv"

METRIC_CRS = 32642
ACCEPT = 90
REVIEW = 80

SINDH_ADMIN1 = "05"

# GeoNames feature codes for actual settlements. Excludes canals, farms, offices —
# "Dokri Distributary" and "Setharja Minor" are irrigation channels, not villages.
PPL_CODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLL", "PPLS", "PPLX"}

# Type prefixes to strip. Includes ED and USK, which the first version missed —
# that alone accounted for a chunk of the unmatched rows.
PREFIX = re.compile(
    r"^\s*(B\.?H\.?U\.?|BASIC\s+HEALTH\s+UNIT"
    r"|R\.?H\.?C\.?|RURAL\s+HEALTH\s+CENT\w*"
    r"|G\.?D\.?|E\.?D\.?|U\.?S\.?K\.?|D\.?C\.?D\.?"
    r"|GOV(ERNMENT)?\s+DISPENSARY|DISPENSARY"
    r"|M\.?C\.?H\.?C?\.?(\s+CENT\w*)?|MATERNITY\s+HOME|MOTHER\s+(AND|&)\s+CHILD"
    r"|T\.?H\.?Q\.?|D\.?H\.?Q\.?|TALUKA\s+HEAD\s*QUARTER|DISTRICT\s+HEAD\s*QUARTER"
    r"|GOV(ERNMENT)?\s+HOSPITAL|CIVIL\s+HOSPITAL|HOSPITAL"
    r"|SUB\s*-?\s*HEALTH\s+CENT\w*|HEALTH\s+CENT\w*)\s*[-:,]?\s*",
    re.I,
)

# "Goth" means village/hamlet in Sindhi and appears on both sides inconsistently.
GOTH = re.compile(r"^\s*GOTH\s+|\s+GOTH\s*$", re.I)

TRAILING = re.compile(r"\s*\((.*?)\)\s*$|\s+(TALUKA|TEHSIL|DISTT?\.?|DISTRICT)\s+.*$", re.I)


def settlement_name(facility: str) -> str:
    s = str(facility).strip()
    prev = None
    while prev != s:                       # strip stacked prefixes, e.g. "BHU GD Kumb"
        prev = s
        s = PREFIX.sub("", s).strip()
    s = TRAILING.sub("", s).strip()
    s = GOTH.sub(" ", s).strip()
    return re.sub(r"\s+", " ", s)


def load_geonames() -> pd.DataFrame:
    cols = ["geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
            "feature_class", "feature_code", "country", "cc2", "admin1", "admin2",
            "admin3", "admin4", "population", "elevation", "dem", "timezone", "moddate"]
    gn = pd.read_csv(GEONAMES, sep="\t", names=cols, dtype=str, low_memory=False)
    gn = gn[(gn["feature_class"] == "P") & (gn["admin1"] == SINDH_ADMIN1)]
    gn = gn[gn["feature_code"].isin(PPL_CODES)]
    gn["population"] = pd.to_numeric(gn["population"], errors="coerce").fillna(0)

    # One row per name variant: asciiname plus every alternate spelling. This is the
    # part that handles inconsistent transliteration.
    rows = []
    for r in gn.itertuples(index=False):
        variants = {str(r.asciiname), str(r.name)}
        if isinstance(r.alternatenames, str) and r.alternatenames:
            variants.update(r.alternatenames.split(","))
        for v in variants:
            v = v.strip()
            # Latin script only — Urdu variants cannot match Latin facility names.
            if len(v) >= 3 and re.fullmatch(r"[A-Za-z0-9 .'\-]+", v):
                rows.append({"place_name": v, "lon": float(r.longitude),
                             "lat": float(r.latitude), "population": r.population,
                             "source": "geonames"})
    out = pd.DataFrame(rows)
    print(f"[gaz] geonames Sindh: {len(gn):,} places -> {len(out):,} Latin name variants")
    return out


def load_osm_places() -> pd.DataFrame | None:
    p = GEOFABRIK_DIR / PLACES_SHP
    if not p.exists():
        print(f"[gaz] {PLACES_SHP} not found — skipping")
        return None
    g = gpd.read_file(p, engine="pyogrio", where="name IS NOT NULL AND name != ''")
    g = g.to_crs(4326)
    if BOUNDARY.exists():
        sindh = gpd.read_file(BOUNDARY).to_crs(4326)
        g = gpd.sjoin(g, sindh[["geometry"]], how="inner",
                      predicate="within").drop(columns=["index_right"])
    if g.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any():
        g["geometry"] = g.to_crs(METRIC_CRS).geometry.centroid.to_crs(4326)
    latin = g["name"].astype(str).str.fullmatch(r"[A-Za-z0-9 .'\-]+", na=False)
    print(f"[gaz] osm places: {len(g):,} in Sindh, {int(latin.sum()):,} Latin-script "
          f"({1 - latin.mean():.0%} are Urdu script and unusable here)")
    g = g[latin]
    if g.empty:
        return None
    return pd.DataFrame({"place_name": g["name"].astype(str),
                         "lon": g.geometry.x, "lat": g.geometry.y,
                         "population": 0.0, "source": "osm_places"})


def load_villages() -> pd.DataFrame | None:
    if not VILLAGES.exists():
        return None
    v = gpd.read_file(VILLAGES).to_crs(4326)
    if "name" not in v.columns:
        return None
    if v.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any():
        v["geometry"] = v.to_crs(METRIC_CRS).geometry.centroid.to_crs(4326)
    v = v[v["name"].notna()]
    latin = v["name"].astype(str).str.fullmatch(r"[A-Za-z0-9 .'\-]+", na=False)
    print(f"[gaz] sindh_villages: {len(v):,} named, {int(latin.sum()):,} Latin-script")
    v = v[latin]
    if v.empty:
        return None
    pop = pd.to_numeric(v.get("population"), errors="coerce").fillna(0) \
        if "population" in v.columns else 0.0
    return pd.DataFrame({"place_name": v["name"].astype(str),
                         "lon": v.geometry.x, "lat": v.geometry.y,
                         "population": pop, "source": "villages"})


def build_gazetteer() -> pd.DataFrame:
    frames = []
    if GEONAMES.exists():
        frames.append(load_geonames())
    else:
        print(f"[gaz] {GEONAMES.name} MISSING — this is the primary source.")
        print("      Download PK.zip from geonames.org/export/dump/, extract PK.txt,")
        print("      rename to data/geonames_PK.txt. Match rate will be poor without it.")
    for f in (load_villages(), load_osm_places()):
        if f is not None:
            frames.append(f)
    if not frames:
        print("[FATAL] no gazetteer available.")
        sys.exit(1)

    gaz = pd.concat(frames, ignore_index=True)
    gaz["place_name"] = gaz["place_name"].str.strip()
    gaz = gaz[gaz["place_name"].str.len() >= 3]

    # GeoNames records the same settlement several times at slightly different
    # coordinates. Keep the highest-population instance of each name.
    gaz = (gaz.sort_values("population", ascending=False)
              .drop_duplicates(subset=["place_name"], keep="first")
              .reset_index(drop=True))
    print(f"[gaz] combined, deduplicated: {len(gaz):,} candidate names\n")
    return gaz


def main() -> int:
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        print("[FATAL] pip install rapidfuzz --break-system-packages")
        return 1

    if not PPHI_CSV.exists():
        print(f"[FATAL] {PPHI_CSV} not found. Run rhai_10_parse_pphi.py first.")
        return 1

    fac = pd.read_csv(PPHI_CSV)
    fac["settlement"] = fac["name"].map(settlement_name)

    dropped = int((fac["settlement"].str.len() < 3).sum())
    if dropped:
        print(f"[INFO] {dropped} facilities had no usable settlement name after "
              f"prefix stripping — excluded and reported as unmatched")
    fac = fac[fac["settlement"].str.len() >= 3].copy()
    print(f"[INFO] {len(fac):,} facilities to geocode\n")

    gaz = build_gazetteer()
    choices = gaz["place_name"].tolist()

    results = []
    for i, row in enumerate(fac.itertuples(index=False), start=1):
        if i % 200 == 0:
            print(f"   ...{i:,}/{len(fac):,}")
        m = process.extractOne(row.settlement, choices,
                               scorer=fuzz.token_set_ratio, score_cutoff=REVIEW)
        if m is None:
            results.append({"matched_place": None, "score": 0.0, "lon": None,
                            "lat": None, "gaz_source": None})
            continue
        _, score, idx = m
        g = gaz.iloc[idx]
        results.append({"matched_place": g["place_name"], "score": float(score),
                        "lon": float(g["lon"]), "lat": float(g["lat"]),
                        "gaz_source": g["source"]})

    fac = pd.concat([fac.reset_index(drop=True), pd.DataFrame(results)], axis=1)
    fac["match_status"] = np.select(
        [fac["score"] >= ACCEPT, fac["score"] >= REVIEW],
        ["accepted", "review"], default="unmatched")

    n_acc = int((fac["match_status"] == "accepted").sum())
    n_rev = int((fac["match_status"] == "review").sum())
    n_un = int((fac["match_status"] == "unmatched").sum())

    print()
    print("=" * 74)
    print("GEOCODING RESULTS")
    print("=" * 74)
    print(f"Facilities             : {len(fac):,}")
    print(f"Auto-accepted (>={ACCEPT})   : {n_acc:,}  ({n_acc/len(fac):.1%})")
    print(f"Needs review ({REVIEW}-{ACCEPT-1})   : {n_rev:,}  ({n_rev/len(fac):.1%})")
    print(f"Unmatched (<{REVIEW})        : {n_un:,}  ({n_un/len(fac):.1%})")
    print()
    print("By gazetteer source (accepted):")
    print(fac.loc[fac["match_status"] == "accepted", "gaz_source"]
             .value_counts().to_string())
    print()

    if "district" in fac.columns:
        by_d = (fac.assign(ok=fac["match_status"] == "accepted")
                   .groupby("district").agg(total=("ok", "size"), matched=("ok", "sum")))
        by_d["rate"] = (by_d["matched"] / by_d["total"] * 100).round(1)
        print("Match rate by district:")
        print(by_d.sort_values("rate").to_string())
        print()

    ok = fac[(fac["match_status"] == "accepted") & fac["lon"].notna()].copy()
    if len(ok):
        gdf = gpd.GeoDataFrame(ok, geometry=gpd.points_from_xy(ok["lon"], ok["lat"]),
                               crs=4326)
        gdf["geocode_method"] = "settlement_centroid_fuzzy"
        gdf["positional_uncertainty_km"] = 2.0
        gdf.to_file(OUT_GPKG, driver="GPKG")
        print(f"Wrote {OUT_GPKG.name}: {len(gdf):,} geocoded facilities")

    fac[fac["match_status"] == "review"].to_csv(OUT_REVIEW, index=False)
    fac[fac["match_status"] == "unmatched"].to_csv(OUT_UNMATCHED, index=False)
    print(f"Wrote {OUT_REVIEW.name} ({n_rev:,}) and {OUT_UNMATCHED.name} ({n_un:,})")

    print()
    print("CHECK FOR CIRCULARITY")
    print("  Correlate per-district match rate against per-district village density")
    print("  from rhai_layer_audit.csv. If they correlate, geocoding succeeds")
    print("  preferentially in already-well-mapped districts — which is the same bias")
    print("  the paper is measuring. State it either way.")
    print()
    print("NEXT")
    print("  1. Review the 80-89 band by hand.")
    print("  2. Sample ~50 accepted matches in QGIS over satellite imagery; check a")
    print("     plausible facility building sits near each point. Report that rate.")
    print("  3. Merge into the facility layer, rerun rhai_05, compare against the")
    print("     open-data-only run. That difference is the paper's central result.")
    print()
    print("  Cite GeoNames (CC-BY 4.0) in the paper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())