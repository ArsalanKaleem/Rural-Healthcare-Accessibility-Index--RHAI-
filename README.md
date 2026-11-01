# RHAI — Rural Healthcare Accessibility Index (Sindh, Pakistan)

Village-level travel time to the nearest health facility across Sindh, computed over the
real road network, and a measurement of how badly open geospatial data represents rural
public primary care infrastructure in Pakistan.

**The finding this repository exists to document:** open geospatial data omits most rural
public primary care facilities in Sindh. Accessibility estimates built on it overstate
travel times roughly twofold, overstate the underserved population tenfold, and
misidentify which districts are worst served.

---

## Scope

This study measures **geographic access to rural public primary care**. The comparison
register covers basic health units, rural health centres, dispensaries and
mother-and-child health centres operated by PPHI Sindh. Taluka and district headquarter
hospitals fall under the provincial health department and were not obtained; private
facilities are not recorded centrally anywhere. The shortfall reported here is a
shortfall in how open data represents that one tier.

### What this measures, and what it does not

The index estimates **physical reachability**: how long it takes to travel from a village
to the nearest health facility over the road network, accounting for road class and rural
driving speeds.

It does **not** measure:

- whether a facility is **staffed or functional** — a BHU with no doctor is a building
- whether medicines, equipment or electricity are present
- opening hours, or whether the facility is open when needed
- quality of care, affordability, or whether people actually use it
- transport availability — the model assumes a vehicle exists

Accessibility ≠ availability ≠ quality.

### The three-tier frame

| Tier | Question | This project |
|---|---|---|
| 1. Reachable | Can a person get there? | **Answered** — this is what the routing computes |
| 2. Physically present | Does the building exist? | **Partly** — satellite-checked on a sample |
| 3. Operational | Is it staffed, stocked, open? | **Not answered.** Needs ground data |

Tier 3 is the wall this project cannot cross with open data. Satellite imagery can
confirm a roof; it cannot confirm a doctor. Staff posted but not attending is invisible
from orbit.

---

## Headline results

| | Scenario A<br>(open data only) | Scenario B<br>(+ operator register) |
|---|---|---|
| Facilities | 2,725 | 3,308 |
| Median travel time | 19.1 min | 9.2 min |
| Population-weighted median | 14.3 min | 7.1 min |
| People over 30 min from care | **6.95 million** | **0.68 million** |
| People over 60 min | 1.26 million | 0.05 million |
| Maximum travel time | 263.8 min | 84.9 min |

- **Overstatement factor: 2.01×** population-weighted, 2.08× unweighted. Robust to
  excluding zero-distance cases (1.96×) and sub-minute cases (1.94×).
- **Only 5.2%** of located register facilities fall within 250 m of any facility in the
  open data. The two sources describe substantially different sets of buildings.
- **District priority rankings are not preserved** (Spearman ρ = 0.657 across all
  districts, 0.557 for the 22 with ≥10 villages; largest shift 14 places). Tharparkar and
  Dadu exchange first place depending on which facility layer is used.
- **Satellite check:** 42 of 50 sampled geocodes had a plausible facility structure
  within 500 m (84.0%, 95% CI 71.5–91.7).

### Coverage gap, selected districts

| District | Open data | + register | Multiplier | Register total |
|---|---|---|---|---|
| Ghotki | 1 | 34 | **34×** | 50 |
| Matiari | 1 | 17 | 17× | 36 |
| Kashmore | 1 | 15 | 15× | 44 |
| Tharparkar (Mithi) | 4 | 38 | 9.5× | 51 |
| Dadu | 4 | 35 | 8.8× | 50 |
| Jacobabad | 3 | 26 | 8.7× | 37 |
| Khairpur | 10 | 71 | 7.1× | 151 |
| **Tando Allahyar** | **0** | **1** | — | 47 |
| Karachi East / West / Central, Malir | — | — | **1.0×** | — |

Tando Allahyar — a district of over a million people — has **zero** health facilities in
open geospatial data, and only one of its 47 registered facilities could be geocoded.
Every metropolitan district gains nothing: open sources already had them. The bias is a
step function between urban and rural, not a gradient.

---

## Method

**Villages** → 5,159 settlement points across Sindh.
**Roads** → OpenStreetMap drive network, downloaded per district via Overpass.
**Routing** → OSMnx + NetworkX, one multi-source Dijkstra traversal seeded from all
facility nodes.
**Speeds** → set for rural conditions, not library defaults: motorway 90, trunk 70,
primary 55, secondary 45, tertiary 35, unclassified 25, residential 20, track 15,
path 8 km/h. These are judgement, not measurement — no speed survey exists for rural
Sindh. The same values apply to both scenarios, so the *comparison* does not depend on
them being right, though absolute times do.
**Halo** → 15 km facility buffer beyond each district boundary, so edge villages can
reach facilities across administrative lines.

**Cross-check.** Shah Bandar, Thatta: model 103.8 min vs independent routing 101 min,
under 3% apart. One case. It shows the graph and speeds produce a plausible result on one
long rural journey, and no more.

### Recovering the facility register

PPHI Sindh publishes district facility lists as PDFs with **names but no coordinates**.
Those were parsed and geocoded by matching each facility's embedded settlement name
against gazetteers, constrained to the facility's own district and verified against
district polygons.

| Step | Operation | Retained | Lost |
|---|---|---|---|
| 1 | Parsed from six regional PDFs | 1,357 | — |
| 2 | Settlement name extractable | 1,356 | 1 |
| 3 | Matched within own district at score ≥88 | 507 | 849 |
| 4 | Match inside expected district polygon | 477 | 30 |
| 5 | Borderline 78–87 screened by hand | +139 | 127 of 266 rejected |
| | **Recovered layer** | **616** | **741** |

**616 of 1,357 facilities (45.4%)** recovered with verified coordinates.

---

## Limitations

Stated plainly, because they are the point of the paper.

1. **The village layer is an OSM convenience sample.** Density ranges from 2.0 to 289.4
   villages per 1,000 km² — a 148-fold spread. Individual travel times are valid;
   unweighted aggregates partly describe where OSM contributors were active. All headline
   figures are population-weighted.

2. **Facilities sit at settlement centroids, not buildings.** Typical positional error
   0–2 km, roughly 0–5 minutes at rural speeds, biased toward *underestimating* travel
   time.

3. **372 villages (7.2%) show zero travel time under Scenario B**, because a facility
   geocoded to a settlement centroid snaps to the same graph node as the village named
   after it. Defensible, but an artefact. Results reported with and without.

4. **Scenario B remains an undercount**, worst where geocoding recovered least: Tando
   Allahyar (2%), Tando Muhammad Khan (8%), Umerkot (22%). Their travel times are still
   upper bounds and are not presented as corrected.

5. **The correction is not fully independent of the bias.** Geocoding success was
   unassociated with open-data facility density (ρ = −0.12, p = 0.59) but showed a
   borderline association with settlement mapping density (ρ = +0.41, p = 0.064, n = 21).
   Underpowered rather than null.

6. **17 villages (0.3%) show marginally longer times under Scenario B** (median +0.3 min,
   max +7.7 min), from non-deterministic OSM graph retrieval between runs.

7. **Secondary and tertiary facilities are absent.** The register covers primary care only.

8. **No functionality data.** See the three-tier frame above.

9. **Satellite validation was single-rater** with a permissive criterion. It establishes
   that coordinates land where a facility could plausibly stand, not that a specific
   facility was identified.

---

## Methodological findings

Three results that transfer beyond this study area.

**OpenStreetMap stores Sindh place names in Urdu script.** Taluka headquarter towns —
Dokri, Ratodero, Naudero, Setharja — returned no matches when searched in Latin against a
national extract of 29,746 places. Of the verified geocodes, GeoNames supplied the
overwhelming majority and OpenStreetMap place names supplied a handful. For Latin-script
record linkage in Pakistan, a Latin gazetteer with alternate-name coverage is a
requirement, not a supplement.

**Person-named settlements defeat unconstrained matching.** Rural Sindhi settlements are
named after landowners and clans, and those names recur province-wide. Unconstrained
fuzzy matching placed only 25.7% of facilities in the correct district, with 78 km median
displacement, while returning high similarity scores throughout. Spatial constraint is a
correctness requirement, not an optimisation.

**Metric choice is not neutral.** The token set ratio, a common default, scores subset
matches as perfect: "Khalifa Huryah" against "Khalifa" returns 100. This affected 30.3% of
accepted matches, including cases where two distinct facilities collapsed onto one
settlement. Substituting the token sort ratio removed the failure mode at the cost of a
lower recovery rate.

**And a limit on the approach itself.** In Tando Allahyar the register names settlements
by person and clan — Dodo Rind, Masoo Bozdar, Bachal Pittafi — while the gazetteer records
the same territory under settlement-type toponyms such as Saidpur, Padhar and Matli. Two
naming conventions describing the same landscape without intersecting. No threshold
adjustment bridges them.

---

## Repository layout

```
scripts/     analysis pipeline, numbered in execution order
data/        derived outputs (raw inputs gitignored — see data/README.md)
figures/     publication figures
docs/        district lookup tool (GitHub Pages)
```

Run `scripts/rhai_15_sanity_check.py` to verify pipeline invariants and
`scripts/rhai_20_final_audit.py` to regenerate every number reported in the paper.

---

## Data sources

| Source | Use | Licence |
|---|---|---|
| OpenStreetMap (Geofabrik extract, 12 July 2026) | roads, POIs, settlements | ODbL |
| GeoNames (PK) | gazetteer — supplied most geocodes | CC-BY 4.0 |
| GADM v4.1 level 3 | district boundaries | free for academic use |
| healthsites.io / HDX | health facility points | ODbL |
| PPHI Sindh district facility lists | facility register (names only) | published PDFs, linked not redistributed |
| WorldPop-derived village population | population weighting | CC-BY 4.0 |

---

## Reproducing

```bash
pip install -r requirements.txt
python scripts/rhai_05_route_by_district.py      # Scenario A  (hours)
python scripts/rhai_10_parse_pphi.py             # parse operator PDFs
python scripts/rhai_11_geocode_pphi.py           # district-constrained geocoding
python scripts/rhai_16_review_helper.py          # borderline match review
python scripts/rhai_12_merge_facilities.py       # build Scenario B layer
python scripts/rhai_05b_route_scenarioB.py       # Scenario B  (hours)
python scripts/rhai_13_compare_scenarios.py      # the comparison
python scripts/rhai_17_figures.py                # figures
```

Routing scripts are resumable — rerun to pick up any district that failed.

---

## Related work

**SWAI — Sindh Water Access Index.** Same 5,159 villages, drinking-water accessibility.
DOI: 10.5281/zenodo.21422759

Cross-project note: Shah Bandar scores 93.2/100 for water accessibility but sits 104
minutes from the nearest health facility under open data. Water-rich, healthcare-poor.

---

## Citation

The paper: [International Journal of Advanced Research, 3(5), 1606–1624](https://ijournalar.com/site/index.php/ijar/article/view/606) ([PDF](https://ijournalar.com/site/index.php/ijar/article/download/606/434))

```
Kaleem, A. (2026). What open geospatial data can and cannot tell us about
geographic access to rural public primary care: A village-level case study
from Sindh, Pakistan. International Journal of Advanced Research, 3(5),
1606–1624. https://ijournalar.com/site/index.php/ijar/article/view/606
```

```bibtex
@article{kaleem2026open,
  author  = {Kaleem, Arsalan},
  title   = {What Open Geospatial Data Can and Cannot Tell Us about Geographic Access to Rural Public Primary Care: A Village-Level Case Study from {Sindh}, {Pakistan}},
  journal = {International Journal of Advanced Research},
  year    = {2026},
  volume  = {3},
  number  = {5},
  pages   = {1606--1624},
  issn    = {3106-7980},
  url     = {https://ijournalar.com/site/index.php/ijar/article/view/606}
}
```

Code and data: https://github.com/ArsalanKaleem/Rural-Healthcare-Accessibility-Index--RHAI-

ORCID: [0009-0002-9054-6965](https://orcid.org/0009-0002-9054-6965)

## Licence

Code: MIT. Derived data: CC-BY 4.0, subject to the source licences above.

## Contact

Arsalan Kaleem — arsalanabbasi.here@gmail.com

Corrections and challenges to these numbers are welcome. If you hold facility coordinate
data for Sindh and are willing to share it, please get in touch — a complete facility
register would be the largest single improvement to this work.
