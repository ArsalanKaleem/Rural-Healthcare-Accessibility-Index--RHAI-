# Rural Healthcare Accessibility Index (RHAI)

Village-level accessibility to healthcare across Sindh, Pakistan, using open
geospatial data — travel time and access score for every village to its
nearest Basic Health Unit (BHU) and hospital.

> **Status:** in development. See the 10-day build plan.

## What this measures — and what it does NOT

This index estimates **physical reachability** of health facilities: how long
it takes to travel from a village to the nearest facility over the road
network, accounting for rivers, canals and bridges as barriers.

It does **not** measure:
- whether the facility is **staffed or functional** (a BHU with no doctor is a building)
- **quality** of care available
- whether the facility is **open** when needed

These are stated up front because conflating reachability with access is the
single most common way health-accessibility indices mislead. Wherever possible,
functional status is treated as a separate, documented limitation.

## Data sources (all open)

| Data | Source | Note |
|---|---|---|
| Villages | OpenStreetMap / Geofabrik | places = village |
| Health facilities | OSM `amenity=hospital/clinic/doctors` + gov't lists where available | coverage is incomplete — a key limitation |
| Roads | OpenStreetMap | `highway=*`, with speed by road class |
| Rivers / canals | HydroRIVERS + OSM waterways | barriers to travel |
| Population | WorldPop | demand weighting |
| Boundaries | GADM or Natural Earth | districts |

## Reproducing

Large files (`.osm.pbf`, rasters) are excluded from this repo — see the table
above to download them. Then run the pipeline in order (documented in the build
plan / scripts).

## Author

Arsalan Kaleem — ORCID 0009-0002-9054-6965
