"""Diurnal cycle of storm initiation, in LOCAL time, split by land and sea.

Where local time actually matters
---------------------------------
Segmentation is invariant to a uniform time shift: shifting the clock relabels the
time axis without touching voxel adjacency, so the objects are identical. Measured
(docs/findings.md Finding 48), what changes is only where chunk boundaries fall, and
chunk LENGTH dominates chunk ALIGNMENT by a wide margin.

So UTC is the right base for segmentation, and it stays right if the AOI is ever
extended globally, where "local time" is not even well defined for one domain.

Local time matters for **interpretation**. The land-sea diurnal cycle is the maritime
continent's defining signal, and it is only visible against a local clock. Indonesia
spans three zones, so each storm is converted using its own longitude.

    .\\run.ps1 src\\diurnal.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, GRID_DEG  # noqa: E402
from geo import land_mask  # noqa: E402

# Indonesia's three legal zones. WIB +7, WITA +8, WIT +9.
ZONE_EDGES = (112.5, 127.5)
ZONE_NAMES = ("WIB (+7)", "WITA (+8)", "WIT (+9)")


def utc_offset(lon: np.ndarray) -> np.ndarray:
    return np.where(lon < ZONE_EDGES[0], 7, np.where(lon < ZONE_EDGES[1], 8, 9))



def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--h", type=float, default=4.0)
    a = ap.parse_args()

    from climatology import load, record_years
    df = load(cols=["year", "month", "start_time", "wcentroid_time",
                    "wcentroid_lat", "wcentroid_lon", "total_volume_km3",
                    "duration_h", "truncated_time", "truncated_space"], h=a.h)
    yrs = record_years(df)
    d = df[~(df.truncated_time | df.truncated_space)].dropna(
        subset=["wcentroid_lat", "wcentroid_lon"]).copy()
    print(f"{len(d):,} untruncated storms over {yrs:.2f} yr")

    mask, mlat, mlon = land_mask()   # Natural Earth 10m, global
    iy = np.clip(((d.wcentroid_lat - mlat[0]) / GRID_DEG).round().astype(int),
                 0, mask.shape[0] - 1)
    ix = np.clip(((d.wcentroid_lon - mlon[0]) / GRID_DEG).round().astype(int),
                 0, mask.shape[1] - 1)
    d["land"] = mask[iy, ix] == 1
    print(f"land {d.land.mean():.1%}, sea {1-d.land.mean():.1%}\n")

    off = utc_offset(d.wcentroid_lon.to_numpy())
    utc_h = pd.to_datetime(d.start_time).dt.hour + \
        pd.to_datetime(d.start_time).dt.minute / 60.0
    d["local_h"] = (utc_h.to_numpy() + off) % 24
    d["utc_h"] = utc_h.to_numpy()

    print("storm initiation by hour, share of that group's storms")
    print(f"{'hour':>5}{'LAND local':>12}{'SEA local':>11}{'LAND utc':>11}"
          f"{'SEA utc':>10}")
    bins = np.arange(0, 25, 2)
    rows = []
    for lo_, hi_ in zip(bins[:-1], bins[1:]):
        r = {"hour": f"{lo_:02d}-{hi_:02d}"}
        for nm, sub in (("land", d[d.land]), ("sea", d[~d.land])):
            r[f"{nm}_local"] = ((sub.local_h >= lo_) & (sub.local_h < hi_)).mean()
            r[f"{nm}_utc"] = ((sub.utc_h >= lo_) & (sub.utc_h < hi_)).mean()
        rows.append(r)
    t = pd.DataFrame(rows)
    for _, r in t.iterrows():
        print(f"{r.hour:>5}{r.land_local:>12.4f}{r.sea_local:>11.4f}"
              f"{r.land_utc:>11.4f}{r.sea_utc:>10.4f}")

    pk = lambda s: t.hour[t[s].idxmax()]
    print(f"\npeak initiation window")
    print(f"  land, local time : {pk('land_local')}   sea, local time : {pk('sea_local')}")
    print(f"  land, UTC        : {pk('land_utc')}   sea, UTC        : {pk('sea_utc')}")
    amp = lambda s: t[s].max() / t[s].min()
    print(f"\ndiurnal amplitude (peak bin / trough bin)")
    print(f"  land {amp('land_local'):.2f}x   sea {amp('sea_local'):.2f}x")

    out = DATA_PROCESSED / f"diurnal_h{a.h:g}.parquet"
    t.to_parquet(out, index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
