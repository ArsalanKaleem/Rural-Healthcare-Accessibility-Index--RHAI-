"""
RHAI Script 3b — honest tiering: only classify facilities whose NAME explicitly
states the tier (BHU/RHC/THQ/DHQ). Everything else is 'unclassified' rather than
guessed. This avoids the fake-pyramid problem where generic 'hospital' tags get
promoted to secondary.
"""
import geopandas as gpd
import re

HEALTHSITES = "data/pakistan_healthsites.geojson"
AREA        = "data/test_boundary.gpkg"   # swap to Sindh boundary when scaling

fac = gpd.read_file(HEALTHSITES).to_crs(4326)
area = gpd.read_file(AREA).to_crs(4326)
fac = gpd.sjoin(fac, area[[area.columns[0], "geometry"]], how="inner", predicate="within")
fac = fac.drop(columns=[c for c in fac.columns if c.startswith("index_")])
print(f"facilities in study area: {len(fac)}")

name = fac["name"].fillna("").str.upper()

def tier_from_name(n):
    if re.search(r"\bDHQ\b|DISTRICT HEAD|TEACHING|UNIVERSITY HOSP", n):  return "tertiary"
    if re.search(r"\bTHQ\b|TEHSIL HEAD|\bRHC\b|RURAL HEALTH", n):        return "secondary"
    if re.search(r"\bBHU\b|BASIC HEALTH|DISPENSARY|SUB.?CENTR|\bMCH\b", n): return "primary"
    return "unclassified"                        # <-- honest: not guessed

fac["tier"] = name.map(tier_from_name)

# a separate, always-valid grouping: "any facility"
fac["any_facility"] = True

print("\n=== tiers (only name-explicit ones are classified) ===")
print(fac["tier"].value_counts().to_string())
print(f"\nunclassified = OSM gives no reliable tier; still counted as 'any facility'")

fac = fac.reset_index(drop=True)
fac["facility_id"] = fac.index + 1
keep = ["facility_id","name","amenity","healthcare","tier","any_facility","geometry"]
fac[keep].to_file("data/facilities_tiered.gpkg", driver="GPKG")
print("\nSaved data/facilities_tiered.gpkg")