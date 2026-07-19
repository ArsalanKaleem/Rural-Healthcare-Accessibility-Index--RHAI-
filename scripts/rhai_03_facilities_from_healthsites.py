"""
RHAI Script 3 — build a properly TIERED facility layer from healthsites.io,
clipped to your study area, carrying functionality fields through.

Replaces the crude OSM-fclass facilities with real Pakistani health tiers
(BHU / RHC / THQ / DHQ) parsed from facility names + amenity tags.
"""
import geopandas as gpd
import pandas as pd
import re

HEALTHSITES = "data/pakistan_healthsites.geojson"
AREA        = "data/test_boundary.gpkg"     # Thatta test; swap for Sindh boundary later

fac = gpd.read_file(HEALTHSITES).to_crs(4326)
area = gpd.read_file(AREA).to_crs(4326)

# --- clip to study area ---
fac = gpd.sjoin(fac, area[[area.columns[0], "geometry"]], how="inner", predicate="within")
fac = fac.drop(columns=[c for c in fac.columns if c.startswith("index_")])
print(f"facilities in study area: {len(fac)}")

# --- tier from name keywords first (most reliable), then fall back to amenity ---
name = fac["name"].fillna("").str.upper()

def tier_from_name(n):
    if re.search(r"\bDHQ\b|DISTRICT HEAD|TEACHING|UNIVERSITY HOSP|CIVIL HOSPITAL", n): return "tertiary"
    if re.search(r"\bTHQ\b|TEHSIL HEAD|\bRHC\b|RURAL HEALTH", n):                       return "secondary"
    if re.search(r"\bBHU\b|BASIC HEALTH|DISPENSARY|MCH|SUB.?CENTR", n):                 return "primary"
    return None

fac["tier"] = name.map(tier_from_name)

# fall back to amenity tag where name didn't classify
amenity = fac["amenity"].fillna("").str.lower()
fac.loc[fac["tier"].isna() & amenity.eq("hospital"), "tier"] = "secondary"
fac.loc[fac["tier"].isna() & amenity.isin(["clinic","doctors","pharmacy"]), "tier"] = "primary"
fac["tier"] = fac["tier"].fillna("primary")   # default

print("\n=== tiers ===")
print(fac["tier"].value_counts().to_string())

# --- functionality fields: how much do we actually have? ---
func_cols = ["operational_status","staff_doctors","staff_nurses","beds","opening_hours","operator_type"]
print("\n=== functionality data available (this is the rare, valuable part) ===")
for c in func_cols:
    if c in fac.columns:
        filled = (fac[c].astype(str).str.strip().replace("nan","").replace("None","") != "").sum()
        print(f"  {c}: {filled}/{len(fac)} filled")

# --- keep useful columns, add facility_id, save ---
keep = ["name","amenity","healthcare","tier"] + [c for c in func_cols if c in fac.columns]
fac = fac.reset_index(drop=True)
fac["facility_id"] = fac.index + 1
fac[["facility_id"] + keep + ["geometry"]].to_file("data/facilities_tiered.gpkg", driver="GPKG")
print("\nSaved data/facilities_tiered.gpkg — use this in the router instead of test_facilities.gpkg")