# Method notes: measured properties of the IMERG Indonesia cube

> Every number here is reproducible. The command that produced it is given.
> Nothing in this file is asserted from memory. Append new measurements, do not
> overwrite old ones - a changed number is a finding.
>
> A few entries refer back to `temp/plan.md` and `temp/climatology-design.md`, the
> working drafts that framed a question before it was measured. Those are scratch, kept
> out of the published tree; the finding below each reference is the answer, and stands
> without them.

## Run 1 - 2026-09-26, baseline diagnostics

Command:

```
python src/probe.py --start 2020-01-01 --end 2020-01-05 --subregions --advection
```

### The archive

| Property | Value |
|---|---|
| Files | 9,131 daily NetCDF4, 2001-01-01 to 2025-12-31, no gaps in the date index |
| Per file | `precipitation(time: 48, lat: 182, lon: 472)` float32 |
| Units | **mm/hr** (an intensity, not a depth) |
| Grid | 0.1 deg, centre registered, lat -11.55 to 6.55 ascending, lon 94.45 to 141.5 |
| Cell area | 121.1 km2 at -11.55, 123.6 km2 at 0.0, 122.8 km2 at 6.55 |
| On disk | 30 GB |
| Full archive in memory as float32 | about 150 GB |
| Read speed | about 1.3 s per day cold |

Depth per half-hourly step is `R * 0.5` mm. A volume calculation that omits the 0.5
is wrong by a factor of two.

### Wetness, 2020-01-01 to 2020-01-05, full AOI

| Threshold | Fraction of voxels |
|---|---|
| 0.1 mm/h | 0.3217 |
| 0.5 mm/h | 0.2015 |
| 1.0 mm/h | 0.1350 |
| 2.0 mm/h | 0.0804 |
| 5.0 mm/h | 0.0260 |
| 10.0 mm/h | 0.0073 |

Total rain volume over the 5-day window and full AOI: 726.2 km3.
For scale, the critical mass threshold used over the Mekong was 0.01 km3.

### Finding 1: the published method percolates over this domain

3D connected-component labelling, 26-connectivity, as specified in Laverde-Barajas
et al. 2019. "Share" is the fraction of all wet voxels sitting inside the single
largest object.

| Threshold | n objects | largest object share | largest object duration |
|---|---|---|---|
| 0.1 mm/h | 9,990 | **97.7%** | 120.0 h (the whole window) |
| 0.5 mm/h | 11,944 | **94.9%** | 120.0 h |
| **1.0 mm/h** (the papers' value) | 10,606 | **90.1%** | 120.0 h |
| 2.0 mm/h | 8,732 | **76.2%** | 120.0 h |
| 5.0 mm/h | 5,867 | 19.1% | 86.5 h |
| 10.0 mm/h | 3,707 | 6.0% | 22.0 h |

At the papers' own threshold, one object contains 90% of the rain and spans the full
domain and the full window. It is not a storm. It is the ITCZ.

This is not a defect in the published work. ST-CORA was built for the Tiete catchment
(150,000 km2) and the Lower Mekong. This AOI is about 5,200 km wide across the
equator with near-continuous convection.

### Finding 2: domain decomposition does not rescue it

Threshold fixed at 1.0 mm/h.

| Domain | Voxels | Wet % | Largest object share |
|---|---|---|---|
| Full AOI | 20,616,960 | 13.5% | 90.1% |
| Java, 5x5 deg | 600,000 | 18.8% | **70.3%** |
| Jakarta, 2x2 deg | 96,000 | 20.6% | 27.1% |

Percolation persists down to 5x5 degrees. Only at about 2x2 degrees does it fall near
the usable range, and that is too small to hold a mesoscale system. So splitting the
AOI into catchments, as the papers do, is not sufficient here.

**Correction to an earlier estimate in session 1:** a first ad-hoc run using raw index
slices reported 24.2% for a "Java" box. That box was actually over Sumatra and the sea
at (-7.55 to -2.55, 100.45 to 105.45). The geographic Java box above is the correct
comparison. Use `src/probe.py`, not ad-hoc slicing.

### Finding 3: advection is mild here, so time connectivity is defensible

Frame-to-frame displacement by phase correlation over a Sumatra/Java window, 239 steps:

| Percentile | cells / 30 min | km/h | m/s |
|---|---|---|---|
| p50 | 0.00 | 0.0 | 0.0 |
| p90 | 1.00 | 22.3 | 6.2 |
| p99 | 1.00 | 22.3 | 6.2 |

Fraction of steps exceeding 1 cell: 0.008. Fraction exceeding sqrt(3) cells, the
26-connectivity diagonal limit: 0.000.

So a 26-neighbour system in space and time does **not** obviously break at 0.1 deg /
30 min over this domain. This contradicts the first hypothesis of the session, which
was that advection would be the main failure mode. It is not. Percolation is.

**Caveat that must travel with this number:** domain-scale phase correlation is
dominated by the largest-amplitude feature in the window and is quantised to whole
grid cells, so sub-cell motion reads as zero and a single fast-moving cell embedded in
a slow field will not appear. This is evidence about the bulk field. It is not proof
that every storm is slow. A per-object velocity check after segmentation would settle
it properly.

## Open measurements, not yet done

- [ ] Wet/dry season contrast: repeat all of the above for a July window.
- [ ] Threshold sensitivity of the storm count with segmentation in place.
- [ ] Per-object velocity distribution, to close out the Finding 3 caveat.
- [ ] Diurnal cycle in local time (UTC+7/8/9), and whether it aliases into storm duration.
- [ ] Full-archive integrity pass: time steps per file, grid drift across 25 years.

## Run 2 - 2026-09-26, single-day check

Command:

```
python src/probe.py --start 2020-01-10 --end 2020-01-10 --thresholds 1.0 5.0
```

| Threshold | n objects | largest object share | largest duration |
|---|---|---|---|
| 1.0 mm/h | 2,405 | 74.7% | 24.0 h (whole window) |
| 5.0 mm/h | 1,199 | **40.9%** | 24.0 h |

### Finding 4: the percolation metric is window-length sensitive

Run 1 gave 19.1% at 5 mm/h over a 5-day window. This single-day window gives 40.9% at
the same threshold. The largest-object share is a ratio against total wet voxels in the
window, so a shorter window inflates it, and in both cases the largest object spans the
entire window, meaning it is truncated by the window edge rather than by its own decay.

Two consequences:

1. **The fallback option in `temp/plan.md` is weaker than it looked.** Raising the
   threshold to 5 mm/h does not reliably de-percolate the full AOI. The 19.1% figure
   was window-specific, not a property of the threshold.
2. **The metric needs a companion.** Largest-object share should always be reported
   alongside the largest object's duration as a fraction of the window. When that is
   1.0, the object is window-truncated and the share is a lower bound on how bad the
   percolation actually is.

Neither changes the main conclusion, which it reinforces: no single global level set
separates storms over this domain. It does mean the baseline comparison method has to
be chosen more carefully, and that all percolation numbers must state the window.

## Run 3 - 2026-09-26, data sources

Scripts: `src/sources.py`, `src/imerg_io.py`. Cross-check driver kept in the scratchpad.

### Finding 5: the local archive is IMERG **Late**, not Final

The folder `GPM_3IMERGHHL_07_subset_halfhourly` was described as Final. Its own
`FileHeader` says otherwise:

```
DOI            = 10.5067/GPM/IMERG/3B-HH-L/07
DOIshortName   = 3IMERGHH_LATE
ProductVersion = V07B
GenerationDateTime = 2024-06-11T07:53:16Z
```

The `L` in `GPM_3IMERGHHL` is the run. CMR confirms three distinct V07 collections:
`GPM_3IMERGHH` (Final), `GPM_3IMERGHHE` (Early), `GPM_3IMERGHHL` (Late).

Measured difference for 2020-01-01 over the AOI, Final versus the local Late archive:
**-8.40% in total**, with 33.0% of cells differing by more than 1e-4 mm/hr. Late is not
gauge calibrated; Final is. These are different products, not different packagings.

### Finding 6: online sources, checked rather than assumed

| Source | Version | Coverage | Verdict |
|---|---|---|---|
| **NASA GES DISC / Earthdata OPeNDAP** | V07, all three runs | full record | **Use this.** Server-side subsetting, works with the existing `~/.netrc` |
| **Google Earth Engine** `NASA/GPM_L3/IMERG_V07` | V07, band `precipitation` | 1998-01-01 to 2026-09-25 | Viable, and the only current one. But GEE is for server-side reduction, and this method needs the cube client-side |
| **Microsoft Planetary Computer** `gpm-imerg-hhr` | **V06**, variable `precipitationCal` | 2000-06-01 to **2021-05-31** | **Rejected.** Wrong version, ends 2021, and Zarr chunks are [12, 3600, 1800] so any subset pulls whole global slabs |

OPeNDAP transfer, one timestep over the AOI:

| Request | Bytes | Time |
|---|---|---|
| Full global granule | 25.9 MB | 25.1 s |
| AOI subset, raw DAP4 | 0.346 MB | 5.1 s |
| AOI subset, `.dap.nc4` | 0.081 MB | 4.1 s |

Subsetting saves 75x bytes; asking for netCDF4 rather than raw DAP4 saves another 4x.
A day is 48 granules, about 16 s with 8 workers. **The full 2001-2025 record would be
about 620 hours served serially, so online is for the notebook and MVP windows, and the
local archive is for the climatology.** The cache makes reruns free.

Grid alignment is exact: global indices `lat[784:965]`, `lon[2744:3215]` reproduce the
local 182 x 472 grid with residuals at float32 precision (max 9.2e-06 deg).

### Finding 7: the local archive has drifted from the authoritative product

Fetching the matching run (Late) online and comparing to the local archive for
2020-01-01: **42 of 48 half-hours are identical**, 6 differ (00:30, 01:30, 02:00, 02:30,
03:00, 03:30 UTC), total differs by +0.53%.

What is established: the local file's `GenerationDateTime` is 2024-06-11, three days
before the server granules' `ProductionDateTime` of 2024-06-14, so the local subset was
built from an earlier production and 6 half-hours changed between the two.

What is **not** established: why only those 6. The CMR `ProductionDateTime` is identical
(2024-06-14) for both the matching and the differing granules, so a simple "these were
reprocessed and those were not" story does not fit the metadata. Do not assert it.

Practical consequence: a local archive is a snapshot that can silently diverge from the
product it claims to be. This is an argument for the online source as the default and
for recording the granule production date in the catalogue.

### Finding 8: a decode bug that the cross-check caught

The first OPeNDAP implementation hand-decoded the raw DAP4 binary, guessing the payload
byte offset and validating the guess with `np.isfinite`. That check is worthless here
because the fill value -9999.9 is finite, so a wrong offset returned plausible garbage:
48 timesteps decoded into only 2 distinct fields while the domain total still looked
about right. Replaced by requesting `.dap.nc4` and letting netCDF4 parse a real file,
plus an explicit assertion that the day's frames are distinct.

The lesson generalises: **a domain-total check would have passed.** Only the cell-by-cell
comparison against an independent copy of the same product caught it.

## Run 4 - 2026-09-26, the Final archive

```
.\run.ps1 src\probe.py --start 2020-01-01 --end 2020-01-05 --source local --subregions
```

### Finding 9: the Final archive, located and verified

`I:\My Drive\hybrid-bias-correction\data\downloads\GPM_3IMERGHH_07_subset_halfhourly`

```
DOI            = 10.5067/GPM/IMERG/3B-HH/07
DOIshortName   = 3IMERGHH                     <- Final
ProductVersion = V07B
GenerationDateTime = 2024-10-28T20:01:32Z
```

10,135 daily files, **1998-01-01 to 2025-09-30, zero missing days**. Same 182 x 472 grid,
same `precipitation` variable in mm/hr. This is a longer record than the Late archive
(27.7 years vs 25) because V07 extends back into the TRMM era.

`config.PRODUCT` now defaults to `final`, and `config.LOCAL_ARCHIVES` maps each run to
its own directory and glob. The cache is keyed by run so the two can never collide.

### Finding 10: percolation is robust across runs

Same window, Final rather than Late:

| Threshold | n objects | largest share (Final) | largest share (Late) |
|---|---|---|---|
| 1.0 mm/h | 12,427 | **89.5%** | 90.1% |
| 2.0 mm/h | 9,965 | 27.9% | 76.2% |
| 5.0 mm/h | 6,604 | 21.6% | 19.1% |
| 10.0 mm/h | 3,746 | 7.7% | 6.0% |

Java 5x5 deg at 1 mm/h: 58.9% (Final) against 70.3% (Late). The central conclusion does
not depend on which run is used.

Total volume over the 5-day window: **666.8 km3 (Final)** against 726.2 km3 (Late), so
Late is 8.9% higher, consistent with the -8.40% measured on the single day.

### Finding 11: a concat bug, caught by running the probe

First run on the Final archive returned a cube of (240, **364**, **944**) at 75% NaN and
a volume of NaN. Cause: `xr.concat` defaults to `join="outer"`, and daily files in this
archive carry lat/lon values that differ in their last float bits, so the union doubled
the grid. Per-day validation passed because each day really was 182 x 472; the range-level
check only looked at the time length.

Fixed with `join="override", compat="override", coords="minimal"`, and `_validate_range`
now asserts the post-concat spatial shape and rejects a NaN fraction above 50%.

Note the implication for the archive itself: **coordinate values are not bit-identical
across daily files.** The `data-validator` grid-stability check should quantify this over
the full record.

### Finding 12: local Final and online Final disagree on a few half-hours, unexplained

Comparing the local Final archive against the authoritative online Final, cell by cell:

| Date | timesteps differing | cells differing | total difference |
|---|---|---|---|
| 2020-01-01 | 6 of 48 | 4.37% | +0.308% |
| 2015-06-15 | 5 of 48 | 2.41% | -0.510% |
| 2024-03-07 | 7 of 48 | 7.00% | +0.173% |

The differing steps always fall in the first eight (00:00 to 03:30 UTC); steps 8 to 47
are identical on every date tested.

Ruled out:
- **My granule ordering.** Checked each CMR URL's embedded timestamp against the assumed
  slot: 0 mismatches in 48.
- **A time shift.** Searched a 3-day online window for an exact twin of each differing
  local frame. None found, so it is not a permutation.
- **A product mismatch.** Both are Final by DOI.

Not established: why. Do not invent a reason in any write-up. It is under 1% of daily
volume but it is a real integrity question, and it is a task for `data-validator` to
characterise over a proper sample before the climatology runs.

## Run 5 - 2026-09-27, AWS S3 evaluated, archives relocated

### Finding 13: both archives live on `I:`, and Late is longer than the `F:` copy

| Run | Path (under `I:\My Drive\hybrid-bias-correction\data\downloads`) | Days |
|---|---|---|
| final | `GPM_3IMERGHH_07_subset_halfhourly` | 10,135 (1998-01-01 to 2025-09-30) |
| late | `GPM_3IMERGHHL_07_subset_halfhourly` | 10,227 |

The `F:` copy of Late held 9,131 days, so it was a partial copy. `config.LOCAL_ARCHIVES`
now points at `I:` for both.

Sibling `*_extract_halfhourly` folders hold `idn_cli_imerg_hh_rate_YYYYMMDD.nc4` from
another pipeline. xarray's installed backends cannot open them. Not used here.

### Finding 14: AWS S3 is the wrong route for a regional AOI, quantified

`https://registry.opendata.aws/nasa-gpm3imerghh/` resolves to:

```
ARN:           arn:aws:s3:::gesdisc-cumulus-prod-protected/GPM_L3/GPM_3IMERGHH.07/
Region:        us-west-2
RequesterPays: false
```

`https://data.gesdisc.earthdata.nasa.gov/s3credentials` works with the existing
`~/.netrc` and returns `accessKeyId`, `secretAccessKey`, `sessionToken`, with an
expiration about one hour out.

S3 has no server-side subsetting, so the question is whether HDF5 byte-range reads can
fetch only the AOI. Measured from a real granule:

```
precipitation  shape (1, 3600, 1800) float32, gzip level 6
               chunks (1, 145, 1800)     <- 145 lon cells x ALL 1800 lat
               25 chunks total, 1.04 MB uncompressed each
full granule over HTTPS: 7.55 MB compressed, 6.7 s
```

The AOI spans lon indices 2744-3215, which touches **5 of 25 chunks**, so a perfect
byte-range read still pulls about 20% of the granule, roughly 1.5 MB compressed. Chunks
span the full latitude band, so Indonesia's narrow latitude range buys nothing.

| Route | Bytes per timestep | Ratio vs OPeNDAP |
|---|---|---|
| **OPeNDAP `.dap.nc4` subset** | **0.081 MB** | 1x |
| S3 byte-range, 5 of 25 chunks | about 1.5 MB | 19x worse |
| S3 or HTTPS full granule | 7.55 MB | 93x worse |

Wall clock is closer than bytes suggest (6.7 s for a full granule against 4.1 s for an
OPeNDAP subset), because Hyrax pays server-side decompression and subsetting latency.
But for one day OPeNDAP is both smaller and faster: 3.9 MB and about 16 s with 8 workers,
against 362 MB and about 40 s for full granules.

**Verdict: keep OPeNDAP. S3 only pays off if the processing itself moves into us-west-2**,
where egress disappears and Hyrax latency is bypassed. `boto3` and `s3fs` are not
installed, so no S3 read was actually performed; this conclusion rests on the chunk
layout and the transfer sizes above, which were measured.

## Run 6 - 2026-09-27, the proposed method works

```
python src/catalogue.py --start 2020-01-01 --end 2020-01-05 --source local --product final
```

Attribute definitions pinned by the user: **max intensity = peak voxel**,
**start location = volume-weighted centroid of the first timestep**.

### Finding 15: watershed de-percolates without throwing away the rain

Same 5-day window and cube, IMERG Final. "largest" is the share of labelled voxels in the
single biggest object; "captured" is the share of voxels >= 1 mm/h that landed in a storm.

| Method | storms | largest | captured | sec |
|---|---|---|---|---|
| CCL thr=1.0 (as published) | 3,378 | **90.1%** | 99.3% | 0.7 |
| CCL thr=5.0 (de-percolated) | 2,045 | 22.0% | **18.7%** | 0.6 |
| watershed h=1.0 | 17,497 | **0.2%** | 97.7% | 24.1 |
| watershed h=2.0 | 11,017 | 0.3% | 96.9% | 22.7 |
| **watershed h=4.0** | **5,801** | **0.3%** | **95.5%** | 21.9 |
| watershed h=8.0 | 2,381 | 0.4% | 93.5% | 21.5 |

This is the central result. CCL forces a choice that cannot be won: keep the rain and
percolate (99.3% captured, 90.1% in one blob), or de-percolate and discard four fifths of
it (22.0% largest, only 18.7% captured). The watershed does both at once, at every h
tested: percolation share never exceeds 0.4% while capture stays above 93%.

Cost is about 22 s for 5 days, so roughly 2 minutes for a month. Acceptable.

### Finding 16: h is not a stable parameter, and no h-independent storm count exists

The storm count roughly halves for each doubling of h: 17,497 at h=1, 11,017 at h=2,
5,801 at h=4, 2,381 at h=8. Between h=2 and h=4 the count drops 47%.

This **fails** the stability criterion written into `/sweep` (a plus or minus 20% change
should move the count by under 10%), and it moderates the optimistic framing in
`temp/plan.md`, which suggested persistence would make the count a property of the rain
rather than of the parameter. On this data it does not.

The honest reading: storm identity over the maritime continent is genuinely
scale-dependent, and h selects the scale. What is robust is the **percolation share**,
which sits at 0.2-0.4% across the whole range, and the **captured fraction**, 93-98%. So
the method reliably solves the problem it was chosen for; it does not deliver a canonical
storm count, and nothing should be written as though it does.

This strengthens the case for actually implementing the merge tree, which would express
the hierarchy honestly instead of forcing a single h to stand for the truth.

### Finding 17: catalogue sanity on the h=4.0 run

5,801 storms, 557.9 km3 captured of the 666.8 km3 falling in the window (83.7%; the
remainder is below the 1 mm/h wet threshold). 328 storms truncated in time, 402 in space.

Duration: median 5.5 h, p90 10.5 h, p99 16.0 h, max 24.5 h. The largest systems reach
42,000-79,000 km2 and 1.5-2.7 km3, which is the mesoscale range and physically plausible
for this region. None of this is validated against observations, by scope decision.

### Verification of the attribute code

Checked on a synthetic cube with a known answer: a 3x3 blob at 10 mm/hr drifting one cell
east per step over 5 steps. Duration, voxel count, peak intensity, start and end centroid
positions and total volume all matched the analytic expectation exactly, the last to six
significant figures. A second test confirmed the watershed separates two touching Gaussian
cores that CCL merges into one object.

## Run 7 - 2026-09-27, monthly climatology, to pick sweep months by measurement

```
python src/monthly.py --year 2020 --source local --product final --out temp/daily_2020.csv
```

Streams one day at a time, so it never holds more than a day in memory. 366 days, about
30 minutes against the `I:` archive (roughly 5 s/day; the `F:` drive managed 1.3 s/day, so
Google Drive File Stream is the bottleneck, not the code).

### Finding 18: January is not the wet month for this domain

AOI-wide rain volume by month, 2020, IMERG Final:

| Month | km3 | Rank |
|---|---|---|
| **12 Dec** | **3,118** | **1, wettest** |
| 05 May | 2,859 | 2 |
| 11 Nov | 2,715 | 3 |
| 06 Jun | 2,557 | 4 |
| 03 Mar | 2,542 | 5 |
| 07 Jul | 2,409 | 6 |
| 10 Oct | 2,373 | 7 |
| 04 Apr | 2,314 | 8 |
| **01 Jan** | **2,258** | **9** |
| 02 Feb | 2,267 | 10 (by daily mean, 29 days) |
| 09 Sep | 2,199 | 11 |
| **08 Aug** | **1,648** | **12, driest** |

Two things here matter.

**A DJF assumption would have picked the wrong month.** January ranks 9th of 12 domain-wide.
Had the sweep been run on "January as the wet month", as the earlier plan suggested for the
MVP, it would have been run on a middling month while calling it wet. The wettest and driest
months are **December and August**, and the sweep uses those.

**The seasonal contrast is weak: 1.89x between the extreme months.** This is the multiple
rainfall regimes of the maritime continent cancelling in a domain average. When the
monsoonal south is dry, equatorial and anti-monsoonal regions are not. May being the second
wettest month is the same effect.

Consequences to carry forward:

- A domain-wide storm climatology blurs regimes that a regional one would separate. Any
  seasonal statement about "Indonesian storms" from this catalogue needs either a regional
  breakdown or an explicit statement that it is a domain aggregate.
- Wet-versus-dry is a weak axis for testing the method's seasonal sensitivity here. A
  1.89x volume ratio is a mild contrast, so a sweep showing little seasonal difference is
  weak evidence of robustness, not strong evidence.
- August carries the highest single-voxel intensity of the year at 119.49 mm/hr despite
  being the driest month, so intensity and volume do not rank together.

## Run 8 - 2026-09-27, the h sweep

```
.\run.ps1 src\sweep.py --months 2020-12 2020-08 --source local --product final
```

Full narrative and tables in `docs/sweep-prominence.md`, raw numbers in
`data/processed/sweep-prominence-watershed.csv`. Headlines only here.

### Finding 19: h is definitively unstable, measured across two seasons

Across the full -20% to +20% span around h = 4.0, the storm count moves **-37.7%** in
December and **-36.4%** in August. The criterion is 10%. The two months agree to within
1.3 percentage points, so it is a property of the method, not the weather. An 8x change
in h moves the count 8.3x.

The earlier default h grid (1, 2, 3, 4, 6, 8, 12) could not have decided this: every
step exceeds 25% while the criterion is defined at 20%. The 3.2 and 4.8 points exist
solely to make the test possible. A sweep grid that cannot evaluate its own criterion is
a silent failure, and this one nearly shipped.

### Finding 20: captured volume is h-invariant, which is the useful stability

| Month | h=1.0 | h=8.0 | change |
|---|---|---|---|
| December | 2,594.2 km3 | 2,489.6 km3 | **-4.0%** |
| August | 1,393.1 km3 | 1,333.0 km3 | **-4.3%** |

An 8x change in h moves the captured volume by about 4%. This follows from the method
being a partition: h decides where internal boundaries fall, not which voxels belong to
a storm at all.

**Practical rule: volume-based statistics are safe against the choice of h. Count-based
statistics are not.** Between-month ratios sit in between, drifting 11% (0.579 to 0.644)
across the full range, so comparative statements survive far better than absolute ones.

Percolation stays between 0.0004 and 0.0044 everywhere, against 0.90 for CCL at the
published threshold. The problem the method was chosen for is solved robustly.

### Finding 21: h = 4.0 adopted as a scale, not an optimum

p95 max area near 20,000 km2 and p95 duration 11-12 h, which is the mesoscale convective
system range. Capture 93-94%, truncation about 10%. There is no optimum because the
count never stabilises, so this is a declared choice and must be quoted with every
number taken from a catalogue.

### Caveat on the seasonal axis

December to August is only a 1.89x volume ratio (Finding 18), because Indonesia's
rainfall regimes partly cancel in a domain average. The close agreement between the two
months is therefore **weak** evidence of seasonal robustness, not strong evidence. A
regional breakdown would test it properly. One year only; nothing here speaks to
interannual stability.

## Run 9 - 2026-09-27, the merge tree

`src/mergetree.py`. Union-find sweep over voxels in descending intensity, jitted with
numba. Components are born at local maxima and die at the saddle where they merge into
something stronger; persistence is `birth - death`.

### Finding 22: the tree is topologically exact

Synthetic check, two Gaussian peaks of 13.2 and 9.2 mm/hr joined over a saddle at 1.205:
the shorter peak's persistence should be 9.2 - 1.205 = **7.995**. The tree reports
**7.995**. Cutting at h below that gives 2 objects, above it gives 1.

### Finding 23: the tree's own segmentation is unusable for a catalogue

The natural "first touch" rule, where each voxel joins the component that reached it
first in the descending sweep, is topologically correct but a bad **spatial** partition.
On two nearly equal peaks (10.0 and 9.5 mm/hr):

| Rule | Voxel split |
|---|---|
| first touch (`cut_topological`) | **684 / 177** |
| watershed | 441 / 420 |

The whole shared skirt goes to whichever peak the sweep reached first, so volumes would
be wrong by a factor of several. This was caught only because the synthetic case had a
known fair answer.

**Architecture that resolves it**: use the tree for *which maxima survive at h* and for
the hierarchy, and a watershed seeded on those maxima for the spatial division.
`segment_at` does this and reproduces the direct watershed exactly on the synthetic case
(441/420) and to **98.7-98.9%** on real data, by both voxel agreement and by the volumes
of the 200 largest storms.

`cut_topological` is kept, clearly documented as unsuitable for measuring rain.

### Finding 24: sweeping h is 8x cheaper from a prebuilt tree

2-day cube, 24,814 components, tree built in 0.7 s.

| | 6 values of h |
|---|---|
| via prebuilt tree | 5.5 s + 0.7 s build |
| re-segmenting each time | 50.1 s |

The expensive part of `label_watershed` is the h-maxima morphological reconstruction,
which the tree replaces with a lookup.

### Finding 25: seed counts differ from skimage h-maxima, increasingly with h

At the same h, `segment_at` yields more objects than `label_watershed`: 4,908 vs 4,510
at h=2, 3,228 vs 2,414 at h=4, 2,061 vs 974 at h=8. The boundaries agree to 98.8%, so
this is a difference in *which maxima survive*, not in where the divisions fall.
`h_maxima` takes regional maxima of the h-reconstruction, which can merge peaks that are
close in value even when the saddle between them is deep; the tree's criterion is the
cleaner one, being persistence against the actual joining saddle.

**Consequence: counts from the two methods are not interchangeable.** The sweep in
Run 8 used `label_watershed`, so its counts are specific to that method. Do not compare
them against merge-tree counts. Volume-based numbers are unaffected, consistent with
Finding 20.

### Catalogue integration

`catalogue.build(..., method="mergetree")` is now the default. It adds `n_substorms` and
`max_substorm_persistence`: the components folded into each surviving storm at this h,
which is a scale indicator for how much a storm would fragment at a lower prominence.

## Run 10 - 2026-09-27, the sweep rerun with the merge tree

Full narrative in `docs/sweep-prominence.md` Run 2; raw numbers in
`data/processed/sweep-prominence-mergetree.csv`.

### Finding 26: the merge tree halves the parameter sensitivity

Across the full -20% to +20% span around h = 4.0:

| Method | December | August |
|---|---|---|
| watershed (Run 8) | -37.7% | -36.4% |
| **merge tree** | **-21.1%** | **-19.7%** |

Still UNSTABLE against the 10% criterion, so Finding 19 stands, but the tree's
persistence criterion is about twice as well behaved as skimage's h-maxima. Volume drift
across an 8x change in h also improves, from -4.0% to **-1.3%** (December), and the
captured fraction at h=8 holds at 0.954 against the watershed's 0.907.

The tree is preferred on every axis measured: half the sensitivity, a third of the
volume drift, higher capture, and about 3x faster to sweep (46-82 s per h against
133-213 s, after a one-off 13 s tree build per month).

### Finding 27: between-month ratios are method-independent

August divided by December, two independently implemented segmentations:

| h | watershed | merge tree | difference |
|---|---|---|---|
| 1.0 | 0.579 | 0.577 | 0.002 |
| 4.0 | 0.627 | 0.621 | 0.006 |
| 8.0 | 0.644 | 0.642 | 0.002 |

They agree to within 0.006 at every h while disagreeing on the absolute count by up to
2.6x. This is the strongest evidence yet that **comparative statistics are the robust
ones**, and it turns Finding 20's practical rule into a measured result rather than an
inference from the partition argument.

### Finding 28: the two methods yield different populations, not just different counts

At h = 8.0 in December: merge tree 29,017 storms with median volume 0.0039 km3;
watershed 11,118 with median 0.1072 km3. The tree's median volume is also
**non-monotonic** in h (0.0079, 0.0105, 0.0115, 0.0107, 0.0090, 0.0039) where the
watershed's rose steadily. p95 volume rises monotonically for both, so the divergence is
entirely at the small end.

Reading: as h rises the tree absorbs weak peaks into strong neighbours, removing
mid-sized storms from the population, while small isolated peaks with no stronger
neighbour survive unchanged; the median falls even as the big systems grow. The
watershed merges more aggressively and leaves a coarser population.

**"h = 4" does not mean the same thing to the two methods.** Record the segmentation
alongside h on every catalogue. This sharpens Finding 25 from "counts are not
interchangeable" to "the storm populations are qualitatively different".

## Run 11 - 2026-09-27, New Year 2019/2020 test period

```
.\run.ps1 src\catalogue.py --start 2019-12-30 --end 2020-01-02 --source local --product final --method mergetree --prominence 4
```

### Finding 29: the loader crosses the year boundary correctly

2019-12-30 to 2020-01-02 spans a calendar year change, which is where a date-indexed
file loader usually breaks. It did not: 192 timesteps over 4 days, uniform 30-minute
step asserted across the 2019/2020 boundary, no gaps.

### Catalogue, h = 4.0

| | |
|---|---|
| storms | 5,711 |
| total captured volume | 375.4 km3 |
| percolation share | 0.0042 |
| duration | median 4.0 h, p90 9.0 h, max 24.5 h |
| truncated | 420 in time, 342 in space (13.3% of the catalogue) |

At h = 12.0, the setting used for the explorer, the same window gives 1,690 storms, the
largest of which is 6.77 km3 over 14.5 h with a peak of 38.5 mm/hr, centred near
5.1 N 140.1 E.

For scale against the earlier 3-day December 2020 window (1,281 storms at h=12): this
4-day window has 1,690, so about 422 per day against 427. The two periods are close in
storm production per day despite being a year apart.

No claim is made here about any particular flood or impact. Linking storms to impact
needs an impact database and is out of scope (see `temp/plan.md`).

## Run 12 - 2026-09-27, the 2020 reference catalogue and a replication attempt

```
.\run.ps1 src\build_year.py --year 2020 --prominence 4 --source local --product final
```

421,526 storms, 24,303 km3, 92.3% untruncated, **16 minutes for a year**. So the full
1998-2025 archive is about **7.4 hours**, confirming the earlier estimate.

Population at h = 4.0: volume p50 0.0093, p99 0.581, max 5.70 km3; max intensity p50 8.0,
p99 40.0, max 119.5 mm/hr.

### Finding 30: the AGU 2020 poster does not contain the severity scheme

`LaverdeM_PosterAGU2020_...pdf` is the "Laverde-Barajas et al. (2020)" cited by the
SERVIR Storm Tracker manual for storm severity. Read in full, it contains:

- IMERG **Final**, monsoon seasons **Jun-Oct 2014-2019**, so 6 seasons
- **1,730 storms**: 1,500 short-lived (87%), 230 long-lived (13%)
- classification into short-lived and long-lived by **k-means only**
- headline: long-lived events are 13% of the population but contribute **>97%** of
  monsoon rainfall

There is **no nine-level severity scheme, no return-period axes and no thresholds** in
this poster, nor in either other paper. The manual's nine levels are an operational
addition to the web system whose bin edges are not published in anything held here.

Consequence: we may adopt the structure and cite the concept, but every threshold is
ours. Never write "the Laverde-Barajas classification" for our output.

### Finding 31: their headline statistic is largely a scale effect

Replicating as closely as the data allows, on the full 2020 Indonesian catalogue with
their Critical Mass Threshold applied (volume >= 0.01 km3 and max intensity >= 10 mm/h,
from the 2020 Remote Sensing paper) and their k-means split on duration, extent,
intensity and volume:

| | Poster (Lower Mekong) | Here (Indonesia, 2020, h=4) |
|---|---|---|
| long-lived share of population | 13% | **20.2%** |
| long-lived share of rainfall | **>97%** | **59.0%** |

The gap is not a contradiction. Their catalogue holds about **97 storms per million km2
per month**; ours at h = 4.0 holds about **1,376**, roughly 14x finer. Concentration of
rainfall into the largest objects depends directly on how finely the field is
partitioned.

Tested by cutting one merge tree (December 2020) at a range of prominences:

| h | storms per Mkm2 per month | mean volume km3 | mean duration h | top 13% share of rain |
|---|---|---|---|---|
| 4 | 1,571 | 0.141 | 7.4 | 46.6% |
| 8 | 957 | 0.238 | 9.1 | 48.2% |
| 16 | 327 | 0.578 | 12.0 | 53.2% |
| **32** | **105** | **0.911** | **11.8** | **82.8%** |
| 64 | 84 | 0.215 | 9.0 | 67.3% |

**At h = 32 the storm density matches the poster's ~97 per Mkm2 per month almost
exactly, and mean volume and mean duration both land inside the poster's reported ranges
(0.4-2.3 km3, 9-13 h), while the concentration rises to 82.8%.** Matching their
granularity largely reproduces their population statistics.

h = 64 breaks the trend at 67.3%. With only 715 storms the statistic is noisy and very
few maxima survive, so the partition behaves erratically. Reported rather than smoothed.

What this supports: **"a small minority of storms carries almost all the rain" is
substantially a statement about partition granularity, not purely about the atmosphere.**
Any such figure must be quoted with the storm density that produced it.

What it does not support: that the poster is wrong. This is one month, one domain, and
our segmentation differs from theirs in more than h. The claim is that storm density is
the controlling variable, not that their number is an error.

It also answers an open question from `temp/climatology-design.md`: if comparability with
the published Mekong work matters, **h near 32 reproduces their granularity**, while
h = 4 remains right for resolving individual convective systems.

## Run 13 - 2026-09-27, archive repair: routes and limits

### Finding 32: THREDDS NCSS is gone; OPeNDAP is not

The acquisition notebook used GES DISC THREDDS NCSS. It now answers **HTTP 410**
with an HTML body, so it cannot repair anything.

Measured alternatives, one granule each:

| Route | Bytes | Time | Status |
|---|---|---|---|
| THREDDS NCSS | - | - | **410 Gone** |
| OPeNDAP (Earthdata Cloud Hyrax) | 0.070 MB | 4.8 s | works |
| Full global granule over HTTPS | 8.1 MB | 5.9 s | works |

OPeNDAP moves about 100x less data for the same result, because both routes cut on
the same global indices `lat[784:965]`, `lon[2744:3215]`. `src/download.py`
implements both (`--route opendap|global`), defaulting to OPeNDAP.

### Finding 33: IMERG Final V07 ends 2025-09-30. October to December 2025 do not exist

CMR collection metadata for `GPM_3IMERGHH` v07 gives a temporal extent of
**1998-01-01 to 2025-09-30**, and granule counts confirm it:

| Month | Final | Late | Early |
|---|---|---|---|
| 2025-08 | 1488 | 1488 | 1488 |
| 2025-09 | 1440 | 1440 | 1440 |
| **2025-10** | **0** | 1488 | 1488 |
| 2025-11 | 0 | 1440 | 1440 |
| 2025-12 | 0 | 1488 | 1488 |
| 2026-06 | 0 | 1440 | 1440 |

The local archive ending 2025-09-30 is therefore **not an incomplete download**: it
is the edge of the product. Late and Early are ongoing.

A complete calendar year 2025 is not possible in Final. Filling Oct-Dec from Late
would mix products, and Late reads about 9% higher in total volume than Final
(Finding 5), which is larger than most effects this project tries to detect. Either
accept 2025 as a 9-month year, or build 2025 wholly from Late and label it.

All 20 unreadable days **are** repairable: 2022-05-12 and the 19 in 2025-09 all
exist in Final.

### Finding 34: repaired days will differ slightly from their neighbours

Re-fetching 2020-06-01, a day the archive already holds, reproduces the grid exactly
(lat/lon to float32 precision) but differs in **6 of 48 timesteps, all within the
first eight UTC steps**, with the daily total +1.32%.

This is the Finding 12 pattern again, now seen from the other direction: the archive
is an older snapshot than what the server currently serves. Repaired days will carry
the current version while their neighbours carry the older one.

The inconsistency is real but small, and the alternative is leaving the days
unreadable. Record which days were repaired and when.

### Also fixed

`OPeNDAPSource._fetch_nc` accepted any HTTP 200 and handed the body to netCDF4. A
200 carrying an HTML error page surfaced only as "NetCDF: Unknown file format" and
killed a whole day. It now checks the HDF5 magic and retries three times.

## Run 14 - 2026-09-27, repair executed and the overlap fix tested

### Archive repaired

All **20 unreadable days repaired** via OPeNDAP into
`G:\temp\imerg\GPM_3IMERGHH_07_subset_halfhourly`, each verified as
(48, 182, 472) and readable. 19 succeeded on the first pass; 2025-09-22 failed with
"NetCDF: Not a valid ID" and succeeded on retry, which is why the fetch layer now
retries three times on a bad body.

The archive move to `G:` completed (10,135 files) and introduced no new corruption:
a random 400-day sample found only 2025-09-27, already on the known-bad list.
`config.local_archive()` resolves to `G:` automatically. The bad-day cache is now
empty, and one quarantined original remains as
`...20250922...nc4.bad` for inspection.

### Finding 35: the month-boundary truncation does NOT bite the long tail

The overlap fix is implemented (`--overlap-days`, default 1): each month is
segmented on a padded window and a storm is claimed by the month containing its
volume-weighted centroid time. Tested on June 2020 against the old chunked
behaviour:

| | chunked (pad=0) | padded (pad=1) |
|---|---|---|
| storms | 35,063 | 34,944 (-0.34%) |
| total volume | 2,141.0 km3 | 2,138.7 km3 (-0.1%) |
| time-truncated | 0.94% | **0.00%** |
| **max duration** | **27.0 h** | **27.0 h** |
| **p99 duration** | **15.0 h** | **15.0 h** |
| runtime | 98 s | 93 s |

**The justification given for prioritising this fix was wrong.** The claim was that
month-boundary truncation removes "specifically the longest storms". It does not:

- longest storm that was truncated: **14.5 h**
- longest storm that was not: **27.0 h**

Max and p99 duration are unchanged by the fix. With a median duration of 4 h and
p99 of 15 h, few storms span a month boundary at all, and those that do are not the
long ones; June 2020's longest storms sit mid-month.

The fix is still worth keeping: it removes 331 spurious truncation flags, is
conceptually correct, and costs nothing (it ran marginally faster). But it was
**not** the difference between one climatology run and two, and the earlier
statement to that effect overstated it. The distribution is materially unchanged.

## Run 15 - 2026-09-28, the full archive climatology

```
python src\build_year.py --year 1998 2025 --prominence 4      # 8.93 h
.\run.ps1 src\climatology.py
```

| | |
|---|---|
| Storms | **13,386,185** |
| Record | 1998-2025, **27.75 years** of months present |
| Volume | 618,505 km3 (22,288 km3/yr) |
| Untruncated | 12,453,713 (93.0%) |
| Runtime | **8.93 h**, mean 19.8 min/year (range 14.3-24.3) |

The 7.4 h estimate was 20% low. The prediction that local disk (G:) would beat it was
also wrong: the bottleneck is segmentation, not I/O.

2025 is a 9-month year, as the product requires. 2020 had to be rebuilt: the resume
logic correctly skipped it because a file existed from an earlier test, but that file
predated the overlap fix and carried 0.95% time-truncated storms against 0.00%
everywhere else. **Resume checks month coverage, not code version**; invalidate years
explicitly whenever segmentation changes.

### Finding 36: interannual variability is real and modest

Full years only, volume per month ranges **1,341 to 2,211 km3, a 1.65x spread**,
minimum 2015, maximum 2010. For reference, 2015 was a strong El Nino year and 2010 a
strong La Nina year, which is the expected sign for the maritime continent, but this
project has run no ENSO index correlation and the pairing is an observation, not a
result.

### Finding 37: the seasonal cycle, finally measured over 28 years

Share of total rainfall by calendar month, all years pooled:

| Month | Share | | Month | Share |
|---|---|---|---|---|
| Jan | **0.106** | | Jul | 0.071 |
| Feb | 0.088 | | **Aug** | **0.060** |
| Mar | 0.094 | | Sep | 0.061 |
| Apr | 0.085 | | Oct | 0.069 |
| May | 0.084 | | Nov | 0.088 |
| Jun | 0.084 | | **Dec** | **0.111** |

December is wettest and August driest over the full record, a 1.85x ratio, closely
matching the 1.89x found for 2020 alone (Finding 18). **January is the second wettest
month over 28 years**, which corrects the impression from the single 2020 sample where
it ranked 9th of 12. A one-year sample was not enough to rank the months.

### Finding 38: per-storm return periods are meaningless outside the extreme tail

Corrected thresholds (an earlier version divided by the storm count and produced
thresholds that *fell* as T rose):

| T (yr) | k, storms exceeding in the record | Volume | Max intensity |
|---|---|---|---|
| 1 | 28 | 5.271 km3 | 142.6 mm/hr |
| 2 | 14 | 5.853 km3 | 149.5 mm/hr |
| 5 | 6 | 7.300 km3 | 166.1 mm/hr |
| 10 | 3 | 8.246 km3 | 174.4 mm/hr |
| 25 | 1 | 8.811 km3 | 180.2 mm/hr |

At h = 4.0 the catalogue holds **448,782 storms a year**, so a percentile is nowhere
near a return period:

| Percentile | Storms exceeding per year | Implied T |
|---|---|---|
| p90 | 44,878 | 0.00002 yr |
| p99 | 4,488 | 0.0002 yr |
| p99.9 | 449 | 0.002 yr |
| p99.99 | 45 | 0.02 yr |

**A 1-in-1-year storm is the 28th largest in the entire 28-year record.** The severity
scheme's p90/p99 bands, carried over from the short-record percentile version, would
therefore put essentially the whole population in the lowest class.

Consequences:

1. Severity bands must be defined **on return period directly**, not on percentiles.
2. The scheme is only meaningful for the extreme tail at this granularity. For a
   useful spread of classes across ordinary storms, either use a much coarser h so
   that "a storm" is a system (h near 32 gives ~100 storms per Mkm2 per month, the
   Mekong study's granularity), or accept that severity describes only the top few
   hundred storms of the record.
3. The Mekong study had roughly 700 storms a year over a smaller domain, so a
   per-storm return period there is far more meaningful than here. This is the same
   granularity effect as Finding 31, now biting the severity design.

### Finding 39: the concentration result holds over 28 years

| Top X% of storms | Share of rainfall |
|---|---|
| 1% | 18.4% |
| 10% | 63.7% |
| 13% | **70.7%** |
| 50% | 97.3% |

50% of the rain comes from the top 5.8% of storms; 97% needs the top 48.4%. With
ST-CORA's CMT applied (4.25M storms), the top 13% give 50.0%.

The full record gives 70.7% for the top 13%, against 68.9% from 2020 alone, so the
single-year estimate was representative. The poster's >97% for its long-lived 13%
remains a granularity difference, not a disagreement about the atmosphere.

### Finding 40: severity bands are stated as exceedance rates, not return periods

Following Finding 38, band edges are now set by **how often a threshold is exceeded**
rather than by a percentile or a return period in years. The arithmetic is identical
(T = 1/rate) but the phrasing is honest about what is being measured, and unlike
percentile bands it produces classes that are actually populated.

Defaults `(500, 50)` per year, measured on the 28-year record:

| Band edge | Volume | Max intensity |
|---|---|---|
| exceeded >= 500 times a year | 1.150 km3 | 71.4 mm/hr |
| exceeded >= 50 times a year | 2.175 km3 | 96.6 mm/hr |

Resulting population, all nine classes now occupied:

| Class | Storms in record | Per year | Share of rain |
|---|---|---|---|
| very low | 12,426,479 | 447,801 | 95.3% |
| low | 12,022 | 433 | 0.54% |
| moderate | 1,337 | 48 | 0.06% |
| medium | 12,081 | 435 | 3.29% |
| heavy | 366 | 13 | 0.11% |
| very heavy | 40 | 1.4 | 0.01% |
| intense | 1,273 | 46 | 0.66% |
| severe | 104 | 3.7 | 0.06% |
| extreme | 11 | 0.40 | 0.01% |

Compare the earlier return-period bands at T = 0.01 and 1 yr, which left **three
classes empty** and put 99.96% of storms in the lowest one.

Even so, 99.78% of storms remain "very low". That is not a defect of the bands: at
h = 4.0 the catalogue resolves 449,000 storms a year, so any scheme reserving its
upper classes for genuinely uncommon events will leave the vast majority at the
bottom. The classes are useful for ranking the notable tail, roughly the top 1,000
storms a year, and should not be presented as a description of the whole population.

**Always quote the rate bands and the prominence together.** A class name alone is
not interpretable, because both the thresholds and the population depend on h.

## Run 16 - 2026-09-28, the author's ST-CORA source

Repo at `C:\Users\benny\OneDrive\Documents\Github\ST-CORA` (483 lines of Python).

### Finding 41: the code and the papers disagree on connectivity, and it does not matter

`Storm_list(..., connec=6)`. The comment reads "only 26, 18, and 6 are allowed, 6 is
the strongest connection". Both papers describe a **26**-neighbour system in space and
time, and every percolation number in this project used 26 accordingly.

Tested on the 5-day January 2020 window, largest-object share of labelled voxels:

| Threshold | 6-conn | 18-conn | 26-conn |
|---|---|---|---|
| 0.5 mm/h (the code's T) | 90.1% | 92.3% | 92.7% |
| 1.0 mm/h (the papers' T) | **84.1%** | 87.0% | **89.5%** |
| 2.0 mm/h | 19.8% | 27.4% | 27.9% |
| 5.0 mm/h | 20.3% | 21.6% | 21.6% |

**The percolation finding survives.** Six-connectivity reduces the share from 89.5% to
84.1%, which changes nothing about the conclusion. Connectivity matters most near the
transition (2.0 mm/h, where 6-conn falls just under the 20% line), and barely at all
where the published method operates.

### Finding 42: the KDE step cannot de-percolate, because it does not partition

`KED_segmentation` builds `scipy.stats.gaussian_kde` over `[y, x, z, rain]`, evaluates
the density at each voxel, and keeps `density > prob`, where `prob` is the density at
the rain value closest to `T2`. It returns **one filtered point set**, not several
labelled objects. It also runs only when `check_sub(Object, T2)` finds more than one
sub-object.

So the KDE **erodes an object to its dense core**; it never splits one object into
many. That matters for this project's central argument: the step the 2020 paper adds
to fix "false merging" cannot separate a percolated blob into storms, because
separation is not what it does. The published pipeline has no mechanism that would
rescue it over this domain.

Note also that `kernel = 0.25` in the docstring is documented as "1 = kernel
segmentation 4D, 0 = 3D", i.e. a mode flag, not the 25th percentile the paper
describes. The paper's "25th distribution percentile for u" does not appear in the
code in that form.

### Finding 43: the author's real parameters differ from the papers

From the code docstring:

| Parameter | Code | Papers |
|---|---|---|
| T, wet threshold | **0.5 mm** | 1.0 mm/h |
| T2, delineation | 0.5 | not given |
| Minsize | 15 (stated as 64 km2) | 6 voxels (2019) |
| Psize, min object | 100 | - |
| Time base | **LOCAL, GMT+7** | UTC implied |

Storm selection in `Storm_list` is `Duration > 3` steps and `Areas > 50` voxels. There
is **no Critical Mass Threshold in the code**, despite the CMT being central to both
papers.

There is also **no severity classification, no return periods and no k-means anywhere
in the repository**. That closes the question: the nine-level severity scheme exists
only in the operational web system, and no artefact we hold defines its thresholds.

The local-time base is worth carrying forward. This project works in UTC and flags it
as a caveat; the author segmented in GMT+7, which for the maritime continent aligns
storm objects with the land-sea diurnal cycle rather than cutting across it.

## Run 17 - 2026-09-28, regional breakdown

```
.\run.ps1 src\regions.py --grid 1.0 --kmax 6          # silhouette picks k=2
.\run.ps1 src\regions.py --grid 1.0 --kmax 6 --k 3    # three regimes
```

Regions are derived from the catalogue itself, not imported: storm volume is binned
onto a 1 degree grid by calendar month, each cell's 12-month cycle is normalised to
sum to 1, and cells are clustered on that **shape**. The clustering never sees how
much a cell rains or where it is, so the spatial coherence of the result is a check
on the method rather than an input. 912 cells had the 200-storm minimum.

### Finding 44: the domain average hides a 54x seasonal signal

Silhouette prefers k=2 (0.4514 against 0.3241 for k=3), but silhouette rewards few
well-separated clusters and k=3 is far more interpretable. At k=3:

| Region | Cells | Share of volume | Peak | Trough | **Seasonal contrast** |
|---|---|---|---|---|---|
| 0 monsoonal (lat -12 to -5, lon 106-141) | 163 | 10% | Jan | Aug | **54.52x** |
| 1 transitional (lat -12 to 2) | 213 | 21% | Mar | Aug | 5.31x |
| 2 equatorial (lat -10 to 6) | 536 | 69% | Dec | Feb | 1.54x |
| **domain-wide** | 912 | 100% | Dec | Aug | **1.87x** |

The monsoonal region's rainfall varies **54.5-fold** between January and August. The
domain-wide figure is 1.87x. Aggregating understates the strongest seasonal signal in
the country by a factor of about 29, because the equatorial region, which is 69% of
the volume and almost aseasonal, dominates the mean.

The regions come out spatially coherent (a southern monsoonal band, an equatorial
core) purely from seasonal shape, which is the intended check.

### Finding 45: a domain-wide severity scale undercounts monsoonal extremes 9x

Severity scales fitted per region, bands at >= 500/yr and >= 50/yr within each region:

| Region | Storms/yr | >=500/yr volume | >=50/yr volume | vs domain |
|---|---|---|---|---|
| monsoonal | 48,944 | 0.4396 km3 | 1.0769 km3 | **0.50x** |
| transitional | 99,289 | 0.6866 km3 | 1.4945 km3 | 0.69x |
| equatorial | 300,550 | 1.0132 km3 | 1.9847 km3 | 0.91x |
| domain | 448,782 | 1.1502 km3 | 2.1747 km3 | 1.00x |

Storms landing in the three highest classes over the 28-year record:

| Region | Under the DOMAIN scale | Per year |
|---|---|---|
| monsoonal | **99** | 3.6 |
| transitional | 352 | 12.7 |
| equatorial | **937** | 33.8 |

A regional scale puts 1,388 storms in the top three classes in every region, which is
fixed by construction (50/yr x 27.75 yr). The comparison that matters is the domain
column: **the monsoonal region gets 3.6 notable storms a year, the equatorial region
33.8**, a 9.5x bias, purely because one scale is being asked to serve three
climates. A monsoonal storm must be 2.6x larger than its own regional climatology
warrants before a domain-wide scale calls it notable.

This settles the question raised in `temp/climatology-design.md`: regionalisation is
a prerequisite for the severity product, not a refinement of it.

### Caveats

- k=3 is a judgement, not a silhouette result. k=2 scores better and separates only
  monsoonal from the rest. Report which k produced any figure.
- Regions are defined on a 1 degree grid from storm centroids, so a storm is assigned
  by where its weighted centroid fell, not by where it did most of its damage.
- The 200-storm minimum drops sparse cells, mostly at the domain edges.
- Nothing here has been compared against published Indonesian monsoon zonings. That
  comparison is worth doing as an external check, and has not been done.

## Run 18 - 2026-09-28, storm age and the family layer

### Finding 46: "age in days" is not a property a storm object can have at h = 4

Duration of the 12.45M untruncated storms across the 28-year record:

| | |
|---|---|
| p50 | 3.0 h |
| p99 | 14.0 h |
| p99.99 | 25.0 h |
| max | 53.5 h |

| Age | Storms | Per year | Share of volume |
|---|---|---|---|
| >= 12 h | 320,994 | 11,567 | 22.3% |
| >= 1 day | 1,862 | 67 | 0.26% |
| **>= 2 days** | **3** | 0.1 | ~0% |
| >= 3 days | **0** | 0 | 0 |

A 1/2/3+ day classification of storm objects would put three storms in one bucket and
none in the others across 28 years. That is not a shortcoming of the data: at h = 4.0
a storm object is a convective cell, and hours is its correct lifetime. Multi-day rain
systems over Indonesia are sequences of hundreds of cells, not single long-lived ones.

### Finding 47: a family layer gives the ages, but only with strict linking

`src/families.py` links storms into events when their times are within `gap_h` and
their volume-weighted centroids within `dist_km`. The rule has to be strict, because
loose linking percolates exactly as the segmentation did. Share of December 2020's
rain held by the single largest family:

| Link rule | Largest family | Verdict |
|---|---|---|
| bounding-box overlap, 0.5-6 h gap | **93-98%** | unusable |
| centroid within 200 km | 99.9% | unusable |
| centroid within 100 km | 71-94% | unusable |
| **centroid within 50 km, 3 h gap** | **0.5%** | usable |

Bounding boxes fail because a large storm's box spans much of the domain and
everything chains through it. This is the third time percolation has appeared in this
project, after connected-component labelling and after domain decomposition, and the
diagnostic is the same each time: the share of rain in the largest object.

2020 at 50 km / 3 h: 391,527 storms became **248,502 families**, largest holding
0.06% of the rain.

| Age class | Families | Share of families | Share of volume |
|---|---|---|---|
| under a day | 245,518 | 98.80% | 84.1% |
| **1 day** | **2,836** | 1.14% | **13.9%** |
| **2 days** | **141** | 0.06% | **1.8%** |
| **3+ days** | **7** | 0.003% | 0.14% |

So the age classification is worth having, at the family level: multi-day events are
1.2% of families but carry **16% of the annual rainfall**, and they are countable
(2,836 one-day events in 2020, 141 two-day, 7 three-day-plus).

Caveats: families are linked within a calendar month, because the catalogue is
segmented per month, so an event spanning a month boundary is cut. `gap_h` and
`dist_km` are tuned on one month and not swept. And a family is a chain of proximity,
not a tracked system: two unrelated storms passing within 50 km and 3 h will join.

## Run 19 - 2026-09-28, UTC versus local time

### Finding 48: a time shift cannot change segmentation, only where chunks fall

Shifting the clock relabels the time axis without touching voxel adjacency, so the
objects are identical by construction. The only thing a shift can change is where
**chunk boundaries** land, because a local day begins at a different absolute instant
from a UTC day.

Measured on 2020-12-05..11, segmented once continuously and then in day-chunks with
three different alignments:

| Chunking | Storms | Time-truncated | Volume | Max duration |
|---|---|---|---|---|
| continuous, no chunks | 8,732 | **4.35%** | 462.0 km3 | 24.0 h |
| UTC days | 9,249 | 23.20% | 461.7 km3 | 22.0 h |
| UTC+7 days | 8,044 | 29.89% | 390.7 km3 | 20.0 h |
| UTC+9 days | 7,896 | 27.08% | 389.3 km3 | 20.0 h |

Interior storms only (wholly inside 12-06..12-10, untruncated):

| | Storms | Volume | p99 duration |
|---|---|---|---|
| continuous | 5,891 | 301.6 km3 | 13.5 h |
| UTC | 4,992 | 175.8 km3 | 12.0 h |
| UTC+7 | 4,521 | 190.3 km3 | 12.5 h |
| UTC+9 | 4,648 | 188.1 km3 | 12.5 h |

**Chunk length dominates chunk alignment.** Daily chunking loses 15-23% of interior
storms and up to 42% of interior volume against a continuous run, whichever timezone
it is aligned to, while the three timezone choices differ from each other by far less.

This project chunks **monthly**, which is about 30x longer, and adds a one-day overlap
that removes boundary truncation entirely (Finding 35). So the timezone question does
not affect our segmentation at all, and **UTC is the right base** - it also remains
well defined if the AOI is ever extended globally, where a single local time is not.

### Finding 49: local time is required for interpretation, and recovers the classic signal

Storm initiation over the full 28-year catalogue, 12.45M storms, split by land and sea
using the rasterised province polygons (30.1% land, 69.9% sea):

| Local hour | Land | Sea | | UTC hour | Land | Sea |
|---|---|---|---|---|---|---|
| 10-12 | 0.134 | 0.109 | | 02-04 | 0.115 | 0.097 |
| 12-14 | 0.131 | 0.083 | | **04-06** | **0.140** | 0.090 |
| **14-16** | **0.145** | 0.090 | | 06-08 | 0.136 | 0.086 |
| 16-18 | 0.115 | 0.070 | | **14-16** | 0.082 | **0.105** |
| **22-24** | 0.093 | **0.114** | | 22-24 | 0.035 | 0.064 |

| | Peak, local | Peak, UTC | Diurnal amplitude |
|---|---|---|---|
| **land** | **14-16** | 04-06 | **4.25x** |
| **sea** | **22-24** | 14-16 | 1.80x |

This is the maritime continent's defining signal, recovered from our own catalogue:
**land storms peak in the mid-afternoon, oceanic storms near midnight**, and the land
cycle is more than twice as strong (4.25x against 1.80x).

It is only visible against a local clock. In UTC the land peak smears across 02-08
because three time zones are superimposed, and the land-sea phase separation is
obscured.

**Conclusion: segment in UTC, interpret in local time.** The two questions are
separate, and conflating them is what made the author's GMT+7 choice look like a
methodological requirement when it is a presentational one. Recovering a well-known
physical signal that was never targeted is also the strongest independent evidence so
far that the segmentation is finding real storms.

## Run 20 - 2026-09-28, sea-to-land transitions and warning lead time

```
.\run.ps1 src\transition.py --min-volume 0.05
```

Storms are classified by whether their start and end locations fall on land, using the
rasterised province polygons. For the sea-to-land subset the trackline is then walked
vertex by vertex to find the **first** land contact, which gives the actual time spent
over water rather than an upper bound from total duration.

### Finding 50: sea-to-land storms are few but disproportionately wet

Full 28-year record, 12.45M untruncated storms:

| Transition | Per year | Share of storms | Share of rain | Median volume |
|---|---|---|---|---|
| sea -> sea | 301,214 | 67.1% | 70.9% | 0.0071 km3 |
| land -> land | 114,434 | 25.5% | 17.8% | 0.0055 km3 |
| **sea -> land** | **16,843** | **3.8%** | **6.1%** | **0.0239 km3** |
| land -> sea | 16,292 | 3.6% | 5.1% | 0.0213 km3 |

Sea-to-land storms deliver 6.1% of all rainfall from 3.8% of storms, because their
median volume is about **3.4x** that of a typical sea-to-sea storm. Coast-crossing
storms are a small, systematically larger population.

### Finding 51: every sea-to-land storm offers lead time, and the big ones offer most

157,841 tracks walked (volume >= 0.05 km3). Hours over water before first landfall:

| | |
|---|---|
| p25 | 1.5 h |
| **p50** | **3.5 h** |
| p90 | 9.0 h |
| p99 | 14.5 h |
| max | 29.5 h |

**Not one storm makes landfall on its first timestep** (0.0%), so a sea-formed storm
always spends at least one half-hourly step over water before its centroid reaches
land.

Lead time rises monotonically with storm size:

| Volume quartile | Median hours at sea | p90 | Median volume |
|---|---|---|---|
| Q1 small | 2.5 h | 6.5 h | 0.06 km3 |
| Q2 | 3.0 h | 7.5 h | 0.09 km3 |
| Q3 | 4.0 h | 9.0 h | 0.15 km3 |
| **Q4 large** | **6.0 h** | **12.0 h** | 0.32 km3 |

The storms most worth warning about give the most warning: the largest quartile spends
a median 6 hours over water, **2.4x** the smallest quartile, with a p90 of 12 hours.
That is an argument for nowcasting effort directed at storms over water specifically.

The single-year 2020 figures (median 4.5 h overall, 7.0 h for Q4) sit close to the
28-year values (3.5 h and 6.0 h), so one year was broadly representative, though it
ran about 20% high.

### Caveats

- A storm is located by its **volume-weighted centroid**, so a system straddling a
  coastline is assigned wholly to one side.
- "Landfall" is the centroid crossing the coast. The storm's leading edge reaches land
  earlier, so these lead times are **conservative** relative to when rain first falls
  on land.
- Stage 2 is restricted to storms above 0.05 km3, which is 1.3% of the catalogue but
  the part relevant to flooding.
- The land mask is the simplified ADM1 province geometry, so small islands and fine
  coastal detail are approximated.
- Lead time here is a property of the storm, not of any forecast system. It is the
  interval a nowcast could in principle exploit, not a demonstrated skill.

## Run 21 - 2026-09-28, coastline breakdown, on Natural Earth

`src/geo.py` replaces the project's ad-hoc masks with Natural Earth 10m rasters (land,
coastline, global admin-1 provinces, distance-to-land). Natural Earth is global, so
nothing here needs rewriting if the AOI is extended, and its physical land polygons
are built for coastlines where geoBoundaries is an administrative product.

### Finding 52: the old land mask was missing every neighbouring country

| Mask | Land fraction over the AOI |
|---|---|
| geoBoundaries IDN ADM1 (used in Findings 49-51) | 17.90% |
| **Natural Earth 10m land** | **21.95%** |

The masks disagree on 4.6% of cells, and almost all of it is **Natural Earth land that
geoBoundaries calls sea**: Malaysia, Papua New Guinea and Timor-Leste, which an
Indonesia-only administrative file does not contain. Storms making landfall there were
being counted as never reaching land.

Corrected stage-1 numbers, full 28-year record:

| Transition | Per year | Share of storms | Share of rain | (old, IDN-only mask) |
|---|---|---|---|---|
| sea -> sea | 273,863 | 61.0% | 66.3% | 67.1% / 70.9% |
| land -> land | 139,421 | 31.1% | 21.7% | 25.5% / 17.8% |
| sea -> land | 17,983 | 4.0% | 6.6% | 3.8% / 6.1% |
| land -> sea | 17,514 | 3.9% | 5.5% | 3.6% / 5.1% |

Land-to-land rises from 25.5% to 31.1% of storms, which is the direct consequence of
Borneo's Malaysian third and the PNG half of New Guinea becoming land. The lead-time
results in Finding 51 are unchanged to the quoted precision.

### Finding 53: climate region does not predict lead time. Coastal geometry does

Lead time by climate region of landfall is a **null result**:

| Region | Storms | Median h at sea | p90 |
|---|---|---|---|
| monsoonal | 14,714 | 3.50 | 9.00 |
| transitional | 36,977 | 3.50 | 9.00 |
| equatorial | 116,294 | 3.50 | 9.00 |

Identical to two significant figures. The regionalisation that mattered so much for
severity (Finding 45) carries no information about warning lead time.

By province it does vary, from 2.0 h (Riau) to 5.0 h (Maluku Utara, Sumatera Barat),
and the driver is how far offshore storms form:

| Median offshore distance at formation | vs median lead time |
|---|---|
| across 30 provinces, Pearson | **r = +0.877** (p < 0.0001) |
| across 30 provinces, Spearman | +0.893 |
| per storm, n = 167,985 | r = +0.505, Spearman +0.593 |

Median storm volume, by contrast, explains nothing across provinces (r = +0.19,
p = 0.32), even though it predicts lead time strongly *within* the population
(Finding 51). Per storm:

| Formed offshore | Storms | Median h at sea | p90 |
|---|---|---|---|
| < 15 km | 49,399 | **1.0** | 5.5 |
| 15-30 km | 46,436 | 3.0 | 8.0 |
| 30-50 km | 38,545 | 5.0 | 9.5 |
| 50-100 km | 25,958 | 6.5 | 11.0 |
| > 100 km | 7,647 | **8.0** | 13.0 |

So lead time is set by **coastal geometry**, not climate: Riau faces the narrow Malacca
Strait, where storms form a median 15.7 km offshore, while Maluku Utara faces open
ocean at 33.4 km. A coast with no open water upwind cannot offer warning time however
often it storms.

Implied propagation speed for storms forming beyond 15 km, offshore distance divided
by hours at sea: median **9.0 km/h (2.5 m/s)**, p25 5.4, p75 15.7 km/h. That is
consistent with the mild advection measured at the very start of this project
(Finding 3: displacement exceeded one grid cell in 0.8% of steps, roughly 6 m/s at the
cell scale), and it is a useful independent cross-check from a completely different
calculation.

### Operational reading

A domain-wide median lead time of 3.5 h hides a 2.0 to 5.0 h range between provinces.
Warning value is highest where storms form far offshore, and the Malacca Strait coasts
are structurally the hardest to warn: not because their storms are weaker, but because
there is no room for them to form far enough away.
