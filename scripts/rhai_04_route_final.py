"""
RHAI Script 4 — FINAL router.
Headline metric: travel time (minutes) to the nearest health facility of ANY type.
Secondary: time to nearest name-classified facility per tier, where such facilities
exist (reported honestly, may be missing in districts OSM doesn't tier).

Point AREA/VILLAGES/FACILITIES at Thatta test files now; swap to Sindh-wide files
(same code) to scale up.
"""
import osmnx as ox
import networkx as nx
import geopandas as gpd
import pandas as pd

AREA       = "data/test_boundary.gpkg"
VILLAGES   = "data/test_villages.gpkg"
FACILITIES = "data/facilities_tiered.gpkg"   # from script 3b: has 'tier' + 'any_facility'

HWY_SPEEDS = {"motorway":90,"trunk":70,"primary":55,"secondary":45,"tertiary":35,
              "unclassified":25,"residential":20,"track":15,"path":8,"service":20}

boundary = gpd.read_file(AREA).to_crs(4326)
villages = gpd.read_file(VILLAGES).to_crs(4326)
fac      = gpd.read_file(FACILITIES).to_crs(4326)
fac["geometry"] = fac.to_crs(32642).geometry.centroid.to_crs(4326)
poly = boundary.union_all() if hasattr(boundary,"union_all") else boundary.unary_union

print("downloading road network (cached after first run)...")
G = ox.graph_from_polygon(poly, network_type="drive")
G = ox.add_edge_speeds(G, hwy_speeds=HWY_SPEEDS)
G = ox.add_edge_travel_times(G)
largest = max(nx.weakly_connected_components(G), key=len)
G = G.subgraph(largest).copy()
print(f"  graph: {len(G.nodes)} nodes")

villages["node"] = ox.distance.nearest_nodes(G, villages.geometry.x, villages.geometry.y)
fac["node"]      = ox.distance.nearest_nodes(G, fac.geometry.x, fac.geometry.y)

def nearest_minutes(fac_subset):
    nodes = [n for n in fac_subset["node"].unique() if n in G]
    if not nodes:
        return {}
    best = {}
    for fnode in nodes:
        lengths = nx.single_source_dijkstra_path_length(G, fnode, weight="travel_time")
        for n, t in lengths.items():
            if n not in best or t < best[n]:
                best[n] = t
    return best

# --- HEADLINE: any facility ---
tmap = nearest_minutes(fac)
villages["min_any"] = villages["node"].map(lambda n: tmap.get(n))
villages["min_any"] = villages["min_any"] / 60.0

# --- SECONDARY: per tier, only where that tier exists ---
for tier in ["primary","secondary","tertiary"]:
    sub = fac[fac["tier"] == tier]
    if len(sub) == 0:
        print(f"  (no '{tier}' facilities in area — skipping)")
        continue
    tmap_t = nearest_minutes(sub)
    villages[f"min_{tier}"] = villages["node"].map(lambda n: tmap_t.get(n))
    villages[f"min_{tier}"] = villages[f"min_{tier}"] / 60.0

cols = [c for c in villages.columns if c.startswith("min_")]
villages["X"] = villages.geometry.x
villages["Y"] = villages.geometry.y
keep = ["village_id","name","X","Y"] + cols
keep = [c for c in keep if c in villages.columns]
villages[keep].to_csv("data/rhai_traveltimes.csv", index=False)

print("\n=== travel time to nearest facility (minutes) ===")
print(villages[cols].describe().to_string())
print(f"\nunreachable (any facility): {villages['min_any'].isna().sum()} of {len(villages)}")
print("Saved data/rhai_traveltimes.csv")