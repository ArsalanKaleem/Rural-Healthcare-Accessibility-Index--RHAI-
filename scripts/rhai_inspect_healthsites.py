"""
Inspect the healthsites.io facility data to see if it supports real tiering.
Edit FPATH to your downloaded file (gpkg, geojson, shp, or csv).
"""
import geopandas as gpd
import pandas as pd

FPATH = "data/pakistan_healthsites.geojson"   # <-- change to your downloaded file

try:
    fac = gpd.read_file(FPATH)
except Exception:
    fac = pd.read_csv(FPATH)   # if it's a plain CSV

print("=== columns ===")
print(list(fac.columns))
print(f"\ntotal facilities in file: {len(fac)}")

# find the type/nature column (name varies: 'amenity', 'nature', 'healthcare', etc.)
candidates = [c for c in fac.columns if any(k in c.lower()
              for k in ["nature", "amenity", "type", "healthcare", "category", "class"])]
print(f"\nlikely 'type' columns: {candidates}")

for c in candidates:
    print(f"\n--- distinct values in '{c}' ---")
    print(fac[c].value_counts().head(25).to_string())

# peek at names — DHQ/RHC/BHU often live in the name string
namecols = [c for c in fac.columns if "name" in c.lower()]
if namecols:
    nc = namecols[0]
    print(f"\n--- sample names from '{nc}' (look for DHQ/THQ/RHC/BHU) ---")
    print(fac[nc].dropna().head(20).to_string())
    for tag in ["DHQ", "THQ", "RHC", "BHU", "Rural Health", "Basic Health", "Teaching"]:
        n = fac[nc].str.contains(tag, case=False, na=False).sum()
        if n:
            print(f"  names containing '{tag}': {n}")
            f = gpd.read_file("data/pakistan_healthsites.geojson")
for c in ["operational_status","staff_doctors","staff_nurses","beds","opening_hours","operator_type"]:
    filled = (f[c].astype(str).str.strip().replace("nan","") != "").sum()
    print(f"{c}: {filled} of {len(f)} filled")