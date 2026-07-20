"""
RHAI Script 5 — SINDH routing, DISTRICT BY DISTRICT (resilient version).

Sindh is too large for one Overpass download, so this loops over each district,
downloads its road graph, routes villages -> nearest facility, and stitches all
results into one province-wide CSV.

RESILIENT:
  - uses a faster Overpass mirror + long timeout
  - retries each district a few times before giving up
  - one failed district never halts the run (continue)
  - resumable: districts already saved are skipped, so just rerun to mop up
"""
import osmnx as ox
import networkx as nx
import geopandas as gpd
import pandas as pd
import os, time

# --- make Overpass patient + use a faster mirror ---
ox.settings.requests_timeout = 300
ox.settings.overpass_url = "https://overpass.kumi.systems/api/interpreter"
# fallback mirrors to rotate through if one keeps timing out
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

DISTRICTS  = "data/gadm41_PAK_3.shp"
VILLAGES   = "data/sindh_villages.gpkg"
FACILITIES = "data/facilities_tiered.gpkg"
OUTDIR     = "data/district_results"
FINAL      = "data/rhai_traveltimes.csv"

HWY_SPEEDS = {"motorway":90,"trunk":70,"primary":55,"secondary":45,"tertiary":35,
              "unclassified":25,"residential":20,"track":15,"path":8,"service":20}

os.makedirs(OUTDIR, exist_ok=True)

# --- load inputs once ---
dist = gpd.read_file(DISTRICTS).to_crs(4326)
namecol = "NAME_3" if "NAME_3" in dist.columns else "NAME_2"
dist = dist[dist["NAME_1"] == "Sindh"][[namecol, "geometry"]]

villages_all = gpd.read_file(VILLAGES).to_crs(4326)
fac_all = gpd.read_file(FACILITIES).to_crs(4326)
fac_all["geometry"] = fac_all.to_crs(32642).geometry.centroid.to_crs(4326)

districts = sorted(dist[namecol].dropna().unique())
print(f"{len(districts)} districts to process\n")


def download_graph(poly):
    """Try each Overpass mirror until one works."""
    last_err = None
    for url in OVERPASS_MIRRORS:
        ox.settings.overpass_url = url
        try:
            return ox.graph_from_polygon(poly, network_type="drive")
        except Exception as e:
            last_err = e
            print(f"      mirror failed ({url.split('//')[1].split('/')[0]}), trying next...")
            time.sleep(3)
    raise last_err


def route_district(dname):
    d = dist[dist[namecol] == dname]
    poly = d.union_all() if hasattr(d, "union_all") else d.unary_union

    v = gpd.sjoin(villages_all, d, how="inner", predicate="within")
    v = v[[c for c in v.columns if not c.startswith("index_")]]
    if len(v) == 0:
        return None

    # 15 km halo so edge villages can reach a facility just across the border
    fbuf = d.to_crs(32642).buffer(15000).to_crs(4326).union_all()
    f = fac_all[fac_all.geometry.within(fbuf)].copy()
    if len(f) == 0:
        f = fac_all.copy()

    G = download_graph(poly)
    G = ox.add_edge_speeds(G, hwy_speeds=HWY_SPEEDS)
    G = ox.add_edge_travel_times(G)
    largest = max(nx.weakly_connected_components(G), key=len)
    G = G.subgraph(largest).copy()

    v["node"] = ox.distance.nearest_nodes(G, v.geometry.x, v.geometry.y)
    f["node"] = ox.distance.nearest_nodes(G, f.geometry.x, f.geometry.y)

    def nearest_min(sub):
        nodes = [n for n in sub["node"].unique() if n in G]
        best = {}
        for fnode in nodes:
            lengths = nx.single_source_dijkstra_path_length(G, fnode, weight="travel_time")
            for n, t in lengths.items():
                if n not in best or t < best[n]:
                    best[n] = t
        return best

    tmap = nearest_min(f)
    v["min_any"] = v["node"].map(lambda n: tmap.get(n))
    v["min_any"] = v["min_any"] / 60.0
    for tier in ["primary", "secondary", "tertiary"]:
        sub = f[f["tier"] == tier]
        if len(sub):
            tt = nearest_min(sub)
            v[f"min_{tier}"] = v["node"].map(lambda n: tt.get(n))
            v[f"min_{tier}"] = v[f"min_{tier}"] / 60.0

    v["district"] = dname
    v["X"] = v.geometry.x
    v["Y"] = v.geometry.y
    cols = ["village_id", "name", "district", "X", "Y"] + [c for c in v.columns if c.startswith("min_")]
    cols = [c for c in cols if c in v.columns]
    return v[cols]


# --- main loop: resumable, non-halting, retries per district ---
for i, dname in enumerate(districts, 1):
    safe = dname.replace(" ", "_").replace("/", "_")
    outpath = f"{OUTDIR}/{safe}.csv"
    if os.path.exists(outpath):
        print(f"[{i}/{len(districts)}] {dname}: already done, skipping")
        continue

    success = False
    for attempt in range(1, 4):                 # up to 3 tries per district
        t0 = time.time()
        try:
            res = route_district(dname)
            if res is None:
                print(f"[{i}/{len(districts)}] {dname}: no villages, skipping")
                success = True
                break
            res.to_csv(outpath, index=False)
            print(f"[{i}/{len(districts)}] {dname}: {len(res)} villages, "
                  f"median {res['min_any'].median():.1f} min  ({time.time()-t0:.0f}s)")
            success = True
            break
        except Exception as e:
            print(f"[{i}/{len(districts)}] {dname}: attempt {attempt} failed - {str(e)[:70]}")
            time.sleep(10)

    if not success:
        print(f"[{i}/{len(districts)}] {dname}: GAVE UP after 3 tries — rerun script later to retry")
        continue

# --- stitch all district CSVs into one province-wide file ---
parts = []
for fn in os.listdir(OUTDIR):
    if fn.endswith(".csv"):
        parts.append(pd.read_csv(f"{OUTDIR}/{fn}"))

if parts:
    final = pd.concat(parts, ignore_index=True)
    final.to_csv(FINAL, index=False)
    done = len(parts)
    print(f"\n=== STITCHED: {len(final)} villages across {done} districts ===")
    mincols = [c for c in final.columns if c.startswith("min_")]
    print(final[mincols].describe().to_string())
    if done < len(districts):
        print(f"\nNOTE: {len(districts)-done} districts still missing — rerun to retry them.")
    print(f"Saved {FINAL}")
else:
    print("No district results yet.")