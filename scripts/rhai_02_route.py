"""
RHAI Script 2 — download the road network for the test district, build a
travel-time graph, and compute travel time from every village to the nearest
facility of each tier.

Run AFTER rhai_01_setup_thatta.py. On a single district this should finish in
a minute or two. Once it works here, the SAME code runs on all of Sindh by
pointing it at the province-wide files.
"""
import osmnx as ox
import networkx as nx
import geopandas as gpd
import pandas as pd

# --- realistic rural speeds (km/h) — documented modelling choice ---
HWY_SPEEDS = {
    "motorway": 90, "trunk": 70, "primary": 55, "secondary": 45,
    "tertiary": 35, "unclassified": 25, "residential": 20,
    "track": 15, "path": 8, "service": 20,
}
TIER_CAPS = {"primary": 60, "secondary": 120, "tertiary": 180}  # minutes

# --- 1. load test data ---
boundary = gpd.read_file("data/test_boundary.gpkg").to_crs(4326)
villages = gpd.read_file("data/test_villages.gpkg").to_crs(4326)
fac      = gpd.read_file("data/test_facilities.gpkg").to_crs(4326)
poly = boundary.union_all() if hasattr(boundary, "union_all") else boundary.unary_union

# --- 2. download the drivable road network ---
print("downloading road network...")
G = ox.graph_from_polygon(poly, network_type="drive")
print(f"  nodes: {len(G.nodes)}  edges: {len(G.edges)}")

# --- 3. add speeds + travel times ---
G = ox.add_edge_speeds(G, hwy_speeds=HWY_SPEEDS)
G = ox.add_edge_travel_times(G)

# --- 4. keep the largest connected component (avoids infinite times) ---
# for driving graphs use the largest weakly connected component
largest = max(nx.weakly_connected_components(G), key=len)
G = G.subgraph(largest).copy()
print(f"  largest component nodes: {len(G.nodes)}")

# --- 5. snap villages and facilities to nearest graph nodes ---
villages["node"] = ox.distance.nearest_nodes(G, villages.geometry.x, villages.geometry.y)
fac["node"]      = ox.distance.nearest_nodes(G, fac.geometry.x, fac.geometry.y)

# --- 6. multi-source Dijkstra: for each tier, time from every node to nearest facility ---
def nearest_minutes(tier):
    nodes = fac.loc[fac["tier"] == tier, "node"].unique()
    best = {}
    for fnode in nodes:
        if fnode not in G:      # facility snapped outside the kept component
            continue
        lengths = nx.single_source_dijkstra_path_length(G, fnode, weight="travel_time")
        for n, t in lengths.items():
            if n not in best or t < best[n]:
                best[n] = t
    return best

for tier in ["primary", "secondary", "tertiary"]:
    tmap = nearest_minutes(tier)
    villages[f"min_{tier}"] = villages["node"].map(lambda n: tmap.get(n)) 
    villages[f"min_{tier}"] = villages[f"min_{tier}"] / 60.0   # sec -> min

# --- 7. save ---
keep = ["village_id", "name", "min_primary", "min_secondary", "min_tertiary"]
keep = [c for c in keep if c in villages.columns]
out = villages[keep + [villages.geometry.name]].copy()
out["X"] = villages.geometry.x
out["Y"] = villages.geometry.y
out.drop(columns=villages.geometry.name).to_csv("data/test_traveltimes.csv", index=False)

print("\n=== travel time (minutes) ===")
print(villages[[c for c in villages.columns if c.startswith("min_")]].describe().to_string())
n_unreached = villages["min_primary"].isna().sum()
print(f"\nvillages with no route to a primary facility: {n_unreached}")
print("Saved data/test_traveltimes.csv — inspect before scaling to all of Sindh.")
