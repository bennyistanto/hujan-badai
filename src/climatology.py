"""Load the multi-year catalogue and produce the first climatology numbers.

    .\\run.ps1 src\\climatology.py
    .\\run.ps1 src\\climatology.py --exclude-year 2020
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, PRODUCT  # noqa: E402

COLS = ["year", "month", "start_time", "duration_h", "total_volume_km3",
        "max_intensity_mm_hr", "max_area_km2", "wcentroid_lat", "wcentroid_lon",
        "truncated_time", "truncated_space"]


def load(product: str = None, h: float = 4.0, cols=COLS,
         exclude_years=()) -> pd.DataFrame:
    """Concatenate the per-year catalogues.

    Reads only the columns asked for: the full record is 13.4M rows and about
    2.5 GB on disk, so pulling every column is wasteful for most questions.
    """
    pat = f"catalogue_{product or PRODUCT}_*_h{h:g}.parquet"
    files = sorted(DATA_PROCESSED.glob(pat))
    if not files:
        raise FileNotFoundError(f"no catalogue files matching {pat}")
    parts = []
    for f in files:
        y = int(f.stem.split("_")[2])
        if y in exclude_years:
            continue
        parts.append(pd.read_parquet(f, columns=cols))
    return pd.concat(parts, ignore_index=True)


def record_years(df: pd.DataFrame) -> float:
    """Length of the record in years, counting only months actually present.

    2025 is a 9-month year because IMERG Final ends 2025-09-30, so counting
    calendar years would overstate the record and deflate every return period.
    """
    n_months = df.groupby(["year", "month"]).size().shape[0]
    return n_months / 12.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", default=None)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--exclude-year", type=int, nargs="*", default=[])
    a = ap.parse_args()

    df = load(a.product, a.h, exclude_years=set(a.exclude_year))
    years = record_years(df)
    clean = df[~(df.truncated_time | df.truncated_space)]

    print(f"catalogue : {len(df):,} storms, h={a.h:g}")
    print(f"record    : {df.year.min()}-{df.year.max()}, "
          f"{years:.2f} years of months present")
    print(f"volume    : {df.total_volume_km3.sum():,.0f} km3 "
          f"({df.total_volume_km3.sum()/years:,.0f} km3/yr)")
    print(f"untruncated: {len(clean):,} ({100*len(clean)/len(df):.1f}%)")
    print(f"per year  : {len(df)/years:,.0f} storms")

    print("\n--- interannual: storms and volume by year ---")
    g = df.groupby("year").agg(storms=("duration_h", "size"),
                               vol=("total_volume_km3", "sum"),
                               months=("month", "nunique"))
    g["vol_per_month"] = g.vol / g.months
    print(g.to_string(float_format=lambda x: f"{x:,.1f}"))
    full = g[g.months == 12]
    print(f"\nfull years only: volume per month varies "
          f"{full.vol_per_month.min():,.0f} to {full.vol_per_month.max():,.0f} km3 "
          f"({full.vol_per_month.max()/full.vol_per_month.min():.2f}x), "
          f"min {full.vol_per_month.idxmin()}, max {full.vol_per_month.idxmax()}")

    print("\n--- seasonal cycle, all years pooled ---")
    m = df.groupby("month").agg(storms=("duration_h", "size"),
                                vol=("total_volume_km3", "sum"))
    m["share"] = m.vol / m.vol.sum()
    print(m.to_string(float_format=lambda x: f"{x:,.3f}"))

    print("\n--- return periods from the real record ---")
    import severity
    sc = severity.fit(clean, n_years=years)
    print(sc.describe())
    # A T-year event is exceeded once every T years, so over `years` years it is
    # exceeded k = years/T times. The threshold is therefore the k-th largest value
    # in the record, NOT a fraction of the population: an earlier version divided
    # by the storm count and produced thresholds that fell as T rose.
    print(f"  {'T':>5} {'k':>6}  {'volume km3':>12} {'max int mm/hr':>15}")
    for T in (1, 2, 5, 10, 25):
        k = max(int(round(years / T)), 1)
        print(f"  {T:>5} {k:>6}  {sc.vol_sorted[-k]:>12.3f} "
              f"{sc.int_sorted[-k]:>15.1f}")
    print("  k is how many storms in the whole record exceed that threshold.")
    print(f"  With {len(sc.vol_sorted)/years:,.0f} storms a year, a per-storm return")
    print("  period only becomes rare in the extreme tail: see the note below.")

    print("\n--- what a percentile actually means at this population size ---")
    for p in (90, 99, 99.9, 99.99):
        n_exceed = len(sc.vol_sorted) * (100 - p) / 100
        print(f"  p{p:<6} exceeded by {n_exceed:>12,.0f} storms "
              f"= {n_exceed/years:>10,.0f} per year "
              f"-> T = {years/max(n_exceed,1e-9):.4f} yr")

    print("\n--- rainfall concentration, and the AGU 2020 poster's claim ---")
    curve, inv = severity.contribution_curve(clean)
    print(curve.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print("\n  storms needed for a given share of the rain:")
    for share, frac in inv.items():
        print(f"    {share:.0%}  <-  top {100*frac:5.2f}%")
    CMT_V, CMT_I = 0.01, 10.0
    cmt = clean[(clean.total_volume_km3 >= CMT_V)
                & (clean.max_intensity_mm_hr >= CMT_I)]
    c2, i2 = severity.contribution_curve(cmt)
    t13 = c2.loc[c2.top_frac == 0.13, "volume_share"].iloc[0]
    print(f"\n  with ST-CORA's CMT (vol>={CMT_V} km3 and int>={CMT_I} mm/hr): "
          f"{len(cmt):,} storms")
    print(f"    top 13% by volume -> {t13:.1%} of rain")
    print("    poster, Lower Mekong 2014-2019: long-lived 13% -> >97%")
    print("    Finding 31 showed this gap is largely partition granularity:")
    print("    at h=4 we resolve ~14x more storms per unit area than they did.")


if __name__ == "__main__":
    main()
