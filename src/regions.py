"""Derive rainfall regions from the storm catalogue's own seasonality.

Why regions are mandatory here
------------------------------
Indonesia is not one climate. Measured on the 28-year catalogue, the domain-wide
wet-to-dry ratio is only 1.85x, because monsoonal, equatorial and anti-monsoonal
regimes partly cancel in the average (docs/findings.md Findings 18, 37). A single
domain-wide severity scale would therefore call a genuinely rare Nusa Tenggara
storm ordinary, because Papua's storms dominate the tail.

Method
------
Regions are **derived from our own data**, not imported from a published zoning we
have not verified. Storm volume is binned onto a coarse lat/lon grid by calendar
month, each cell's 12-month cycle is normalised to sum to 1, and the cells are
clustered on that shape. So the clustering sees *when* a cell rains, never how much,
and never where it is: a region is a set of cells sharing a seasonal cycle, and any
spatial coherence in the result is a check on the method rather than an input.

k is chosen by silhouette score over a range. The result should be compared against
published Indonesian monsoon zones afterwards, as a sanity check, not as an input.

    .\\run.ps1 src\\regions.py --grid 1.0 --kmax 6
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import os

os.environ.setdefault("OMP_NUM_THREADS", "8")  # silence the MKL kmeans warning

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED  # noqa: E402

REGION_FILE = DATA_PROCESSED / "regions.parquet"


def seasonal_grid(df: pd.DataFrame, grid: float = 1.0,
                  min_storms: int = 200) -> tuple[pd.DataFrame, np.ndarray]:
    """Volume by (cell, month), normalised to a seasonal shape per cell.

    Cells with too few storms are dropped: a 12-month shape estimated from a
    handful of storms is noise, and it would otherwise form its own cluster.
    """
    d = df.dropna(subset=["wcentroid_lat", "wcentroid_lon"])
    glat = np.floor(d.wcentroid_lat / grid) * grid
    glon = np.floor(d.wcentroid_lon / grid) * grid
    t = pd.DataFrame({"glat": glat, "glon": glon, "month": d.month,
                      "vol": d.total_volume_km3})
    piv = (t.pivot_table(index=["glat", "glon"], columns="month", values="vol",
                         aggfunc="sum", fill_value=0.0)
             .reindex(columns=range(1, 13), fill_value=0.0))
    counts = t.groupby(["glat", "glon"]).size()
    keep = counts[counts >= min_storms].index
    piv = piv.loc[piv.index.intersection(keep)]
    tot = piv.sum(axis=1).to_numpy()
    shape = piv.to_numpy() / np.where(tot > 0, tot, 1)[:, None]
    return piv, shape


def choose_k(shape: np.ndarray, kmin: int = 2, kmax: int = 6, seed: int = 0):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    out = []
    for k in range(kmin, kmax + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(shape)
        out.append((k, float(silhouette_score(shape, km.labels_)), km))
    return out


def label_regions(piv: pd.DataFrame, km) -> pd.DataFrame:
    """Attach cluster ids, ordered by peak month so the numbering is meaningful."""
    lab = km.labels_
    centres = km.cluster_centers_
    peak = centres.argmax(axis=1) + 1                 # peak calendar month
    order = np.argsort(peak)
    remap = {old: new for new, old in enumerate(order)}
    out = piv.reset_index()[["glat", "glon"]].copy()
    out["region"] = [remap[x] for x in lab]
    out["peak_month"] = [peak[x] for x in lab]
    return out, centres[order], peak[order]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", type=float, default=1.0)
    ap.add_argument("--kmin", type=int, default=2)
    ap.add_argument("--kmax", type=int, default=6)
    ap.add_argument("--min-storms", type=int, default=200)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--k", type=int, default=None,
                    help="force k instead of taking the silhouette best")
    a = ap.parse_args()

    from climatology import load
    df = load(cols=["year", "month", "total_volume_km3", "max_intensity_mm_hr",
                    "wcentroid_lat", "wcentroid_lon",
                    "truncated_time", "truncated_space"], h=a.h)
    print(f"catalogue {len(df):,} storms")

    piv, shape = seasonal_grid(df, a.grid, a.min_storms)
    print(f"{len(piv):,} cells of {a.grid} deg with >= {a.min_storms} storms\n")

    print("choosing k by silhouette:")
    res = choose_k(shape, a.kmin, a.kmax)
    for k, sil, _ in res:
        print(f"  k={k}  silhouette {sil:.4f}")
    best_k, best_sil, best_km = max(res, key=lambda r: r[1])
    if a.k is not None:
        sil_best = best_k
        best_k, best_sil, best_km = next(r for r in res if r[0] == a.k)
        print(f"-> k={best_k} forced (silhouette {best_sil:.4f}); "
              f"silhouette preferred k={sil_best}")
        print("   Silhouette rewards few well-separated clusters, so it can mask")
        print("   a real third regime. Judge k on the seasonal shapes too.")
    else:
        print(f"-> k={best_k} (silhouette {best_sil:.4f})")
    print()

    reg, centres, peaks = label_regions(piv, best_km)
    out_file = (REGION_FILE if a.k is None else
                REGION_FILE.with_name(f"regions_k{best_k}.parquet"))
    reg.to_parquet(out_file, index=False)

    print("region seasonal shapes, share of that region's annual rain by month:")
    hdr = "  reg  cells  peak " + " ".join(f"{m:>5}" for m in range(1, 13))
    print(hdr)
    for i in range(best_k):
        n = int((reg.region == i).sum())
        row = " ".join(f"{v:5.3f}" for v in centres[i])
        print(f"  {i:>3} {n:>6} {peaks[i]:>5}  {row}")

    print("\nregion extents and totals:")
    vol = piv.sum(axis=1).to_numpy()
    reg["vol"] = vol
    g = reg.groupby("region").agg(cells=("glat", "size"),
                                  lat_min=("glat", "min"), lat_max=("glat", "max"),
                                  lon_min=("glon", "min"), lon_max=("glon", "max"),
                                  vol=("vol", "sum"))
    g["share"] = g.vol / g.vol.sum()
    print(g.to_string(float_format=lambda x: f"{x:,.2f}"))

    print("\nseasonal contrast within each region (max month / min month):")
    for i in range(best_k):
        c = centres[i]
        print(f"  region {i}: {c.max()/c.min():5.2f}x  "
              f"peak {c.argmax()+1:>2}, trough {c.argmin()+1:>2}")
    dom = df.groupby("month").total_volume_km3.sum().to_numpy()
    dom = dom / dom.sum()
    print(f"  domain-wide: {dom.max()/dom.min():5.2f}x  "
          f"peak {dom.argmax()+1:>2}, trough {dom.argmin()+1:>2}")
    print("\nIf the regional contrasts exceed the domain-wide one, the regimes were")
    print("cancelling in the average and the breakdown was necessary.")
    print(f"\nwrote {out_file}")


if __name__ == "__main__":
    main()
