"""
RHAI Script 3b (SINDH scale) — honest tiering of health facilities.

Reads Pakistan-wide healthsites.io, clips to Sindh, and tiers ONLY facilities
whose name explicitly states the tier (BHU / RHC / THQ / DHQ). Everything else
is 'unclassified' rather than guessed. Headline analysis uses 'any facility'.

Output: data/facilities_tiered.gpkg  (Sindh-wide)
"""
import geopandas as gpd
import re

HEALTHSITES = "data/pakistan_healthsites.geojson"
AREA        = "data/sindh_boundary.gpkg"          # <-- Sindh, not Thatta

fac  = gpd.read_file(HEALTHSITES).to_crs(4326)
area = gpd.read_file(AREA).to_crs(4326)

# clip to Sindh (spatial join does the clipping in memory)
fac = gpd.sjoin(fac, area[[area.columns[0], "geometry"]], how="inner", predicate="within")
fac = fac.drop(columns=[c for c in fac.columns if c.startswith("index_")])
print(f"facilities in Sindh: {len(fac)}")

# --- tier ONLY from explicit name keywords; else 'unclassified' ---
name = fac["name"].fillna("").str.upper()

def tier_from_name(n):
    if re.search(r"\bDHQ\b|DISTRICT HEAD|TEACHING|UNIVERSITY HOSP", n):    return "tertiary"
    if re.search(r"\bTHQ\b|TEHSIL HEAD|\bRHC\b|RURAL HEALTH", n):          return "secondary"
    if re.search(r"\bBHU\b|BASIC HEALTH|DISPENSARY|SUB.?CENTR|\bMCH\b", n): return "primary"
    return "unclassified"

fac["tier"] = name.map(tier_from_name)
fac["any_facility"] = True

print("\n=== tiers (only name-explicit ones are classified) ===")
print(fac["tier"].value_counts().to_string())
print("\nunclassified = OSM gives no reliable tier; still counted as 'any facility'")

# --- save ---
fac = fac.reset_index(drop=True)
fac["facility_id"] = fac.index + 1
keep = ["facility_id", "name", "amenity", "healthcare", "tier", "any_facility", "geometry"]
keep = [c for c in keep if c in fac.columns]
fac[keep].to_file("data/facilities_tiered.gpkg", driver="GPKG")
print(f"\nSaved data/facilities_tiered.gpkg  ({len(fac)} facilities)")