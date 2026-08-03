# RHAI — Full Project Status

**Project:** Rural Healthcare Accessibility Index, Sindh, Pakistan
**Author:** Arsalan Kaleem — ORCID 0009-0002-9054-6965 | github.com/ArsalanKaleem
**Folder:** `C:\Projects\RHAI` | **Repo:** Rural-Healthcare-Accessibility-Index--RHAI-
**Direction:** Data-gap paper
**Updated:** August 2026

---

## 1. What the project is now

It started as "map healthcare access in Sindh." It is now something more defensible:

> **A measurement of how badly open geospatial data represents rural health
> infrastructure in Pakistan, and what that does to accessibility estimates built on it.**

The routing model is no longer the headline. It is the instrument that demonstrates the
consequence of the gap. This change happened because the evidence forced it, and it is a
stronger paper for it — the original version would not have survived review.

Working title:
*What open geospatial data can and cannot tell us about rural healthcare access:
a village-level case study from Sindh, Pakistan*

---

## 2. What is built and working

### Routing engine — validated
- OSMnx 2.1.0 + NetworkX 3.6.1, multi-source Dijkstra outward from each facility node.
- District-by-district execution with mirror rotation, retries, resumability, and a
  15 km facility halo for edge effects. Province-scale single-request routing fails
  (Overpass "70x max query area"); district-wise is the working design.
- Rural speed assumptions: motorway 90, trunk 70, primary 55, secondary 45, tertiary 35,
  unclassified 25, residential 20, track 15, path 8, service 20 km/h.
- **Validated:** Shah Bandar, Thatta — model 103.8 min vs Google Maps 101 min (<3% error).

### Coverage achieved
- **5,159 villages routed**, 0 duplicates, 2 unreachable, 25 of 27 GADM districts.
- Karachi Central and South contain zero village points (fully urban) — legitimately
  excluded, not failed runs.

### Provisional results (open data only — NOT publishable as stated)
| Metric | Value |
|---|---|
| Median travel time | 19.1 min |
| Mean | 28.1 min |
| p90 / p95 / p99 | 52.0 / 101.3 / 178.1 min |
| Max | 263.8 min |
| Villages at ≤0 min | 75 (snapped to same node as a facility) |

Sensitivity already run: ρ(score_log, score_clinical) = 0.971 village-level,
0.839 district-level. Alternative anchors: strict_30 ρ=0.989 (max rank shift 3),
lenient_120 ρ=0.952 (max shift 6). **District ranks are robust to the scoring choice.**

### Scripts (all in `scripts/`)
| Script | Purpose | Status |
|---|---|---|
| `rhai_01_setup_thatta.py` | Thatta pilot district | superseded |
| `rhai_02_route.py` | first router | superseded |
| `rhai_03_facilities_from_healthsites.py` | first tiering attempt | superseded (had the upside-down pyramid bug) |
| `rhai_03b_facilities_honest_tiers.py` | name-only tiering, no guessing | current |
| `rhai_04_route_final.py` | single-district router | current |
| `rhai_05_route_by_district.py` | resilient province router | **current, needs rerun with new facilities** |
| `rhai_06_check_coverage.py` | coverage audit + stitch + QA | done |
| `rhai_07_score.py` | scoring, aggregation, sensitivity | done |
| `rhai_08_layer_audit.py` | village/facility density diagnostics | done |
| `rhai_09b_shp_name_sweep.py` | OSM name-based facility sweep | **result invalid, see §4** |
| `rhai_10_parse_pphi.py` | PPHI PDF parser | done |
| `rhai_11_geocode_pphi.py` | fuzzy geocoder | done, 81.8% |

### Repo hygiene — resolved
`.gitignore` was broken because the **PowerShell generator script had been saved as the
file itself** (`$rules = @(`, quoted patterns, `WriteAllLines` call). Not a BOM, which is
what the SWAI notes assumed. 43 files in `data/` were being tracked. Now fixed: raw data
untracked, ignore rule verified live via `git check-ignore -v`.

Diagnostic worth remembering:
```powershell
Get-Content .gitignore | ForEach-Object { "[$_]" }
```
Quotes, commas or `$` in the output means you are looking at code, not patterns.

---

## 3. The findings

### Finding 1 — Facility data is missing, not mistagged
Open sources (OpenStreetMap, healthsites.io) hold 2,725 facilities for Sindh.
**2,246 of them — 82% — are in Karachi**, roughly 1% of the province's land area.

Against PPHI's published lists (1,357 facilities parsed from six regional PDFs):

| District | PPHI listed | Open data | Captured |
|---|---|---|---|
| Khairpur | 151 | 10 | 7% |
| Badin | 107 | 68 | 64% |
| Sanghar | 92 | 65 | 71% |
| Jamshoro | 67 | 13 | 19% |
| **Tharparkar** | **51** | **4** | **8%** |
| Dadu | 50 | 4 | 8% |
| Ghotki | 50 | 1 | 2% |
| Naushero Feroze | 48 | 5 | 10% |
| Tando Allahyar | 47 | 0 | 0% |
| **Karachi East** | **8** | **800** | — |

That last row is the paper in one line: open data over-represents private urban clinics
by two orders of magnitude while missing public rural infrastructure almost entirely.
The bias is not noise — it is structural, and it runs exactly opposite to where
accessibility research needs accuracy.

PPHI's own figures (Baig et al. 2025, *Malaria Journal* 24:265): 1,469 facilities managed
across 26 districts; 1,088 primary analysed (681 BHU, 331 dispensaries, 36 MCH, 40 other);
mean 13,462 people served per facility; district population coverage 17%–79%, mean 46%.

### Finding 2 — Mithi's number was an artefact
Tharparkar's median of 97.7 min and "72.3% of villages over 60 min" were computed against
**4 facilities in 19,653 km²**, when 51 exist. Direction plausible, magnitude wrong.
This is the clearest illustration of why the study could not be published as originally
framed, and it belongs in the paper as a worked example.

### Finding 3 — OSM stores Sindh place names in Urdu script
**23% of OSM place names in Sindh are Urdu script** (خیرپور, سکھر, نوشہرو فیروز).
Taluka headquarters towns — Dokri, Ratodero, Naudero, Setharja — returned **zero**
matches against a 29,746-place national extract when searched in Latin.

Consequence for record linkage: of 1,109 successful geocodes, **GeoNames supplied 1,078
and OSM places supplied 2.** OSM was not merely less useful; it was unusable for this task.

This appears to be undocumented and is a genuine methodological contribution.

### Finding 4 — Village layer is an OSM convenience sample
Density range across districts: **2.0 to 289.4 villages per 1,000 km² — a 148-fold spread.**
Over-sampled: Hyderabad 289.4, Shikarpur 148.7, Larkana 116.9. Under-sampled: Thatta 3.5,
Tando Allahyar 2.8, Jamshoro 2.0.

Still valid: individual village travel times.
Not valid: the province median, unweighted district means, cross-district "% over 60 min".

### Finding 5 — Geocoding by settlement name works
1,357 PPHI facilities parsed → **1,109 geocoded (81.8%)**, 115 in review band, 132 failed.
Rural districts that carry the argument all scored high: Ghotki 94%, Kashmore 91%,
Dadu 88%, Khairpur 85%, Tharparkar 71%.

**Tharparkar goes from 4 facilities to 36.**

---

## 4. Corrections to earlier conclusions — do not carry these forward

Four things were concluded and later shown wrong. Recording them because two are still
sitting in outputs.

1. **"Six schema variants = six script versions."** Wrong. The differing columns are only
   tier columns, and their presence tracks whether a named-tier facility exists in each
   district's halo. One script behaving as designed. `district_results/` was nearly
   deleted on this basis.
2. **"Karachi Central and South failed."** Wrong. Zero village points — fully urban.
3. **"The `.gitignore` problem is a BOM."** Wrong. The generator script had been saved as
   the file. Different cause, different fix.
4. **`rhai_09b` name sweep result is invalid.** It searched for "BHU", "RHC", "Hospital"
   in a `name` column that is 23% Urdu script. Facilities named in Urdu were invisible
   to it. The reported 1.9% gain and the conclusion "the buildings were never mapped"
   are both unsupported. **Must be rerun against `name:en` / `name:ur` before any claim
   about OSM facility coverage is made.**

---

## 5. What to do next

### Immediate — before rerouting
- [ ] **Circularity check.** Correlate per-district geocode match rate against
      per-district village density from `rhai_layer_audit.csv` (Spearman). If they
      correlate, geocoding succeeds preferentially where OSM already mapped things —
      the same bias being measured. Ghotki at 94% with 1 mapped facility argues against
      it, but test properly. State the result either way.
- [ ] **Review the 115 rows** in `pphi_geocode_review.csv` (80–89 band) by hand.
- [ ] **District name crosswalk.** PPHI vs GADM spellings differ and the join will
      silently drop rows: Tharparkar/Mithi, Kamber/Qambar, Naushero Feroze/Naushahro
      Firoz, Shaheed Benazirabad/Nawab Shah, Jacobabad/Jakobabad, Tando Muhammad
      Khan/Tando M. Khan. Sujawal and Keamari appear in PPHI but not in the routed set.
- [ ] **Copy `village_population.csv`** from the SWAI folder. Every
      `underservice_burden` is currently NaN.
- [ ] **Confirm ED and USK** facility codes from a PPHI legend page if one exists.
      Currently treated as primary and flagged as unconfirmed (ED n≈46, USK n=3).

### Validation — this is what makes the layer publishable
- [ ] Sample ~50 accepted geocodes, open in QGIS over satellite basemap, check a
      plausible facility building sits near each point. Report the accuracy rate with a
      confidence interval.
- [ ] Have a second person code 30 of them; report Cohen's κ if you can arrange it.
- [ ] Three more Google Maps route spot-checks: one over-sampled district (Larkana),
      one under-sampled (Jamshoro), one desert (Mithi).

### The central experiment
- [ ] Merge `pphi_geocoded.gpkg` into the facility layer.
- [ ] Rerun `rhai_05_route_by_district.py`.
- [ ] **Scenario A** (open data only) = upper bound on travel time.
      **Scenario B** (open + PPHI) = lower bound.
- [ ] Report per district: median under A, median under B, and the ratio.
      *"Open-data-only estimates overstate median rural travel time by a factor of N"*
      is the result that gets cited.
- [ ] Report Spearman ρ between A and B district rankings. If ranks hold while
      magnitudes do not, that is a useful methodological finding in itself.

### Analysis to finish
- [ ] Population-weight every province and district statistic.
- [ ] Recompute `underservice_burden` = Σ((100 − score)/100 × population).
- [ ] Drop or caveat districts with <10 villages (Rann of Kutch scoring 100/100 on five
      villages in a salt flat is indefensible).
- [ ] Sensitivity on road speeds (±20%), not just time anchors.
- [ ] Investigate the 75 villages at ≤0 min and the 2 unreachable — one line each in methods.
- [ ] Rerun `rhai_09b` against `name:en`/`name:ur` (see §4.4).
- [ ] Optional robustness: rerun on a 1 km WorldPop grid clipped to populated cells,
      report ρ between grid- and village-derived district ranks. Pre-empts the referee
      comment that is otherwise guaranteed.

### Figures
1. **Coverage gap by district** — PPHI vs open data. *Figure 1.*
2. Facility density map — open data vs PPHI, side by side.
3. Village density map — the 148-fold spread.
4. Travel-time bounds — Scenario A vs B per district, range shaded.
5. Score distribution, population-weighted.
6. District ranking by underservice burden.
7. Interactive Folium map — repo only, not the paper.

### Paper
Structure: intro (open-data reliance is untested for Pakistan) → study area → methods →
results part 1 (the gap) → results part 2 (the consequence) → discussion (what open data
can and cannot be used for) → limitations → conclusion.

Keep the three-tier honesty frame:
- **Tier 1 Reachable** — what the routing computes.
- **Tier 2 Physically present** — satellite-verifiable.
- **Tier 3 Operational** — staffed, stocked, open. Needs ground data. **This project
  cannot cross that line and must say so.** The "ghost worker" problem is invisible
  from orbit.

Targets: *International Journal of Health Geographics* (best fit) · *BMC Health Services
Research* · *Geospatial Health* · *PLOS ONE* (fallback) · *Scientific Data* later, as a
descriptor covering SWAI + RHAI together.

**Do not:** publish a named list of facilities believed missing or non-functional — report
rates and district aggregates. Do not present bounded estimates as measurements. Do not
lead with a triumphant claim.

### Release
- [ ] README following SWAI's template — lead with the limitation.
- [ ] Force-add small derived tables (`git add -f`), keep large inputs ignored.
- [ ] Verify which Zenodo record is canonical for SWAI — handoff says
      10.5281/zenodo.21422759, but record 21470648 is also live. Use the concept DOI.
- [ ] Cite **GeoNames (CC-BY 4.0)** — it supplied 97% of successful geocodes.
- [ ] Cite the Geofabrik extract date: **12 July 2026** (`pakistan-260712-free.shp`).
- [ ] Frontend, deferred: static MapLibre GL site on GitHub Pages. 5,159 points ≈ 1.5 MB
      GeoJSON, no server. Build after the paper; put the URL in it.

---

## 6. Outreach — parallel track, do not block on it

Emails drafted and ready. Send them, then carry on as if no reply is coming.

| Contact | Email | Notes |
|---|---|---|
| Dr. Muhammad Ahmed, NED Urban & Infrastructure Eng. | muhammadahmed@neduet.edu.pk | **Send first.** GIS geographer, built PPHI's facility maps, ext. 2454 |
| Ms. Nelofer Baig, Dep. Director Research, PPHI | nelofer.baig@pphisindh.org | Address pattern unverified — **CC info@pphisindh.org.pk** |
| PPHI Head Office | info@pphisindh.org.pk | Clifton Block 2, Karachi. 021-35872214 |
| Prof. Zafar Fatmi, AKU CHS | zafar.fatmi@aku.edu | Corresponding author, malaria paper |
| Sindh Health Department | info@sindhhealth.gov.pk | Holds THQ/DHQ/tertiary tier |
| CDC Sindh | contact@cdc.gos.pk | Dr. Samreen Qureshi, +92 345 4997711 |

The specific ask: their 2025 *Malaria Journal* paper states each facility was geolocated
with GPS coordinates validated by cross-validation and accuracy assessment, processed in
ArcMap 10.8. So the coordinate layer demonstrably exists. Request that, not "do you have
data."

Attachment: one A4 PDF. Map on top (captioned as evidence of the gap, not as a finding
about PPHI), coverage-gap table in the middle, method/ask/contact at the bottom.
One file, under 1 MB.

Ghotki = 50 and Khairpur = 151 are **confirmed** by the parser. The email is correct.

---

## 7. Approaches ruled out

- **Google Earth Engine for facilities** — GEE serves raster imagery, holds no POI data.
- **Google Places API / Selenium scraping** — terms prohibit storing content and building
  competing datasets. Result would be unpublishable and would undermine a paper about
  data integrity. Google Maps remains fine for spot-check route validation.
- **Full `pakistan-latest.osm.pbf` sweep** — at 93.6% already-known in the shapefile
  sweep, marginal. Revisit only if the `name:en` rerun suggests otherwise.
- **VIIRS nightlights for facility operation** — 500 m pixels vs ~200 m² buildings;
  load-shedding makes darkness uninformative; no ground truth to validate against.
  A narrow version (excess radiance over a 1–3 km annulus, tertiary facilities only,
  reported as "night-time electrification signal") is defensible later. Not now, and
  never as an operational-status layer.

---

## 8. Discipline carried from SWAI

- Reproject to EPSG:32642 before any distance or buffer operation.
- QGIS "temporary layer" trap — always Save to File explicitly.
- Never `git add .` — add by name, `git status` before every commit.
- Close CSVs in Excel before running scripts that write them (PermissionError).
- Activate the venv — check for `(venv)` in the prompt before running anything.
- Validate against real-world ground truth before trusting anything at scale.
- Accessibility ≠ availability ≠ quality. State the distinction often.
- Satellite data verifies presence, never operation.
- The project's real value is documenting where and why the method fails.
