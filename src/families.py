"""Group storm objects into multi-day storm FAMILIES (events).

Why this layer exists
---------------------
At h = 4.0 a storm object is a convective cell. Measured over the 28-year
catalogue: median life 3 h, p99 14 h, and only **3 storms in 28 years last 2 days**
(docs/findings.md Finding 46). So "storm age in days" cannot be a property of a
storm object, because objects of that age essentially do not exist.

Multi-day rain systems obviously do exist over Indonesia. They are not single cells
but sequences of hundreds. This module builds that second layer: storms are linked
into families when they are close in time and space, and the family is the thing
that has an age in days.

Linking, and why the rule is tight
----------------------------------
Two storms join a family when their time intervals are within `gap_h` and their
volume-weighted centroids are within `dist_km`.

The rule has to be strict, because loose linking percolates exactly as the
segmentation did. Measured on December 2020, share of the month's rain held by the
single largest family:

    bounding-box overlap          93-98%   unusable
    centroid within 200 km        99.9%    unusable
    centroid within 100 km        71-94%   unusable
    centroid within  50 km, 3 h    0.5%    usable

So 50 km / 3 h are the defaults. Always report the percolation share alongside any
family statistic: it is the check that the linking found events rather than merging
the domain.

    .\\run.ps1 src\\families.py --year 2020
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, PRODUCT  # noqa: E402

DEFAULT_GAP_H = 3.0
DEFAULT_DIST_KM = 50.0
PERCOLATION_LIMIT = 0.20


class _UnionFind:
    def __init__(self, n: int):
        self.p = np.arange(n)

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def link(df: pd.DataFrame, gap_h: float = DEFAULT_GAP_H,
         dist_km: float = DEFAULT_DIST_KM) -> np.ndarray:
    """Family id per storm. Input must carry start/end time and weighted centroid.

    Swept in time order with an active list, so cost stays near-linear instead of
    comparing all pairs: a month holds about 42,000 storms.
    """
    d = df.sort_values("start_time")
    order = d.index.to_numpy()
    t0 = pd.to_datetime(d.start_time).values.astype("datetime64[m]").astype(np.int64)
    t1 = pd.to_datetime(d.end_time).values.astype("datetime64[m]").astype(np.int64)
    la, lo = d.wcentroid_lat.to_numpy(), d.wcentroid_lon.to_numpy()

    n = len(d)
    gap = int(gap_h * 60)
    ddeg = dist_km / 111.32
    uf = _UnionFind(n)
    active: list[int] = []
    for i in range(n):
        active = [j for j in active if t1[j] >= t0[i] - gap]
        if active:
            aj = np.asarray(active)
            dlat = la[aj] - la[i]
            # cos(lat) so a degree of longitude is not overvalued away from the equator
            dlon = (lo[aj] - lo[i]) * np.cos(np.deg2rad(la[i]))
            for j in aj[(dlat * dlat + dlon * dlon) <= ddeg * ddeg]:
                uf.union(i, int(j))
        active.append(i)

    # fam is in sorted order; map it back to the caller's row order by index.
    fam = np.array([uf.find(i) for i in range(n)])
    return pd.Series(fam, index=d.index).reindex(df.index).to_numpy()


def summarise(df: pd.DataFrame, fam: np.ndarray) -> pd.DataFrame:
    """One row per family, with the age that motivated this module."""
    t = df.assign(fam=fam)
    g = t.groupby("fam").agg(
        n_storms=("total_volume_km3", "size"),
        start=("start_time", "min"), end=("end_time", "max"),
        volume_km3=("total_volume_km3", "sum"),
        max_intensity_mm_hr=("max_intensity_mm_hr", "max"),
        max_area_km2=("max_area_km2", "max"),
        lat=("wcentroid_lat", "mean"), lon=("wcentroid_lon", "mean"))
    span = (pd.to_datetime(g.end) - pd.to_datetime(g.start))
    g["age_h"] = span.dt.total_seconds() / 3600.0 + 0.5
    g["age_days"] = np.floor(g.age_h / 24.0).astype(int)
    g["age_class"] = np.where(g.age_days >= 3, "3+ days",
                       np.where(g.age_days == 2, "2 days",
                        np.where(g.age_days == 1, "1 day", "under a day")))
    return g.reset_index()


def percolation_share(g: pd.DataFrame) -> float:
    """Share of rain in the single largest family. The check that linking worked."""
    tot = g.volume_km3.sum()
    return float(g.volume_km3.max() / tot) if tot else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, nargs="+", required=True)
    ap.add_argument("--product", default=None)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--gap-h", type=float, default=DEFAULT_GAP_H)
    ap.add_argument("--dist-km", type=float, default=DEFAULT_DIST_KM)
    a = ap.parse_args()

    years = (list(range(a.year[0], a.year[1] + 1)) if len(a.year) == 2
             else [a.year[0]])
    cols = ["month", "start_time", "end_time", "total_volume_km3",
            "max_intensity_mm_hr", "max_area_km2",
            "wcentroid_lat", "wcentroid_lon", "truncated_time", "truncated_space"]

    all_fam = []
    for y in years:
        f = DATA_PROCESSED / (f"catalogue_{a.product or PRODUCT}_{y}"
                              f"_h{a.h:g}.parquet")
        if not f.exists():
            print(f"{y}: no catalogue, skipped"); continue
        df = pd.read_parquet(f, columns=cols)
        df = df[~(df.truncated_time | df.truncated_space)].dropna(
            subset=["wcentroid_lat", "wcentroid_lon"]).reset_index(drop=True)
        # Link within each month: the catalogue is segmented per month, so a family
        # cannot legitimately span the boundary anyway.
        parts = []
        for m, gm in df.groupby("month"):
            gm = gm.reset_index(drop=True)
            g = summarise(gm, link(gm, a.gap_h, a.dist_km))
            g["year"], g["month"] = y, m
            parts.append(g)
        fam = pd.concat(parts, ignore_index=True)
        fam["family_uid"] = (fam.year.astype(str) + "-" + fam.month.astype(str)
                             + "-" + fam["fam"].astype(str))
        all_fam.append(fam)
        print(f"{y}: {len(df):,} storms -> {len(fam):,} families, "
              f"largest holds {100*percolation_share(fam):.1f}% of the rain")

    if not all_fam:
        return
    fam = pd.concat(all_fam, ignore_index=True)
    out = DATA_PROCESSED / (f"families_{a.product or PRODUCT}_h{a.h:g}"
                            f"_g{a.gap_h:g}_d{a.dist_km:g}.parquet")
    fam.to_parquet(out, index=False)

    share = percolation_share(fam)
    print(f"\n{len(fam):,} families")
    print(f"largest family holds {100*share:.2f}% of the rain"
          + ("" if share < PERCOLATION_LIMIT else
             "  <-- ABOVE THE LIMIT, the linking has merged the domain"))
    print(f"age_h  p50 {fam.age_h.median():.1f}  p99 {fam.age_h.quantile(.99):.1f}  "
          f"max {fam.age_h.max():.1f}")
    print("\nby age class:")
    t = fam.groupby("age_class").agg(families=("age_h", "size"),
                                     storms=("n_storms", "sum"),
                                     volume=("volume_km3", "sum"))
    t["share_families"] = t.families / t.families.sum()
    t["share_volume"] = t.volume / t.volume.sum()
    order = ["under a day", "1 day", "2 days", "3+ days"]
    print(t.reindex([o for o in order if o in t.index]).to_string(
        float_format=lambda x: f"{x:,.4f}"))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
