# Sweep: segmentation prominence h

> Append, do not replace. Earlier runs stay comparable.

## Run 1 - 2026-09-27

```
.\run.ps1 src\sweep.py --months 2020-12 2020-08 --source local --product final
```

Fixed: `wet_threshold=1.0`, `min_voxels=6`, IMERG Final, full Indonesia AOI, whole
calendar months. Raw numbers in `data/processed/sweep-prominence-watershed.csv`.

Months chosen by measurement, not assumption (`src/monthly.py --year 2020`):
**December is the wettest month of 2020 (3,118 km3), August the driest (1,648 km3)**.
January, which a DJF assumption would have picked, ranks 9th of 12.

## Result

| Month | h | storms | percolation | captured | total km3 | dur med | dur p95 | area p95 km2 | truncated |
|---|---|---|---|---|---|---|---|---|---|
| Dec | 1.0 | 92,017 | 0.0004 | 0.974 | 2594.2 | 3.5 h | 8.0 h | 9,616 | 7.4% |
| Dec | 2.0 | 57,158 | 0.0006 | 0.963 | 2582.4 | 4.0 h | 9.5 h | 13,097 | 8.5% |
| Dec | 3.2 | 36,509 | 0.0007 | 0.951 | 2565.0 | 5.0 h | 11.5 h | 17,338 | 9.9% |
| Dec | **4.0** | **28,482** | 0.0008 | 0.943 | 2552.5 | 5.5 h | 12.0 h | 20,213 | 10.7% |
| Dec | 4.8 | 22,762 | 0.0009 | 0.935 | 2539.8 | 6.0 h | 13.0 h | 23,194 | 11.6% |
| Dec | 8.0 | 11,118 | 0.0015 | 0.907 | 2489.6 | 8.0 h | 17.0 h | 35,016 | 15.0% |
| Aug | 1.0 | 53,242 | 0.0010 | 0.968 | 1393.1 | 3.0 h | 7.5 h | 8,898 | 7.0% |
| Aug | 2.0 | 34,452 | 0.0014 | 0.956 | 1386.2 | 3.5 h | 9.0 h | 11,926 | 7.8% |
| Aug | 3.2 | 22,618 | 0.0023 | 0.939 | 1374.4 | 4.5 h | 10.5 h | 15,449 | 8.7% |
| Aug | **4.0** | **17,850** | 0.0023 | 0.930 | 1366.8 | 5.0 h | 11.0 h | 17,943 | 9.5% |
| Aug | 4.8 | 14,390 | 0.0025 | 0.920 | 1359.1 | 5.5 h | 12.0 h | 20,009 | 10.3% |
| Aug | 8.0 | 7,160 | 0.0044 | 0.893 | 1333.0 | 7.0 h | 15.5 h | 30,175 | 13.3% |

## Verdict: h is NOT stable, and that is now measured properly

Across the full -20% to +20% span around h = 4.0:

| Month | h 3.2 -> 4.8 | Criterion | Verdict |
|---|---|---|---|
| December | **-37.7%** | under 10% | **UNSTABLE** |
| August | **-36.4%** | under 10% | **UNSTABLE** |

The two months agree to within 1.3 percentage points, so this is a property of the
method, not of the weather. Over the full tested range an 8x change in h moves the
count 8.3x. There is no h-independent storm count.

This is the second time this claim has been tested and failed. The plan originally
argued that persistence would make the count a property of the rain rather than the
parameter. It does not. That text has been corrected rather than softened.

Note also that the earlier default h grid (1, 2, 3, 4, 6, 8, 12) could not have decided
this: every step in it exceeds 25%, while the criterion is defined at 20%. The 3.2 and
4.8 points exist solely to make the test possible.

## What IS stable, and it matters more than the count

**Total captured volume is very nearly h-invariant.** Over an 8x change in h:

| Month | h=1.0 | h=8.0 | change |
|---|---|---|---|
| December | 2594.2 km3 | 2489.6 km3 | **-4.0%** |
| August | 1393.1 km3 | 1333.0 km3 | **-4.3%** |

This follows directly from the method being a partition. h decides where the internal
boundaries fall; it barely changes which voxels are in a storm at all. So every
volume-based statistic is safe against the choice of h, while every count-based one is
not.

**Percolation stays negligible everywhere**: 0.0004 to 0.0044. The problem the method
was chosen to solve is solved robustly across seasons and across the whole parameter
range. For comparison, CCL at the published 1 mm/h gives 0.90.

**Between-month ratios are far more robust than absolute counts.** August divided by
December: 0.579, 0.603, 0.620, 0.627, 0.632, 0.644 as h rises. That is an 11% drift
against the count's 8.3x. Comparative statements survive the parameter choice; absolute
ones do not.

## Recommended working value: h = 4.0

Chosen as a **scale**, not an optimum. There is no optimum, because the count never
stabilises. At h = 4.0 the population has p95 max area near 20,000 km2 and p95 duration
11 to 12 h, which is the mesoscale convective system range relevant to flooding.
Capture is 93 to 94% and truncation about 10%.

Use a different h if the question calls for a different scale, and say which was used.

## Caveats

- **The seasonal axis is weak here.** December to August is only a 1.89x volume ratio,
  because Indonesia's several rainfall regimes partly cancel in a domain average. The
  close agreement between months is therefore weak evidence of seasonal robustness, not
  strong evidence. A regional breakdown would test this properly.
- **Truncation rises with h**, from 7% to 15% in December. At large h an eighth of the
  catalogue is censored by a domain or window edge. Filter on the flags before quoting
  any duration or volume distribution.
- August percolates slightly more than December at every h (0.0044 vs 0.0015 at h=8),
  presumably because a smaller total wet area makes the largest object a larger share.
  It stays negligible either way.
- One year only. Nothing here establishes interannual stability.

## Consequence for the plan

This strengthens the case for the merge tree, which is not yet implemented. Since the
captured volume is h-invariant while the partitioning is not, the honest object is the
**hierarchy across h**, not a catalogue at one chosen h. A merge tree carries every
level at once and lets the user cut it where their question requires, instead of baking
one arbitrary scale into the product.

---

## Run 2 - 2026-09-27, merge tree

```
.\run.ps1 src\sweep.py --months 2020-12 2020-08 --source local --product final --method mergetree
```

Same fixed settings as Run 1. Raw numbers in `data/processed/sweep-prominence-mergetree.csv`.
The month's tree builds once (350,823 components for December, 13 s) and each h is a cut,
so each value costs 46-82 s against 133-213 s for a full re-segmentation.

| Month | h | storms | percolation | captured | total km3 | vol med | vol p95 | dur med | dur p95 |
|---|---|---|---|---|---|---|---|---|---|
| Dec | 1.0 | 93,687 | 0.0004 | 0.976 | 2596.4 | 0.0079 | 0.119 | 3.5 h | 8.0 h |
| Dec | 2.0 | 64,038 | 0.0006 | 0.972 | 2592.0 | 0.0105 | 0.180 | 4.0 h | 9.5 h |
| Dec | 3.2 | 48,126 | 0.0007 | 0.968 | 2586.2 | 0.0115 | 0.250 | 4.0 h | 10.5 h |
| Dec | **4.0** | **42,200** | 0.0008 | 0.966 | 2582.3 | 0.0107 | 0.291 | 4.0 h | 11.5 h |
| Dec | 4.8 | 37,957 | 0.0009 | 0.963 | 2578.0 | 0.0090 | 0.332 | 4.0 h | 12.0 h |
| Dec | 8.0 | 29,017 | 0.0014 | 0.954 | 2562.2 | 0.0039 | 0.480 | 3.0 h | 13.5 h |
| Aug | 1.0 | 54,062 | 0.0010 | 0.970 | 1394.2 | 0.0067 | 0.111 | 3.0 h | 7.5 h |
| Aug | 2.0 | 38,387 | 0.0014 | 0.967 | 1391.8 | 0.0084 | 0.161 | 3.5 h | 8.5 h |
| Aug | 3.2 | 29,627 | 0.0022 | 0.961 | 1388.0 | 0.0088 | 0.214 | 3.5 h | 10.0 h |
| Aug | **4.0** | **26,193** | 0.0022 | 0.958 | 1385.5 | 0.0081 | 0.250 | 3.5 h | 10.5 h |
| Aug | 4.8 | 23,784 | 0.0024 | 0.955 | 1383.2 | 0.0071 | 0.281 | 3.5 h | 11.0 h |
| Aug | 8.0 | 18,619 | 0.0041 | 0.947 | 1375.2 | 0.0037 | 0.395 | 3.0 h | 12.5 h |

### Stability roughly halves, but still fails

| Method | Dec, h 3.2 to 4.8 | Aug, h 3.2 to 4.8 |
|---|---|---|
| watershed (Run 1) | -37.7% | -36.4% |
| **merge tree** | **-21.1%** | **-19.7%** |

The verdict is unchanged: the criterion is 10%, so h remains **UNSTABLE**. But the
sensitivity is about half that of the direct watershed, so the tree's persistence
criterion is the better-behaved of the two. One individual step (August, 4.0 to 4.8)
came in at -9.2% and passes; no other did.

### Volume invariance improves too

| Method | December, h=1 to h=8 | August |
|---|---|---|
| watershed | -4.0% | -4.3% |
| **merge tree** | **-1.3%** | **-1.4%** |

Captured fraction also holds up better at large h: 0.976 to 0.954, where the watershed
fell 0.974 to 0.907. The tree loses less rain as the prominence rises.

### The between-month ratio is method-independent

| h | watershed | merge tree |
|---|---|---|
| 1.0 | 0.579 | 0.577 |
| 4.0 | 0.627 | 0.621 |
| 8.0 | 0.644 | 0.642 |

Two independently implemented segmentations agree on the August-to-December ratio to
within 0.006 at every h, while disagreeing on the absolute count by up to 2.6x. This is
the strongest evidence in the project so far that **comparative statistics are the
robust ones** and absolute counts are not.

### The two methods produce different populations, not just different counts

At h=8.0 in December: the merge tree finds 29,017 storms with a median volume of
0.0039 km3; the watershed finds 11,118 with a median of 0.1072 km3.

The tree's median volume is also **non-monotonic** in h (0.0079, 0.0105, 0.0115, 0.0107,
0.0090, 0.0039) where the watershed's rose steadily. The p95 volume rises monotonically
in both, so the large end is well behaved and the effect is at the small end.

Reading: as h rises the tree absorbs weak peaks into strong neighbours, which removes
mid-sized storms from the population while small isolated ones, having no stronger
neighbour to merge into, survive unchanged. The median therefore falls even as the
mean size of the big systems grows. The watershed instead merges more aggressively and
leaves a smaller, coarser population.

**Consequence: "h = 4" does not mean the same thing to the two methods.** Always record
which segmentation produced a catalogue, not only the value of h.

### Recommendation unchanged in value, better supported

h = 4.0 with the merge tree. At that setting December has p95 duration 11.5 h and p95
footprint 17,200 km2, the mesoscale range, with capture at 0.966 and truncation at 9.2%
(against 0.943 and 10.7% for the watershed). The merge tree is preferred on every axis
measured: half the parameter sensitivity, a third of the volume drift, higher capture,
and about 3x faster to sweep.
