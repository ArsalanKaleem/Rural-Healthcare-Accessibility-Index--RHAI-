#!/usr/bin/env python
"""
rhai_09b_shp_name_sweep.py — Name sweep over a Geofabrik shapefile extract.
STANDALONE: does not import from any other rhai script.

Finds features whose NAME identifies a health facility, regardless of whether they
carry a health tag. This catches buildings the tag-based pipeline
(amenity=hospital|clinic, healthcare=*) cannot see.

SETUP
    Set GEOFABRIK_DIR below to your extracted folder. Do not copy the 101 files
    into data/ — just set the path.
    Record the extract date (YYMMDD in the folder name) for your methods section.

PERFORMANCE
    The Pakistan buildings layer has millions of rows. This pushes the filter down to
    the OGR driver: named features only, Sindh bounding box only.
    pip install pyogrio --break-system-packages

USAGE
    python scripts/rhai_09b_shp_name_sweep.py

OUTPUTS
    data/shp_name_sweep.gpkg
    data/shp_name_sweep_review.csv   <- MANUAL REVIEW REQUIRED
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

# ----------------------------------------------------------------------------
# CONFIG — EDIT THIS PATH
# ----------------------------------------------------------------------------
GEOFABRIK_DIR = Path(r"C:\Users\Abbasi\Desktop\pakistan-260712-free.shp")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BOUNDARY = DATA / "sindh_boundary.gpkg"
EXISTING = DATA / "facilities_tiered.gpkg"

OUT_GPKG = DATA / "shp_name_sweep.gpkg"
OUT_REVIEW = DATA / "shp_name_sweep_review.csv"

METRIC_CRS = 32642        # UTM 42N — correct for Sindh
DEDUPE_METRES = 100       # points closer than this are the same facility

# Smallest layer first so you see results before the slow one runs.
LAYERS = [
    ("gis_osm_pois_free_1.shp", "poi_point"),
    ("gis_osm_pois_a_free_1.shp", "poi_polygon"),
    ("gis_osm_buildings_a_free_1.shp", "building"),
]

# ----------------------------------------------------------------------------
# MATCH RULES
# Word boundaries matter: without \b, "BHU" matches "Bhurgari" and "Bhutto".
# ----------------------------------------------------------------------------
TIER_PATTERNS = [
    (re.compile(r"\bD\.?H\.?Q\b|District\s+Head\s*quarter|Teaching\s+Hospital"
                r"|Medical\s+College\s+Hospital", re.I), "tertiary", "DHQ/teaching"),
    (re.compile(r"\bT\.?H\.?Q\b|Taluka\s+Head\s*quarter|Tehsil\s+Head\s*quarter"
                r"|Civil\s+Hospital", re.I), "secondary", "THQ/civil"),
    (re.compile(r"\bR\.?H\.?C\b|Rural\s+Health\s+Cent", re.I), "primary", "RHC"),
    (re.compile(r"\bB\.?H\.?U\b|Basic\s+Health\s+Unit", re.I), "primary", "BHU"),
    (re.compile(r"\bM\.?C\.?H\b|Mother\s+(and|&)\s+Child|Maternal\s+(and|&)\s+Child"
                r"|Maternity\s+Home", re.I), "primary", "MCH/maternity"),
    (re.compile(r"Dispensary|\bG\.?D\.?\s+|Sub\s*[- ]?Health\s+Cent"
                r"|First\s+Aid\s+Post", re.I), "primary", "dispensary"),
    (re.compile(r"\bHospital\b|\bClinic\b|Health\s+Cent|Medical\s+Cent"
                r"|Health\s+Facility", re.I), "unclassified", "generic health"),
]

EXCLUDE = re.compile(
    r"Veterinary|\bVet\b|Animal|Livestock|Poultry|Cattle"
    r"|Hospital\s+Road|Hospital\s+Chowk|Hospital\s+Stop|Hospital\s+Gate"
    r"|Pharmacy|Medical\s+Store|Chemist|Medico|Laboratory\s+Collection"
    r"|Eye\s+Glasses|Optical\s+Store"
    r"|Hostel|Colony|Quarters|Mosque|School|College\s+of",
    re.I,
)

SUSPECT = re.compile(r"\bRoad\b|\bChowk\b|\bStop\b|\bBazar\b|\bMore\b|\bMorr\b"
                     r"|\bGate\b|\bStreet\b|\bTown\b|\bColony\b", re.I)


def classify(name: str):
    """Return (matched_name, tier, label) for the first matching rule, else None."""
    for rx, tier, label in TIER_PATTERNS:
        if rx.search(name):
            return name, tier, label
    return None


# ----------------------------------------------------------------------------
def find_layer(fname: str):
    for base in (GEOFABRIK_DIR, DATA):
        p = base / fname
        if p.exists():
            return p
    return None


def read_named(path: Path, bbox):
    """Read only named features inside bbox, filtering at the driver where possible."""
    cols = ["osm_id", "code", "fclass", "name", "type"]
    try:
        g = gpd.read_file(path, engine="pyogrio", bbox=bbox,
                          where="name IS NOT NULL AND name != ''")
    except Exception as e:  # noqa: BLE001
        print(f"       [warn] driver filter unavailable ({type(e).__name__}); "
              f"full read, may be slow")
        try:
            g = gpd.read_file(path, bbox=bbox)
        except Exception as e2:  # noqa: BLE001
            print(f"       [skip] could not read: {e2}")
            return None
        if "name" in g.columns:
            g = g[g["name"].notna() & (g["name"].astype(str).str.strip() != "")]
    if "name" not in g.columns:
        print("       [skip] no name column")
        return None
    keep = [c for c in cols if c in g.columns] + ["geometry"]
    return g[keep]


def main() -> int:
    if not BOUNDARY.exists():
        print(f"[FATAL] {BOUNDARY} required for the bounding-box filter.")
        return 1

    sindh = gpd.read_file(BOUNDARY).to_crs(4326)
    bbox = tuple(sindh.total_bounds)
    print(f"[INFO] Sindh bbox : {bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}")
    print(f"[INFO] Geofabrik  : {GEOFABRIK_DIR}")
    if not GEOFABRIK_DIR.exists():
        print("       [warn] folder not found — falling back to data/")
    print()

    frames = []
    for fname, kind in LAYERS:
        path = find_layer(fname)
        if path is None:
            print(f"[skip] {fname} not found")
            continue

        print(f"[read] {fname} ({kind})")
        g = read_named(path, bbox)
        if g is None or g.empty:
            print("       no named features in bbox")
            continue
        print(f"       {len(g):,} named features in bbox")

        hits = g["name"].astype(str).map(classify)
        mask = hits.notna()
        if not mask.any():
            print("       0 name matches")
            continue

        sub = g[mask].copy()
        sub["matched_name"] = [h[0] for h in hits[mask]]
        sub["tier"] = [h[1] for h in hits[mask]]
        sub["match_label"] = [h[2] for h in hits[mask]]
        sub["layer"] = kind
        print(f"       -> {len(sub):,} name matches")
        frames.append(sub)

    if not frames:
        print("\n[FATAL] nothing matched. Check GEOFABRIK_DIR.")
        return 1

    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)

    is_poly = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if is_poly.any():
        gdf.loc[is_poly, "geometry"] = (
            gdf.loc[is_poly].to_crs(METRIC_CRS).geometry.centroid.to_crs(4326))

    before = len(gdf)
    gdf = gpd.sjoin(gdf, sindh[["geometry"]], how="inner",
                    predicate="within").drop(columns=["index_right"])
    print(f"\n[INFO] bbox -> Sindh polygon: {before:,} -> {len(gdf):,}")

    if "osm_id" in gdf.columns:
        gdf = gdf.drop_duplicates(subset=["osm_id"], keep="first")
    gdf = gdf.reset_index(drop=True)

    gdf["excluded"] = gdf["matched_name"].str.contains(EXCLUDE, na=False)
    gdf["suspect"] = gdf["matched_name"].str.contains(SUSPECT, na=False)
    gdf["needs_review"] = gdf["excluded"] | gdf["suspect"] | (gdf["tier"] == "unclassified")

    print()
    print("=" * 72)
    print("NAME SWEEP — Sindh")
    print("=" * 72)
    print(f"Name matches    : {len(gdf):,}")
    print(f"Auto-excluded   : {int(gdf['excluded'].sum()):,}")
    print(f"Flagged suspect : {int(gdf['suspect'].sum()):,}")
    print()
    print("By layer:")
    print(gdf.groupby("layer").size().to_string())
    print()
    print("By match type:")
    print(gdf.groupby(["match_label", "tier"]).size().to_string())
    print()

    accepted = gdf[~gdf["excluded"]].copy().reset_index(drop=True)

    if EXISTING.exists():
        old = gpd.read_file(EXISTING).to_crs(4326)
        if old.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any():
            old["geometry"] = old.to_crs(METRIC_CRS).geometry.centroid.to_crs(4326)
        near = gpd.sjoin_nearest(accepted.to_crs(METRIC_CRS),
                                 old.to_crs(METRIC_CRS)[["geometry"]],
                                 how="left", max_distance=DEDUPE_METRES,
                                 distance_col="_d")
        dup = set(near.loc[near["_d"].notna()].index)
        accepted["is_duplicate"] = accepted.index.isin(dup)
        n_new = int((~accepted["is_duplicate"]).sum())
        print(f"Already in facilities_tiered : {len(dup):,}")
        print(f"GENUINELY NEW FACILITIES     : {n_new:,}")
        print(f"Facility layer: {len(old):,} -> {len(old) + n_new:,}")
    else:
        accepted["is_duplicate"] = False
        print(f"[WARN] {EXISTING.name} not found — no dedupe performed")

    gdf.to_file(OUT_GPKG, driver="GPKG")
    accepted.drop(columns="geometry").to_csv(OUT_REVIEW, index=False)

    print()
    print(f"Candidates  -> {OUT_GPKG.name}")
    print(f"Review file -> {OUT_REVIEW.name}")
    print()
    print("NEXT: open the review CSV, sort by needs_review, correct by hand.")
    print("      The regex will have caught 'Hospital Road' and veterinary clinics.")
    print("      Record the false-positive rate for the methods section.")
    return 0


if __name__ == "__main__":
    sys.exit(main())