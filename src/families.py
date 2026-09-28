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


def _load_padded(y: int, product: str, h: float, cols, pad_days: int):
    """Year `y` with the tail of y-1 and the head of y+1 attached.

    Without the pad, a family alive at midnight on New Year is cut in two by the file
    boundary rather than by anything physical. The 2019-12-30 to 2020-01-02 Jakarta
    event is exactly that case: 72 of its storms sit in the 2019 catalogue and 51 in
    the 2020 one.
    """
    def read(year):
        f = DATA_PROCESSED / f"catalogue_{product}_{year}_h{h:g}.parquet"
        if not f.exists():
            return None
        d = pd.read_parquet(f, columns=cols)
        return d[~(d.truncated_time | d.truncated_space)].dropna(
            subset=["wcentroid_lat", "wcentroid_lon"])

    core = read(y)
    if core is None:
        return None
    parts = [core]
    pad = pd.Timedelta(days=pad_days)
    before = read(y - 1)
    if before is not None:
        parts.insert(0, before[pd.to_datetime(before.end_time)
                               >= pd.Timestamp(y, 1, 1) - pad])
    after = read(y + 1)
    if after is not None:
        parts.append(after[pd.to_datetime(after.start_time)
                           <= pd.Timestamp(y, 12, 31) + pad])
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, nargs="+", required=True)
    ap.add_argument("--product", default=None)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--gap-h", type=float, default=DEFAULT_GAP_H)
    ap.add_argument("--dist-km", type=float, default=DEFAULT_DIST_KM)
    ap.add_argument("--pad-days", type=int, default=2,
                    help="days of the adjacent years to link across the boundary")
    a = ap.parse_args()

    years = (list(range(a.year[0], a.year[1] + 1)) if len(a.year) == 2
             else [a.year[0]])
    cols = ["month", "start_time", "end_time", "total_volume_km3",
            "max_intensity_mm_hr", "max_area_km2",
            "wcentroid_lat", "wcentroid_lon", "truncated_time", "truncated_space"]

    all_fam = []
    for y in years:
        df = _load_padded(y, a.product or PRODUCT, a.h, cols, a.pad_days)
        if df is None:
            print(f"{y}: no catalogue, skipped"); continue

        # Link the whole padded year in one pass. An earlier version linked month by
        # month, on the grounds that the catalogue was segmented per month so a family
        # could not legitimately span the boundary. That stopped being true when
        # build_year.py started padding months (Finding 35): storms now cross midnight
        # on the 1st intact, and a family that spans a month or a year boundary is
        # real. Splitting them is what cut the 2019-12-31 Jakarta event in two.
        fam = summarise(df, link(df, a.gap_h, a.dist_km))

        # Claim by start: a family beginning in the previous year's pad belongs to
        # that year, and will be kept when that year is built. Without this the pad
        # would duplicate families across adjacent years.
        keep = pd.to_datetime(fam.start).dt.year == y
        fam = fam[keep].copy()
        fam["year"] = y
        fam["month"] = pd.to_datetime(fam.start).dt.month
        fam["family_uid"] = (fam.year.astype(str) + "-" + fam.month.astype(str)
                             + "-" + fam["fam"].astype(str))
        all_fam.append(fam)
        print(f"{y}: {len(df):,} storms -> {len(fam):,} families, "
              f"largest holds {100*percolation_share(fam):.2f}% of the rain")

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
