"""Catalogue a whole year, month by month, and concatenate.

A reference population is the prerequisite for any severity classification: a storm
is only "extreme" relative to a record. This builds one year; the full-archive job
is the same loop over more years, and is what true return periods require.

    .\\run.ps1 src\\build_year.py --year 2020 --prominence 4
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalogue import build, save  # noqa: E402
from config import DATA_PROCESSED, PRODUCT  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, nargs="+", required=True,
                    help="one year, or two for an inclusive range")
    ap.add_argument("--overwrite", action="store_true",
                    help="redo years whose output already exists")
    ap.add_argument("--prominence", type=float, default=4.0)
    ap.add_argument("--wet-threshold", type=float, default=1.0)
    ap.add_argument("--min-voxels", type=int, default=6)
    ap.add_argument("--source", default="local")
    ap.add_argument("--product", default=None)
    ap.add_argument("--months", type=int, nargs="*", default=None)
    ap.add_argument("--overlap-days", type=int, default=1,
                    help="pad each month by N days on both sides and keep "
                         "storms whose weighted centroid falls inside; "
                         "0 restores the old chunk-at-midnight behaviour")
    a = ap.parse_args()

    years = (list(range(a.year[0], a.year[1] + 1)) if len(a.year) == 2
             else [a.year[0]])
    for y in years:
        run_year(y, a)


def available_days(product):
    """Calendar dates the archive holds AND that are readable.

    Two separate problems, both of which abort a year if unhandled:
      - a day simply absent, e.g. a partial year like 2025 which ends 09-30;
      - a day present but corrupt. 20 such files exist in the Final archive
        (2022-05-12 and 19 days in 2025-09). They are indexed by filename, so
        without this they look available and the month dies mid-run.

    The corrupt list comes from `validate.py`, cached because the scan is slow.
    """
    from sources import LocalSource
    from validate import known_bad
    days = set(LocalSource(product=product).index())
    bad = known_bad(product or PRODUCT)
    if bad:
        print(f"  ({len(bad & days)} unreadable day(s) excluded; "
              f"run validate.py to refresh)", flush=True)
    return days - bad


def run_year(year: int, a) -> None:
    out = (DATA_PROCESSED /
           f"catalogue_{a.product or PRODUCT}_{year}_h{a.prominence:g}.parquet")
    months = a.months or list(range(1, 13))

    if out.exists() and not a.overwrite:
        # Resume must check the file actually covers what was asked for. A previous
        # run with --months writes the same filename, so a bare existence check
        # would silently skip the other ten months of that year.
        try:
            done = {int(x) for x in
                    pd.read_parquet(out, columns=["month"]).month.unique()}
        except Exception as e:
            print(f"{year}: existing file unreadable ({type(e).__name__}), redoing",
                  flush=True)
            done = set()
        missing_m = [m for m in months if m not in done]
        if not missing_m:
            print(f"{year}: already done, skipping ({out.name}, "
                  f"months {sorted(done)})", flush=True)
            return
        print(f"{year}: existing file covers months {sorted(done)}, "
              f"missing {missing_m}; rebuilding the year", flush=True)

    have = available_days(a.product) if a.source == "local" else None
    pad = dt.timedelta(days=a.overlap_days)
    parts, t_all = [], time.time()
    for m in months:
        last = calendar.monthrange(year, m)[1]
        m0, m1 = dt.date(year, m, 1), dt.date(year, m, last)

        # Segment a padded window, then keep only the storms that belong to this
        # month. Without the padding every storm alive at midnight on the 1st is cut
        # in two; that is only ~1% of storms but they are specifically the longest
        # ones, which is the exact tail a severity climatology depends on.
        s0, e0 = m0 - pad, m1 + pad
        if have is not None:
            want = {m0 + dt.timedelta(days=d) for d in range((m1 - m0).days + 1)}
            missing = want - have
            if missing:
                print(f"  {year}-{m:02d}: SKIPPED, {len(missing)} day(s) missing or "
                      f"unreadable (first {min(missing)})", flush=True)
                continue
            # Shrink the padding to whatever is actually available, rather than
            # letting a missing neighbouring day abort an otherwise complete month.
            while s0 < m0 and s0 not in have:
                s0 += dt.timedelta(days=1)
            while e0 > m1 and e0 not in have:
                e0 -= dt.timedelta(days=1)

        t = time.time()
        df = build(f"{s0}", f"{e0}", source=a.source, product=a.product,
                   method="mergetree", wet_threshold=a.wet_threshold,
                   prominence=a.prominence, min_voxels=a.min_voxels,
                   progress=False)
        n_raw = len(df)

        # Ownership rule: a storm belongs to the month containing its
        # volume-weighted centroid time. Unambiguous, and every storm in the padded
        # window is claimed by exactly one month, so nothing is double counted when
        # neighbouring months are concatenated.
        if len(df):
            wc = pd.to_datetime(df.wcentroid_time)
            keep = (wc.dt.year == year) & (wc.dt.month == m)
            df = df[keep].copy()
            # Truncation now means clipped by the PADDED window, which for an
            # interior month is a real edge of the record rather than an artefact
            # of the monthly chunking.
            # Only clear the flag when BOTH sides were padded. If one side could
            # not be padded, storms touching it really are at the edge of the
            # usable record. Conservative: this over-flags rather than under-flags.
            if s0 < m0 and e0 > m1:
                df["truncated_time"] = False

        df["month"] = m
        df["pad_left_days"] = (m0 - s0).days
        df["pad_right_days"] = (e0 - m1).days
        parts.append(df)
        print(f"  {year}-{m:02d}: {len(df):>7,} storms "
              f"(from {n_raw:,} in a {(e0-s0).days+1}-day window), "
              f"{df.total_volume_km3.sum():8.1f} km3, "
              f"{100*df.truncated_time.mean():4.1f}% time-truncated, "
              f"{time.time()-t:5.0f}s", flush=True)

    if not parts:
        print(f"{year}: no complete months, nothing written", flush=True)
        return
    res = pd.concat(parts, ignore_index=True)
    res["year"] = year
    res["storm_uid"] = (str(year) + "-" + res.month.astype(str)
                        + "-" + res.storm_id.astype(str))
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    res.drop(columns=["track"], errors="ignore").to_parquet(out, index=False)

    clean = res[~(res.truncated_time | res.truncated_space)]
    print(f"\n{len(res):,} storms in {year} -> {out}")
    print(f"  total volume     {res.total_volume_km3.sum():,.0f} km3")
    print(f"  untruncated      {len(clean):,} ({100*len(clean)/len(res):.1f}%)")
    print(f"  volume  p50 {clean.total_volume_km3.quantile(.5):.4f}  "
          f"p99 {clean.total_volume_km3.quantile(.99):.3f}  "
          f"max {clean.total_volume_km3.max():.2f} km3")
    print(f"  max int p50 {clean.max_intensity_mm_hr.quantile(.5):.1f}  "
          f"p99 {clean.max_intensity_mm_hr.quantile(.99):.1f}  "
          f"max {clean.max_intensity_mm_hr.max():.1f} mm/hr")
    print(f"  elapsed {(time.time()-t_all)/60:.1f} min")


if __name__ == "__main__":
    main()
