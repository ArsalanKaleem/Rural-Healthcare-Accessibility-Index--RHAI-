"""
RHAI Script 1 — carve out a single test district (Thatta) and its facilities.
Run this FIRST. It creates small, fast test data so you can debug the whole
pipeline before scaling to all of Sindh.

Requires in data/:
  - sindh_villages.gpkg          (from SWAI)
  - a Pakistan districts layer    (GADM level 3, or your boundary source)
  - Geofabrik Pakistan POIs        gis_osm_pois_free_1.shp  (+ _a_ polygon version)
Edit the paths below to match your files.
"""
import geopandas as gpd

TEST_DISTRICT = "Thatta"          # change to run a different district
DISTRICTS_PATH = "data/gadm41_PAK_3.shp"   # <-- your districts file
POIS_PATH      = "data/gis_osm_pois_free_1.shp"  # <-- Geofabrik POIs

# --- 1. district boundary ---
dist = gpd.read_file(DISTRICTS_PATH).to_crs(4326)
# GADM level 3 uses NAME_3 for districts; adjust if your source differs
namecol = "NAME_3" if "NAME_3" in dist.columns else "NAME_2"
test = dist[dist[namecol] == TEST_DISTRICT]
if test.empty:
    raise SystemExit(f"'{TEST_DISTRICT}' not found in column {namecol}. "
                     f"Available: {sorted(dist[namecol].dropna().unique())[:20]}")
test.to_file("data/test_boundary.gpkg", driver="GPKG")
print(f"boundary: {TEST_DISTRICT} saved")

# --- 2. villages inside the district ---
villages = gpd.read_file("data/sindh_villages.gpkg").to_crs(4326)
v = gpd.sjoin(villages, test[[namecol, "geometry"]], how="inner", predicate="within")
v = v.drop(columns=[c for c in v.columns if c.startswith("index_")])
v.to_file("data/test_villages.gpkg", driver="GPKG")
print(f"villages in {TEST_DISTRICT}: {len(v)}")

# --- 3. health facilities from OSM POIs, clipped to the district ---
health_classes = ["hospital", "clinic", "doctors", "pharmacy"]
pois = gpd.read_file(POIS_PATH).to_crs(4326)
health = pois[pois["fclass"].isin(health_classes)].copy()
fac = gpd.sjoin(health, test[[namecol, "geometry"]], how="inner", predicate="within")
fac = fac.drop(columns=[c for c in fac.columns if c.startswith("index_")])

# simple tiering
def tier(fclass):
    if fclass == "hospital":            return "secondary"
    if fclass in ("clinic", "doctors"): return "primary"
    if fclass == "pharmacy":            return "primary"
    return "primary"
fac["tier"] = fac["fclass"].map(tier)
fac = fac.reset_index(drop=True)
fac["facility_id"] = fac.index + 1
fac.to_file("data/test_facilities.gpkg", driver="GPKG")

print(f"facilities in {TEST_DISTRICT}: {len(fac)}")
print(fac["fclass"].value_counts().to_string())
print("\nDone. Next: rhai_02_route.py")
