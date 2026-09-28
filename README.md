# hujan-badai

Object-based storm detection and tracking over Indonesia, from GPM IMERG half-hourly
precipitation. Each storm is a connected object in space **and** time, so it has a
birth, a track, a life and a death rather than being a set of unrelated rainy pixels.

The catalogue covers **1998-2025**, **27.75** years, **13,386,185** storms, **618,505** km3 of rainfall, one Parquet file per year.

---

## Background

Grid-based rainfall statistics answer "how much fell here" but not "what fell here".
Object-based methods treat a storm as a thing with properties: a volume, a duration, a
peak intensity, a path. That reframing is what makes questions like *how long does a
storm spend over water before it reaches the coast* answerable at all.

This project started from the Spatiotemporal Contiguous Object-based Rainfall Analysis
(ST-CORA) of Laverde-Barajas et al., and diverged where that method did not survive
contact with this domain.

### Source work

- Laverde-Barajas, M., et al. (2019). *Spatiotemporal Analysis of Extreme Rainfall
  Events Using an Object-Based Approach.* In Spatiotemporal Analysis of Extreme
  Hydrological Events, 95-112. Elsevier.
  [doi:10.1016/B978-0-12-811689-0.00005-7](https://doi.org/10.1016/B978-0-12-811689-0.00005-7)
- Laverde-Barajas, M., et al. (2020). *ST-CORAbico: A Spatiotemporal Object-Based Bias
  Correction Method for Storm Prediction Detected by Satellite.* Remote Sensing 12(21),
  3538. [doi:10.3390/rs12213538](https://doi.org/10.3390/rs12213538)
- Laverde-Barajas, M., et al. (2020). *Climatology of monsoonal rainstorm events over
  the Lower Mekong Region.* AGU Fall Meeting poster.
  <https://studio.m-anage.com/agu/fm20/meetingapp.cgi/Paper/772134>
- Author's reference implementation
  ([ST-CORA v2.1.1](https://github.com/Servir-Mekong/ST-CORA), 483 lines), read in full
  and compared against the papers in `docs/findings.md` Findings 41-43. Not vendored
  here; cloned separately.

The original targets a catchment (the Tiete, then the Lower Mekong) over a monsoon
season. This targets a 5,200 km equatorial domain over 28 years. Most of the
differences below follow from that one change of scale.

---

## What is different, and why

Every claim here is measured. The finding number points at `docs/findings.md`, which
carries the command that produced each number.

### 1. Connected-component labelling percolates here. This is the central problem

At the papers' own 1 mm/h threshold, 3D connected-component labelling puts **90.1% of
all wet voxels into a single object** spanning the entire domain and the entire 5-day
test window. It is not a storm, it is the ITCZ. Sub-dividing the domain does not rescue
it: at 5x5 degrees the largest object still holds 70.3%. *(Findings 1-2)*

This is not a defect in the published work. ST-CORA was built for a 150,000 km2
catchment; percolation is what happens when the same level-set method meets a
near-continuously convecting maritime continent.

Checked against the author's own code, which defaults to 6-connectivity rather than the
26 the papers describe: the finding survives, 84.1% against 89.5%. *(Finding 41)*

### 2. The KDE segmentation could not have fixed it

The 2020 paper adds multivariate KDE segmentation to resolve "false merging". In the
author's implementation, `KED_segmentation` evaluates a Gaussian KDE over
`[y, x, z, rain]` and keeps the points above a density threshold, returning **one
filtered point set, not several labelled objects**. It erodes an object to its dense
core; it never splits one into many. *(Finding 42)*

So the published pipeline has no mechanism that would separate a percolated blob.

### 3. What replaced it: a merge tree

Instead of a level set, a **partition**. Every wet voxel is assigned to exactly one
storm, so no object can swallow the domain however connected the rain field is.

A merge tree of the superlevel-set filtration is built once per window; each local
maximum births a component, components merge at saddles, and a component's
**persistence** (birth minus death) is the intensity prominence of its peak. Cutting
the tree at a prominence `h` selects which maxima survive, and a watershed seeded on
those gives the spatial division.

| Method | Storms | Largest object | Rain captured |
|---|---|---|---|
| CCL at 1.0 mm/h (as published) | 3,378 | **90.1%** | 99.3% |
| CCL at 5.0 mm/h (de-percolated) | 2,045 | 22.0% | **18.7%** |
| **merge tree, h = 4.0** | **5,801** | **0.3%** | **95.5%** |

CCL faces a choice it cannot win: keep the rain and percolate, or de-percolate and
discard four fifths of it. The merge tree does both. *(Findings 15, 22-24)*

The tree also makes `h` cheap to sweep, because it is built once and cut many times:
8x faster than re-segmenting. *(Finding 24)*

### 4. What did not work

- **The tree's own segmentation distorts volumes.** Its natural "first touch" rule
  gives a shared skirt wholesale to one peak: two nearly equal peaks split 684/177
  voxels where a watershed gives 441/420. The tree supplies the hierarchy; a watershed
  supplies the geometry. *(Finding 23)*
- **`h` is not a stable parameter.** A plus-or-minus 20% change moves the storm count
  by 21% (December) and 20% (August), against a 10% stability criterion. There is no
  canonical storm count: `h` selects the scale of system counted. Captured volume, by
  contrast, is nearly h-invariant: an 8x change in `h` moves it 1.3% with the merge tree
  (4.0% with the watershed). Volume-based statistics are safe, count-based ones are not,
  and between-month ratios sit close to the safe end: two independent segmentations agree
  on the August/December ratio to within 0.006 while disagreeing on the count by 2.6x.
  *(Findings 19-20, 26-27)*
- **Per-storm return periods are near-meaningless at this granularity.** With 449,000
  storms a year, a 1-in-1-year storm is just the 28th largest in a 28-year record, and
  p99 corresponds to a return period of 0.0002 years. Severity bands are therefore
  stated as **exceedance rates** (storms per year), not percentiles or return periods.
  *(Findings 38, 40)*
- **Storm age in days is not a property a storm can have here.** Only 3 storms of
  12.45M last two days, because at `h = 4` an object is a convective cell. Age works at
  the **family** level instead, and families need a strict link rule: bounding-box
  overlap percolates exactly as CCL did. *(Findings 46-47)*
- **Climate region does not predict warning lead time.** All three derived regions give
  a median 3.5 h. Coastal geometry does predict it. *(Finding 53)*

### 5. Smaller departures

| | Original | Here | Why |
|---|---|---|---|
| Connectivity | 26 in papers, 6 in code | 26, and tested both | Difference is marginal *(41)* |
| Wet threshold | 1.0 mm/h (papers), 0.5 (code) | 1.0 mm/h, bounds analysis only | Separated from the splitting parameter |
| Segmentation | CCL + KDE | merge tree + watershed | Percolation *(15)* |
| Critical Mass Threshold | selection baked into detection | full population, CMT as a downstream filter | So it can change without a 9-hour rerun |
| Storm classification | k-means short/long-lived | 9-class severity on exceedance rates | Needs a reference population *(40)* |
| Track | skeleton of the 3D object | volume-weighted centroid per timestep | Robust, and gives velocity directly |
| Time base | local, GMT+7 | **UTC for segmentation, local for interpretation** | A time shift cannot change objects; it only moves chunk edges *(48-49)* |

---

## Data

**GPM IMERG Final Run, V07, half-hourly** (`GPM_3IMERGHH.07`), the gauge-calibrated
product, subset to Indonesia.

| | |
|---|---|
| Grid | 182 x 472 at 0.1 deg, lat -11.55 to 6.55 (**ascending**), lon 94.45 to 141.55 |
| Cadence | 48 steps per day, 30 minutes |
| Variable | `precipitation`, in **mm/hr**: an intensity, so depth per step is `R * 0.5` |
| Record | 1998-01-01 to **2025-09-30**; Final does not extend further |
| Volume | 10,135 daily files, about 35 GB |

Three ways to get it, behind one interface (`src/sources.py`), all producing the same
canonical daily layout:

- **`opendap`** (default) - NASA GES DISC over DAP4, subset server-side. 0.07 MB per
  granule. Needs a free [Earthdata Login](https://urs.earthdata.nasa.gov) in `~/.netrc`.
- **`local`** - a pre-downloaded archive. The only viable source for multi-year runs.
- **`gee`** - `NASA/GPM_L3/IMERG_V07`, stubbed.

Rejected after measurement: **THREDDS NCSS** is gone (HTTP 410); **Microsoft Planetary
Computer** serves V06, ends 2021-05-31, and chunks globally; **AWS S3** has no
server-side subsetting, so it moves about 100x more data than OPeNDAP for the same
result unless you are running inside us-west-2. *(Findings 6, 14, 32)*

Auxiliary geography is **Natural Earth 10m** (land, coastline, global admin-1), because
it is global and nothing needs rewriting if the AOI changes. An earlier
Indonesia-only administrative mask silently classified Malaysia, PNG and Timor-Leste as
sea. *(Finding 52)*

---

## Code

### Environment

`environment.yml` records the versions the results were produced with, so a future rerun
can tell whether a number moved because the science changed or because a library did.

```bash
conda env create -f environment.yml
conda activate hujan-badai
```

That file is a record first and an installer second: it has not been built from scratch,
because the development machine runs these under a pre-existing env named `climate`. The
package set is what matters, not the env name. Every command below assumes the repo root
as the working directory. Full command reference and the traps are in
[docs/runbook.md](docs/runbook.md).

```bash
python src/catalogue.py --start 2020-12-01 --end 2020-12-05
python src/build_year.py --year 1998 2025 --prominence 4
```

### Modules

| Module | Purpose |
|---|---|
| `config.py` | Paths, grid facts, source and product selection |
| `sources.py` | `LocalSource`, `OPeNDAPSource`, `GEESource`; one canonical cache layout |
| `imerg_io.py` | `load_range()`, the single entry point. Raises on missing days |
| `validate.py` | Archive integrity by NetCDF magic number; caches its verdict |
| `download.py` | Repair or extend the archive; OPeNDAP or whole-granule routes |
| `probe.py` | Diagnostics: wet fraction, object sizes, **percolation share** |
| `segment.py` | `label_ccl` (baseline) and `label_watershed` (second method) |
| `mergetree.py` | The merge tree. **`segment_at` is the one to use** |
| `storms.py` | The nine attributes per storm, vectorised |
| `catalogue.py` | One window to Parquet, with full provenance |
| `build_year.py` | Whole years, resumable, month-boundary padding |
| `sweep.py` | Parameter sensitivity, with a grid that can test its own criterion |
| `monthly.py` | Monthly totals, streamed, for picking wet and dry months by measurement |
| `climatology.py` | Multi-year load, seasonal cycle, return periods, concentration |
| `regions.py` | Regions derived from the catalogue's own seasonality |
| `severity.py` | Nine severity classes from a reference population |
| `families.py` | Storms linked into multi-day events, across month and year boundaries |
| `family_severity.py` | Severity with the event as the unit, and event ranking by area and window |
| `diurnal.py` | Land-sea diurnal cycle, in local time |
| `transition.py` | Sea-to-land crossings and warning lead time |
| `geo.py` | Natural Earth land, coastline, province and distance rasters |
| `export_site.py` | Small JSON summaries of the catalogue, for the published dashboard |

### Notebooks

| Notebook | Purpose | Needs |
|---|---|---|
| `01_storm_tracking.ipynb` | Rainfall to storms: pick a date range, segment, build a catalogue, map the tracks | Nothing but an Earthdata login. Fetches from NASA GES DISC with server-side subsetting, so no local archive is required. One month is the online ceiling |
| `02_climatology.ipynb` | What 13 million storms say: seasonal cycle, interannual variability, regions, severity, concentration, diurnal cycle, sea-to-land lead time, multi-day families | The multi-year catalogue, about 2.6 GB, built by `build_year.py`. Not reproducible from the online source in a session |

Both execute top to bottom in a fresh kernel, verified with `jupyter nbconvert
--execute`, and are committed with their outputs.

### Dashboard

<https://bennyistanto.github.io/hujan-badai/>

A static page in `site/`, plain HTML with Observable Plot and D3 from a CDN. No build
step and no server. It reads only the JSON files in `site/data/`, so a figure on the
page cannot drift away from the catalogue.

GitHub Actions publishes it; it does **not** compute it. The catalogue is 2.6 GB and is
not in the repository, and rebuilding it needs the IMERG archive and about nine hours,
so the numbers are exported locally and committed:

```bash
python src/export_site.py
python src/export_site.py --event-start 2019-12-30 --event-end 2020-01-02
```

The event window is re-segmented from the IMERG cube rather than read from the year
catalogues, because the page's detail panel needs each storm's half-hourly history and
the catalogue stores only whole-storm attributes. That part needs the local archive for
those few days; everything else comes from the catalogues.

That writes 15 files, about 900 KB, covering every panel. Commit `site/data/` and push;
the workflow validates that each file is present and parses before deploying.

---

## Output

### Per storm

Date and time, total volume (km3), duration, max intensity (peak voxel), centroid,
volume-weighted centroid, start location, end location, and the trackline as WKT, plus
max footprint, voxel count, substorms absorbed, and flags for truncation in space and
time.

Every row carries the parameters that produced it, including the prominence `h` and the
segmentation method, alongside the git revision and build timestamp. The two are
inseparable: merge tree and watershed give qualitatively different populations at the
same `h`, not just different counts. *(Finding 28)*

### Catalogues

`data/processed/catalogue_final_<year>_h4.parquet`, 28 files, 2.6 GB.

### Derived products

| File | Contents |
|---|---|
| `regions_k3.parquet` | Cells assigned to monsoonal / transitional / equatorial |
| `families_final_h4_g3_d50.parquet` | Multi-day storm events |
| `transitions_h4.parquet` | Sea-to-land crossings with lead times |
| `diurnal_h4.parquet` | Land and sea initiation by hour |
| `sweep-prominence-*.csv` | Parameter sensitivity, one file per method |
| `site/data/*.json` | The dashboard's data, about 900 KB, the only derived output committed to the repository |

### Headline results

- **December wettest (11.5% of annual rain), August driest (5.8%).** January is the
  *second* wettest over 28 years, though it ranked 9th of 12 in 2020 alone: one year
  cannot rank the months. These are pooled over complete years only. Pooling the
  partial 2025 as well, which Finding 37 did, gives 11.1% and 6.0% and understates the
  December-over-August ratio as 1.87x against 1.98x. *(Findings 37, 54)*
- **The domain average hides a 54x seasonal signal.** The monsoonal south varies
  54.5-fold between its wettest and driest month with each grid cell weighted equally,
  or 43.8-fold weighted by rainfall; domain-wide the figure is 1.87x, because the
  equatorial region is 69% of the volume and nearly aseasonal. The weighting has to be
  stated: it changes the transitional region's peak month from March to December.
  *(Findings 44, 55)*
- **A domain-wide severity scale is 9.5x biased**: 3.6 notable storms a year in the
  monsoonal region against 33.8 in the equatorial. *(Finding 45)*
- **Land storms peak 14-16 local, oceanic storms 22-24 local**, land amplitude 4.25x
  against sea 1.80x. The classic maritime-continent signal, recovered without being
  targeted, and the strongest available evidence that the objects are physically real.
  *(Finding 49)*
- **Every sea-formed storm offers lead time**, median 3.5 h over water before landfall,
  and **the largest storms offer most** (6.0 h median, 12.0 h p90). *(Finding 51)*
- **Lead time is set by coastal geometry, not climate.** Distance offshore at formation
  versus lead time: r = +0.877 across the 30 provinces with at least 1,000 sea-formed
  storms, or +0.836 across all 34. Riau gets 2.0 h facing the Malacca Strait; Maluku
  Utara gets 5.0 h facing open ocean. *(Findings 53, 56)*
- **Top 13% of storms carry 70.7% of the rain.** *(Finding 39)*
- **Event severity is undefined until the area and the window are fixed.** The Jakarta
  New Year 2020 flood is the largest 2-day total in 28 years over the catchment that
  flooded (1.74x the median annual maximum), and below an ordinary year over a region
  seven times larger or at a 7-day window. Both are correct, which is why the scale
  has to be quoted with the number. *(Finding 62)*

---

## What this is not

- **Not validated.** No gauge or radar comparison has been made. This is a catalogue,
  not a measurement of skill. Any statement of accuracy would be unsupported.
- **Not an impact product.** Detecting rain over a place is not evidence of flooding.
  Tested directly against the Jakarta flood of 2020-01-01: the storms over the city
  were in the top few percent of the 28-year population, the month was 182nd of 333
  nationally, and IMERG's peak 24 h reads about half what city gauges recorded. A
  per-storm catalogue is the wrong instrument for a flood. *(Findings 57-59)*
- **Not answerable by ranking objects at all.** Ranking linked events rather than
  individual cells moves the same flood from the 99.58th percentile to the 99.70th
  and leaves its class unchanged, because a linking rule tight enough to stop
  families percolating is too tight to assemble a four-day flood into one object.
  Ranking rainfall over an area and a window does identify it. *(Findings 61-62)*
- **Not transferable to the near-real-time runs without recalibration.** IMERG Late
  reads about 9% higher in total volume than Final. *(Finding 5)*
- **Not free of one arbitrary choice.** `h = 4.0` is a declared scale, not an optimum,
  because no optimum exists. Quote it, and the segmentation method, with every number.
- **Not a reproduction of ST-CORA.** The segmentation is different, and that difference
  is the point of section 3 above.

---

## Evidence

The project rule is: **measure it or cite it, never assert from memory.**

- [docs/findings.md](docs/findings.md) - 64 numbered findings, each with the command
  that produced it
- [docs/runbook.md](docs/runbook.md) - every command, and the traps
- [docs/sweep-prominence.md](docs/sweep-prominence.md) - the `h` parameter study

## License

See [LICENSE](LICENSE). IMERG data is courtesy of NASA/JAXA; Natural Earth is public
domain.
