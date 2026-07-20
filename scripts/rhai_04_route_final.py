"""
RHAI Script 4 (SINDH scale) — FINAL router.

Headline metric: travel time (minutes) to the nearest health facility of ANY type,
for every village in Sindh, routed over the real OSM road network.
Secondary: per-tier times where name-classified facilities exist.

MEMORY NOTE: downloading the whole-Sindh drive network is the heavy step.
If this runs out of RAM or hangs, stop and switch to the per-district version.
"""
import osmnx as ox
import networkx as nx
import geopandas as gpd
import pandas as pd
import time

AREA       = "data/sindh_boundary.gpkg"      # <-- Sindh
VILLAGES   = "data/sindh_villages.gpkg"      # <-- all Sindh villages
FACILITIES = "data/facilities_tiered.gpkg"   # <-- Sindh-wide, from 03b

HWY_SPEEDS = {"motorway":90,"trunk":70,"primary":55,"secondary":45,"tertiary":35,
              "unclassified":25,"residential":20,"track":15,"path":8,"service":20}

t0 = time.time()
boundary = gpd.read_file(AREA).to_crs(4326)
villages = gpd.read_file(VILLAGES).to_crs(4326)
fac      = gpd.read_file(FACILITIES).to_crs(4326)

# polygons -> points (projected centroid, silences the CRS warning)
fac["geometry"] = fac.to_crs(32642).geometry.centroid.to_crs(4326)

poly = boundary.union_all() if hasattr(boundary,"union_all") else boundary.unary_union
print(f"villages: {len(villages)} | facilities: {len(fac)}")

print("downloading Sindh road network (SLOW + memory-heavy)...")
G = ox.graph_from_polygon(poly, network_type="drive")
print(f"  raw graph: {len(G.nodes)} nodes, {len(G.edges)} edges  ({time.time()-t0:.0f}s)")

G = ox.add_edge_speeds(G, hwy_speeds=HWY_SPEEDS)
G = ox.add_edge_travel_times(G)

largest = max(nx.weakly_connected_components(G), key=len)
G = G.subgraph(largest).copy()
print(f"  largest component: {len(G.nodes)} nodes")

print("snapping villages & facilities to graph...")
villages["node"] = ox.distance.nearest_nodes(G, villages.geometry.x, villages.geometry.y)
fac["node"]      = ox.distance.nearest_nodes(G, fac.geometry.x, fac.geometry.y)

def nearest_minutes(fac_subset):
    nodes = [n for n in fac_subset["node"].unique() if n in G]
    if not nodes:
        return {}
    best = {}
    for i, fnode in enumerate(nodes):
        lengths = nx.single_source_dijkstra_path_length(G, fnode, weight="travel_time")
        for n, t in lengths.items():
            if n not in best or t < best[n]:
                best[n] = t
        if i % 100 == 0:
            print(f"    routed from {i}/{len(nodes)} facilities...")
    return best

print("routing: nearest facility of ANY type...")
tmap = nearest_minutes(fac)
villages["min_any"] = villages["node"].map(lambda n: tmap.get(n)) 
villages["min_any"] = villages["min_any"] / 60.0

for tier in ["primary","secondary","tertiary"]:
    sub = fac[fac["tier"] == tier]
    if len(sub) == 0:
        print(f"  (no '{tier}' facilities in Sindh — skipping)")
        continue
    print(f"routing: nearest '{tier}' ({len(sub)} facilities)...")
    tmap_t = nearest_minutes(sub)
    villages[f"min_{tier}"] = villages["node"].map(lambda n: tmap_t.get(n))
    villages[f"min_{tier}"] = villages[f"min_{tier}"] / 60.0

villages["X"] = villages.geometry.x
villages["Y"] = villages.geometry.y
cols = [c for c in villages.columns if c.startswith("min_")]
keep = ["village_id","name","X","Y"] + cols
keep = [c for c in keep if c in villages.columns]
villages[keep].to_csv("data/rhai_traveltimes.csv", index=False)

print("\n=== SINDH travel time to nearest facility (minutes) ===")
print(villages[cols].describe().to_string())
print(f"\nunreachable (any facility): {villages['min_any'].isna().sum()} of {len(villages)}")
print(f"total runtime: {time.time()-t0:.0f}s")
print("Saved data/rhai_traveltimes.csv")