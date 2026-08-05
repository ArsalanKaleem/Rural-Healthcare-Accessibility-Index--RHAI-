#!/usr/bin/env python
"""
rhai_11_geocode_pphi.py — Geocode PPHI facilities, CONSTRAINED TO THEIR OWN DISTRICT.

WHY THIS VERSION EXISTS
    v1 matched each facility name against all of Sindh. Rural Sindhi settlements are
    named after people (Ibrahim Sihano, Mehrab Talpur, Ramzan Brohi) and those names
    recur province-wide, so an unconstrained search returned whichever identical name
    it hit first. Only 285 of 1,109 results (25.7%) landed in the right district;
    median displacement 78 km. A high name-similarity score means nothing without a
    location constraint.

    v2 constrained the search but verified containment against BUFFERED polygons,
    keeping the first spatial-join hit. In a small district a 12 km buffer overlaps
    its neighbours entirely, so "first hit" was arbitrary: small districts scored 0%
    and large ones 70%+, an artefact of district area rather than of matching.

    v3 tested set membership instead of first-hit, which fixed that — but still wrote
    the buffered set to the output layer and reported its pass rate as a success
    metric. That metric is tautological: candidates are drawn from the buffered
    district, so every accepted match passes by construction. It always reads 100%.

    v4 (this one) uses EXACT containment for the output layer and for all reported
    rates. Boundary-tolerance matches are written separately for sensitivity testing,
    with honest positional uncertainty attached.

    The distinction matters: a 12 km displacement is 20-30 minutes of rural travel
    time, an order of magnitude larger than the 0-2 km uncertainty the paper discloses.

METHOD
    1. GeoNames Sindh populated places, Latin script, alternate spellings expanded.
    2. Spatially assign each to GADM level-3 districts (buffered, so places near a
       boundary are candidates for both neighbours).
    3. Crosswalk PPHI district spellings to GADM spellings.
    4. Match each facility only within its district's candidate set.
    5. Verify each match falls inside the UNBUFFERED expected district polygon.

CAVEAT FOR THE PAPER
    Facilities sit at SETTLEMENT CENTROIDS, not buildings. Typical positional error
    0-2 km, roughly 0-5 min at rural driving speeds — small against travel times of
    20-100 min, and biased toward UNDERestimating travel time.

USAGE
    python scripts/rhai_11_geocode_pphi.py

OUTPUTS
    data/pphi_geocoded.gpkg            primary layer, exact containment — route on this
    data/pphi_geocoded_boundary.gpkg   boundary-tolerance matches, sensitivity only
    data/pphi_geocode_review.csv       78-87 band, manual review
    data/pphi_unmatched.csv            failures and wrong-district matches
    data/district_crosswalk.csv        PPHI -> GADM name mapping, for auditing
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
GADM = DATA / "gadm41_PAK_3.shp"
CROSSWALK_CSV = DATA / "district_crosswalk.csv"

OUT_GPKG = DATA / "pphi_geocoded.gpkg"
OUT_BOUNDARY = DATA / "pphi_geocoded_boundary.gpkg"
OUT_REVIEW = DATA / "pphi_geocode_review.csv"
OUT_UNMATCHED = DATA / "pphi_unmatched.csv"

METRIC_CRS = 32642
ACCEPT = 88
REVIEW = 78
SINDH_ADMIN1 = "05"
DISTRICT_BUFFER_M = 12000

PPL_CODES = {"PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC", "PPLL", "PPLS", "PPLX"}

CROSSWALK = {
    "Tharparkar": "Mithi",
    "Naushero Feroze": "Naushahro Firoz",
    "Shaheed Benazirabad": "Nawab Shah",
    "Jacobabad": "Jakobabad",
    "Tando Muhammad Khan": "Tando M. Khan",
    "Mirpurkhas": "Mirphurkhas",
    "Karachi West": "Karachi west",
    "Kamber": "Larkana",        # Kamber-Shahdadkot split from Larkana
    "Sujawal": "Thatta",        # Sujawal split from Thatta, 2013
    "Keamari": "Karachi west",  # Keamari split from Karachi West, 2020
}

PREFIX = re.compile(
    r"^\s*(B\.?H\.?U\.?|BASIC\s+HEALTH\s+UNIT"
    r"|R\.?H\.?C\.?|RURAL\s+HEALTH\s+CENT\w*"
    r"|G\.?D\.?|E\.?D\.?|U\.?S\.?K\.?|D\.?C\.?D\.?|S\.?G\.?D\.?"
    r"|GOV(ERNMENT)?\s+DISPENSARY|DISPENSARY"
    r"|M\.?C\.?H\.?C?\.?(\s+CENT\w*)?|MATERNITY\s+HOME|MOTHER\s+(AND|&)\s+CHILD"
    r"|T\.?H\.?Q\.?|D\.?H\.?Q\.?|TALUKA\s+HEAD\s*QUARTER|DISTRICT\s+HEAD\s*QUARTER"
    r"|GOV(ERNMENT)?\s+HOSPITAL|CIVIL\s+HOSPITAL|HOSPITAL"
    r"|SUB\s*-?\s*HEALTH\s+CENT\w*|HEALTH\s+CENT\w*)\s*[-:,]?\s*",
    re.I,
)
GOTH = re.compile(r"^\s*GOTH\s+|\s+GOTH\s*$", re.I)
TRAILING = re.compile(r"\s*\((.*?)\)\s*$|\s+(TALUKA|TEHSIL|DISTT?\.?|DISTRICT)\s+.*$", re.I)
LATIN = re.compile(r"[A-Za-z0-9 .'\-]+")


def settlement_name(facility: str) -> str:
    s = str(facility).strip()
    prev = None
    while prev != s:
        prev = s
        s = PREFIX.sub("", s).strip()
    s = TRAILING.sub("", s).strip()
    s = GOTH.sub(" ", s).strip()
    return re.sub(r"\s+", " ", s)


def load_districts() -> gpd.GeoDataFrame:
    if not GADM.exists():
        print(f"[FATAL] {GADM.name} required for district-constrained matching.")
        sys.exit(1)
    g = gpd.read_file(GADM)
    s = (g[g["NAME_1"] == "Sindh"][["NAME_3", "geometry"]]
         .rename(columns={"NAME_3": "district"})
         .dissolve(by="district", as_index=False)
         .to_crs(4326))
    print(f"[INFO] GADM Sindh districts: {len(s)}")
    return s


def load_gazetteer(districts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    frames = []

    if not GEONAMES.exists():
        print(f"[FATAL] {GEONAMES.name} missing — it supplies most matches.")
        print("        Download PK.zip from geonames.org/export/dump/")
        sys.exit(1)

    cols = ["geonameid", "name", "asciiname", "alternatenames", "latitude",
            "longitude", "feature_class", "feature_code", "country", "cc2",
            "admin1", "admin2", "admin3", "admin4", "population", "elevation",
            "dem", "timezone", "moddate"]
    gn = pd.read_csv(GEONAMES, sep="\t", names=cols, dtype=str, low_memory=False)
    gn = gn[(gn["feature_class"] == "P") & (gn["admin1"] == SINDH_ADMIN1)]
    gn = gn[gn["feature_code"].isin(PPL_CODES)]
    gn["population"] = pd.to_numeric(gn["population"], errors="coerce").fillna(0)

    rows = []
    for r in gn.itertuples(index=False):
        variants = {str(r.asciiname), str(r.name)}
        if isinstance(r.alternatenames, str) and r.alternatenames:
            variants.update(r.alternatenames.split(","))
        for v in variants:
            v = v.strip()
            if len(v) >= 3 and LATIN.fullmatch(v):
                rows.append({"place_name": v, "lon": float(r.longitude),
                             "lat": float(r.latitude), "population": r.population,
                             "source": "geonames"})
    gdf = gpd.GeoDataFrame(pd.DataFrame(rows),
                           geometry=gpd.points_from_xy([r["lon"] for r in rows],
                                                       [r["lat"] for r in rows]),
                           crs=4326)
    print(f"[gaz] geonames: {len(gn):,} places -> {len(gdf):,} Latin variants")
    frames.append(gdf)

    if VILLAGES.exists():
        v = gpd.read_file(VILLAGES).to_crs(4326)
        if "name" in v.columns:
            poly = v.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            if poly.any():
                v.loc[poly, "geometry"] = (
                    v.loc[poly].to_crs(METRIC_CRS).geometry.centroid.to_crs(4326))
            v = v[v["name"].notna()]
            v = v[v["name"].astype(str).map(lambda s: bool(LATIN.fullmatch(s.strip())))]
            if len(v):
                pop = (pd.to_numeric(v["population"], errors="coerce").fillna(0)
                       if "population" in v.columns else pd.Series(0.0, index=v.index))
                frames.append(gpd.GeoDataFrame(
                    {"place_name": v["name"].astype(str), "lon": v.geometry.x,
                     "lat": v.geometry.y, "population": pop, "source": "villages"},
                    geometry=v.geometry.values, crs=4326))
                print(f"[gaz] villages: {len(v):,} Latin-script")

    gaz = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    gaz["place_name"] = gaz["place_name"].str.strip()
    gaz = gaz[gaz["place_name"].str.len() >= 3]

    dm = districts.to_crs(METRIC_CRS).copy()
    # Buffer proportional to district size: ~10% of the equivalent radius,
    # capped at 12 km. A fixed buffer over-reaches in small districts and
    # makes their matches fail the containment test for purely geometric reasons.
    eq_radius = (dm.geometry.area / 3.14159) ** 0.5
    dm["geometry"] = dm.geometry.buffer((0.10 * eq_radius).clip(upper=DISTRICT_BUFFER_M))
    j = (gpd.sjoin(gaz.to_crs(METRIC_CRS), dm[["district", "geometry"]],
                   how="inner", predicate="within")
         .drop(columns=["index_right"]).to_crs(4326))
    print(f"[gaz] {len(j):,} place-district pairs "
          f"(candidate buffer {DISTRICT_BUFFER_M/1000:.0f} km)\n")
    return j.reset_index(drop=True)


def membership(pts: gpd.GeoDataFrame, polys: gpd.GeoDataFrame,
               colname: str) -> pd.Series:
    """For each point, the SET of district names whose polygon contains it.

    Set membership rather than first spatial-join hit: with buffered polygons a point
    commonly falls inside several districts, and picking the first arbitrarily made
    small districts look like failures.
    """
    j = gpd.sjoin(pts.to_crs(METRIC_CRS),
                  polys[["district", "geometry"]].rename(columns={"district": colname}),
                  how="left", predicate="within")
    return j.groupby(level=0)[colname].agg(lambda s: set(s.dropna()))


def main() -> int:
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        print("[FATAL] pip install rapidfuzz --break-system-packages")
        return 1

    if not PPHI_CSV.exists():
        print(f"[FATAL] {PPHI_CSV.name} not found. Run rhai_10 first.")
        return 1

    districts = load_districts()
    gadm_names = set(districts["district"])

    fac = pd.read_csv(PPHI_CSV)
    fac["settlement"] = fac["name"].map(settlement_name)
    fac = fac[fac["settlement"].str.len() >= 3].copy().reset_index(drop=True)
    fac["district_gadm"] = fac["district"].replace(CROSSWALK)

    unmapped = sorted(set(fac["district_gadm"]) - gadm_names)
    if unmapped:
        n = int(fac["district_gadm"].isin(unmapped).sum())
        print(f"[WARN] {len(unmapped)} PPHI districts have no GADM match: {unmapped}")
        print(f"       {n} facilities affected — matched province-wide and flagged.")
        print(f"       GADM names: {sorted(gadm_names)}\n")

    pd.DataFrame(sorted(CROSSWALK.items()),
                 columns=["pphi_name", "gadm_name"]).to_csv(CROSSWALK_CSV, index=False)

    gaz = load_gazetteer(districts)

    by_district: dict[str, tuple[list[str], pd.DataFrame]] = {}
    for d, sub in gaz.groupby("district"):
        sub = (sub.sort_values("population", ascending=False)
                  .drop_duplicates(subset=["place_name"], keep="first")
                  .reset_index(drop=True))
        by_district[d] = (sub["place_name"].tolist(), sub)
    sizes = [len(v[0]) for v in by_district.values()]
    print(f"[INFO] candidate sets for {len(by_district)} districts "
          f"(min {min(sizes):,}, median {int(np.median(sizes)):,}, max {max(sizes):,})")
    print(f"[INFO] geocoding {len(fac):,} facilities\n")

    results = []
    for i, row in enumerate(fac.itertuples(index=False), start=1):
        if i % 200 == 0:
            print(f"   ...{i:,}/{len(fac):,}")
        d = row.district_gadm
        if d in by_district:
            choices, sub = by_district[d]
            scope = "district"
        else:
            choices, sub, scope = gaz["place_name"].tolist(), gaz, "province_fallback"

        m = process.extractOne(row.settlement, choices,
                               scorer=fuzz.token_set_ratio, score_cutoff=REVIEW)
        if m is None:
            results.append({"matched_place": None, "score": 0.0, "lon": np.nan,
                            "lat": np.nan, "gaz_source": None, "match_scope": scope})
            continue
        _, score, idx = m
        g = sub.iloc[idx]
        results.append({"matched_place": g["place_name"], "score": float(score),
                        "lon": float(g["lon"]), "lat": float(g["lat"]),
                        "gaz_source": g["source"], "match_scope": scope})

    fac = pd.concat([fac, pd.DataFrame(results)], axis=1)
    fac["match_status"] = np.select(
        [fac["score"] >= ACCEPT, fac["score"] >= REVIEW],
        ["accepted", "review"], default="unmatched")

    # --- verify containment -------------------------------------------------
    has_xy = fac["lon"].notna()
    pts = gpd.GeoDataFrame(
        fac[has_xy].copy(),
        geometry=gpd.points_from_xy(fac.loc[has_xy, "lon"], fac.loc[has_xy, "lat"]),
        crs=4326)

    d_strict = districts.to_crs(METRIC_CRS)
    d_buf = districts.to_crs(METRIC_CRS).copy()
    d_buf["geometry"] = d_buf.geometry.buffer(DISTRICT_BUFFER_M)

    strict = membership(pts, d_strict, "landed_in")
    tolerant = membership(pts, d_buf, "near")

    fac["landed_in"] = pd.Series(
        {i: (sorted(v)[0] if v else None) for i, v in strict.items()})
    fac["district_exact"] = pd.Series(
        {i: fac.at[i, "district_gadm"] in v for i, v in strict.items()}
    ).reindex(fac.index).fillna(False)
    fac["district_near"] = pd.Series(
        {i: fac.at[i, "district_gadm"] in v for i, v in tolerant.items()}
    ).reindex(fac.index).fillna(False)

    acc = fac["match_status"] == "accepted"
    n_acc = int(acc.sum())
    n_rev = int((fac["match_status"] == "review").sum())
    n_un = int((fac["match_status"] == "unmatched").sum())
    n_exact = int((acc & fac["district_exact"]).sum())
    n_bound = int((acc & fac["district_near"] & ~fac["district_exact"]).sum())

    print()
    print("=" * 74)
    print("GEOCODING RESULTS — district-constrained")
    print("=" * 74)
    print(f"Facilities             : {len(fac):,}")
    print(f"Name-matched (>={ACCEPT})    : {n_acc:,}  ({n_acc/len(fac):.1%})")
    print(f"Needs review ({REVIEW}-{ACCEPT-1})   : {n_rev:,}  ({n_rev/len(fac):.1%})")
    print(f"Unmatched (<{REVIEW})        : {n_un:,}  ({n_un/len(fac):.1%})")
    print()
    print("CONTAINMENT (name-matched only)")
    print(f"  inside expected district : {n_exact:,}/{n_acc:,} "
          f"({n_exact/max(n_acc,1):.1%})")
    print(f"  outside, within {DISTRICT_BUFFER_M/1000:.0f} km   : {n_bound:,}   "
          f"-> separate layer, sensitivity only")
    print()
    print(f"  HEADLINE: {n_exact:,} of {len(fac):,} PPHI facilities geocoded with")
    print(f"            verified coordinates ({n_exact/len(fac):.1%})")
    print(f"  (unconstrained v1 scored 25.7% on the containment test)")
    print()

    fallback = int((fac["match_scope"] == "province_fallback").sum())
    if fallback:
        print(f"[WARN] {fallback} facilities matched province-wide (district not in "
              f"GADM). Treat as unverified.\n")

    print("By gazetteer source (verified):")
    print(fac.loc[acc & fac["district_exact"], "gaz_source"].value_counts().to_string())
    print()

    by_d = (fac.assign(exact=acc & fac["district_exact"], accepted=acc)
               .groupby("district")
               .agg(total=("exact", "size"), accepted=("accepted", "sum"),
                    verified=("exact", "sum")))
    by_d["rate"] = (by_d["verified"] / by_d["total"] * 100).round(1)
    by_d["exact_of_accepted"] = (
        by_d["verified"] / by_d["accepted"].replace(0, np.nan) * 100).round(1)
    print("Match rate by district (verified = name-matched AND inside district):")
    print(by_d.sort_values("rate").to_string())
    print()
    print("  rate              = verified / total PPHI facilities in that district")
    print("  exact_of_accepted = how often a name match also landed correctly.")
    print("                      Low here with high acceptance means a boundary or")
    print("                      crosswalk problem, not a naming problem.")
    print()

    zero = by_d[(by_d["verified"] == 0) & (by_d["total"] >= 10)]
    if len(zero):
        print(f"[WARN] {len(zero)} district(s) with 10+ facilities and zero verified "
              f"matches: {list(zero.index)}")
        print("       A wrong CROSSWALK entry gives exactly this signature.\n")

    suspect = by_d[(by_d["accepted"] >= 10) & (by_d["exact_of_accepted"] < 40)]
    if len(suspect):
        print(f"[CHECK] {len(suspect)} district(s) where most name matches landed "
              f"outside the district: {list(suspect.index)}")
        print("        Either GADM's boundary is off, or the crosswalk target is "
              "wrong.\n")

    # --- write --------------------------------------------------------------
    good = fac[acc & fac["district_exact"] & has_xy].copy()
    if len(good):
        gdf = gpd.GeoDataFrame(
            good, geometry=gpd.points_from_xy(good["lon"], good["lat"]), crs=4326)
        gdf["geocode_method"] = "settlement_centroid_fuzzy_district_verified"
        gdf["positional_uncertainty_km"] = 2.0
        gdf.to_file(OUT_GPKG, driver="GPKG")
        print(f"Wrote {OUT_GPKG.name}: {len(gdf):,} verified facilities  "
              f"<- route on this")

    loose = fac[acc & fac["district_near"] & ~fac["district_exact"] & has_xy].copy()
    if len(loose):
        gl = gpd.GeoDataFrame(
            loose, geometry=gpd.points_from_xy(loose["lon"], loose["lat"]), crs=4326)
        gl["geocode_method"] = "settlement_centroid_fuzzy_boundary_tolerance"
        gl["positional_uncertainty_km"] = float(DISTRICT_BUFFER_M) / 1000.0
        gl.to_file(OUT_BOUNDARY, driver="GPKG")
        print(f"Wrote {OUT_BOUNDARY.name}: {len(gl):,} boundary-tolerance facilities")
        print(f"      Excluded from the primary layer. {DISTRICT_BUFFER_M/1000:.0f} km "
              f"is 20-30 min of rural travel time — do not merge these silently.")

    fac[fac["match_status"] == "review"].to_csv(OUT_REVIEW, index=False)
    fac[(fac["match_status"] == "unmatched") |
        (acc & ~fac["district_exact"])].to_csv(OUT_UNMATCHED, index=False)
    print(f"Wrote {OUT_REVIEW.name} ({n_rev:,}) and {OUT_UNMATCHED.name}")

    print()
    print("NEXT")
    print("  1. Review the 78-87 band. Check the name AND that landed_in matches")
    print("     district_gadm.")
    print("  2. Rerun rhai_14_circularity_check.py on the corrected layer.")
    print("  3. Then rhai_12_merge_facilities.py and the Scenario B reroute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())