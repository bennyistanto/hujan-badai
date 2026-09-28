"""Diagnostics on the IMERG cube. Every number quoted in docs/findings.md
should be reproducible by a command printed in this file's docstring.

Examples
--------
python src/probe.py --start 2020-01-01 --end 2020-01-05
python src/probe.py --start 2020-01-01 --end 2020-01-05 --subregions
python src/probe.py --start 2020-01-01 --end 2020-01-05 --advection
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imerg_io import load_range, cell_area_m2  # noqa: E402
from config import DT_HOURS, GRID_DEG  # noqa: E402

# 26-neighbour system in space and time, as specified in Laverde-Barajas et al. 2019.
# scipy's default is 6-connectivity, which is NOT what the papers describe.
STRUCT_26 = np.ones((3, 3, 3), dtype=bool)

DEFAULT_THRESHOLDS = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0)

# Named windows as (lat_slice_deg, lon_slice_deg)
SUBREGIONS = {
    "full AOI":       ((-11.6, 6.6), (94.4, 141.6)),
    "Java 5x5deg":    ((-9.0, -4.0), (105.0, 110.0)),
    "Jakarta 2x2deg": ((-7.0, -5.0), (105.6, 107.6)),
}


def wet_fractions(R: np.ndarray, thresholds=DEFAULT_THRESHOLDS) -> dict:
    return {t: float((R >= t).mean()) for t in thresholds}


def label_stats(R: np.ndarray, threshold: float) -> dict:
    """3D connected-component labelling at one threshold, with percolation metric."""
    S = R >= threshold
    wet = int(S.sum())
    if wet == 0:
        return dict(threshold=threshold, n_objects=0, wet_voxels=0)
    lab, n = ndi.label(S, structure=STRUCT_26)
    counts = np.bincount(lab.ravel())[1:]
    order = np.argsort(counts)[::-1]
    biggest = int(order[0]) + 1
    tt, yy, xx = np.where(lab == biggest)
    return dict(
        threshold=threshold,
        n_objects=int(n),
        wet_voxels=wet,
        largest=int(counts[order[0]]),
        largest_share=float(counts[order[0]]) / wet,
        top10=counts[order[:10]].tolist(),
        median_size=float(np.median(counts)),
        n_below_6vox=int((counts < 6).sum()),
        largest_hours=float((tt.max() - tt.min() + 1) * DT_HOURS),
        largest_lat_cells=int(yy.max() - yy.min() + 1),
        largest_lon_cells=int(xx.max() - xx.min() + 1),
    )


def phase_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """Integer-pixel displacement of b relative to a by phase correlation."""
    A, B = np.fft.fft2(a), np.fft.fft2(b)
    X = A * np.conj(B)
    X /= np.abs(X) + 1e-9
    c = np.fft.ifft2(X).real
    dy, dx = np.unravel_index(np.argmax(c), c.shape)
    if dy > a.shape[0] // 2:
        dy -= a.shape[0]
    if dx > a.shape[1] // 2:
        dx -= a.shape[1]
    return int(dy), int(dx)


def advection_stats(R: np.ndarray, box=(slice(30, 110), slice(60, 200))) -> dict:
    """Frame-to-frame displacement over a sub-box.

    Caveat, and it matters: this is a domain-scale estimate. Phase correlation is
    dominated by the largest-amplitude feature in the window and is quantised to whole
    grid cells, so sub-cell motion reads as zero and a single fast-moving cell inside a
    slow field will not show up. Treat the result as evidence about the bulk field,
    not about every storm.
    """
    disp = []
    for t in range(R.shape[0] - 1):
        a, b = np.log1p(R[t][box]), np.log1p(R[t + 1][box])
        if a.max() < 1 or b.max() < 1:
            continue
        disp.append(phase_shift(b, a))
    d = np.array(disp)
    speed_cells = np.hypot(d[:, 0], d[:, 1])
    km_per_cell = GRID_DEG * 111.32
    return dict(
        n=len(d),
        pct={q: float(np.percentile(speed_cells, q)) for q in (50, 75, 90, 95, 99)},
        km_per_cell=km_per_cell,
        frac_over_1_cell=float((speed_cells > 1.0).mean()),
        frac_over_diag=float((speed_cells > np.sqrt(3)).mean()),
    )


def total_volume_km3(R: np.ndarray, lat: np.ndarray, mask=None) -> float:
    """Rain volume. R is mm/hr; depth per step is R * DT_HOURS mm."""
    area = cell_area_m2(lat)[None, :, None]          # m2
    depth_m = R * DT_HOURS / 1000.0                  # mm/hr -> m per step
    vol = depth_m * area                             # m3
    if mask is not None:
        vol = np.where(mask, vol, 0.0)
    return float(vol.sum() / 1e9)                    # m3 -> km3


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--thresholds", type=float, nargs="*", default=list(DEFAULT_THRESHOLDS))
    ap.add_argument("--subregions", action="store_true")
    ap.add_argument("--advection", action="store_true")
    ap.add_argument("--source", default=None,
                    help="local | opendap | gee. Default from config.SOURCE")
    a = ap.parse_args()

    da = load_range(a.start, a.end, source=a.source)
    R = da.values
    lat = da["lat"].values
    from config import SOURCE
    print(f"source {a.source or SOURCE}")
    print(f"window {a.start} .. {a.end}   cube {R.shape}   "
          f"{R.nbytes/1e9:.2f} GB float32")
    print(f"NaN fraction {np.isnan(R).mean():.5f}   max {np.nanmax(R):.2f} mm/hr")
    print(f"total rain volume over window: {total_volume_km3(R, lat):.3f} km3")

    print("\nwet fraction")
    for t, f in wet_fractions(R, a.thresholds).items():
        print(f"  >= {t:5.1f} mm/h : {f:.4f}")

    print("\n3D connected-component labelling, 26-connectivity")
    print(f"  {'thr':>5} {'n_obj':>7} {'wet_vox':>10} {'largest':>10} "
          f"{'share':>7} {'dur_h':>7} {'<6vox':>7}")
    for t in a.thresholds:
        s = label_stats(R, t)
        if not s.get("n_objects"):
            continue
        print(f"  {s['threshold']:5.1f} {s['n_objects']:7d} {s['wet_voxels']:10d} "
              f"{s['largest']:10d} {s['largest_share']:6.1%} "
              f"{s['largest_hours']:7.1f} {s['n_below_6vox']:7d}")
    print("  'share' is the fraction of all wet voxels inside the single largest")
    print("  object. Above roughly 0.20 the labelling has percolated and is not")
    print("  producing storm objects.")

    if a.subregions:
        print("\npercolation vs domain size, threshold 1.0 mm/h")
        for name, ((la0, la1), (lo0, lo1)) in SUBREGIONS.items():
            sub = da.sel(lat=slice(la0, la1), lon=slice(lo0, lo1)).values
            s = label_stats(sub, 1.0)
            print(f"  {name:16s} cells={sub.size:9d} n_obj={s['n_objects']:5d} "
                  f"wet={100*s['wet_voxels']/sub.size:4.1f}% "
                  f"largest={s['largest_share']:5.1%} of wet")

    if a.advection:
        s = advection_stats(R)
        print(f"\nframe-to-frame displacement, n={s['n']} steps "
              f"({s['km_per_cell']:.1f} km per cell, 0.5 h per step)")
        for q, v in s["pct"].items():
            print(f"  p{q:<3d} = {v:5.2f} cells = {v*s['km_per_cell']*2:5.1f} km/h "
                  f"= {v*s['km_per_cell']*2/3.6:4.1f} m/s")
        print(f"  fraction of steps over 1 cell:      {s['frac_over_1_cell']:.3f}")
        print(f"  fraction over sqrt(3) (26-conn):    {s['frac_over_diag']:.3f}")
        print("  Caveat: domain-scale phase correlation, quantised to whole cells.")
        print("  It measures the bulk field, not individual fast-moving storms.")


if __name__ == "__main__":
    main()
