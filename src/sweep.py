"""Sensitivity sweep of the segmentation prominence h.

Every parameter in this project started as an inheritance from a study over the
Lower Mekong. The point of this script is to find out which of them we are
entitled to keep, measured on Indonesian data.

    python src/sweep.py --months 2020-01 2020-08 --h 1 2 3 4 6 8 12

Reports per setting: storm count, volume and duration quantiles, the percolation
share, and the fraction of wet voxels that ended up inside some storm.

A parameter is called **stable** here if a plus or minus 20% change moves the storm
count by less than about 10%. Measured on a 5-day window h fails that badly, the
count roughly halving per doubling of h. This script is what settles whether that
holds over full months and across seasons.
"""
from __future__ import annotations

import argparse
import calendar
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED  # noqa: E402
from imerg_io import load_range  # noqa: E402
from mergetree import build_merge_tree, segment_at  # noqa: E402
from segment import label_watershed, percolation_share  # noqa: E402
from storms import storm_table  # noqa: E402

# Coarse values map the shape of the response; 3.2 and 4.8 are h_nominal -/+ 20%
# and exist solely so the stability criterion can actually be evaluated. A grid of
# only doublings cannot test a plus-or-minus-20% claim, which is the mistake this
# list is built to avoid.
H_NOMINAL = 4.0
DEFAULT_H = (1.0, 2.0, 3.2, 4.0, 4.8, 8.0)


def month_bounds(ym: str) -> tuple[str, str]:
    y, m = (int(x) for x in ym.split("-"))
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def sweep_month(ym: str, hs=DEFAULT_H, wet_threshold=1.0, min_voxels=6,
                source="local", product=None, method="mergetree") -> pd.DataFrame:
    start, end = month_bounds(ym)
    print(f"\n=== {ym} ({start} .. {end}) ===", flush=True)
    t0 = time.time()
    da = load_range(start, end, source=source, product=product, progress=False)
    R = da.values
    wet = int((R >= wet_threshold).sum())
    print(f"  cube {R.shape}, loaded in {time.time()-t0:.0f}s, "
          f"wet voxels {wet:,} ({100*wet/R.size:.1f}%)", flush=True)

    tree = None
    if method == "mergetree":
        # Built once; every h is then a cut, which is where the 8x saving comes from.
        t = time.time()
        tree = build_merge_tree(R, wet_threshold=wet_threshold)
        print(f"  merge tree: {len(tree):,} components in {time.time()-t:.0f}s",
              flush=True)

    rows = []
    for h in hs:
        t = time.time()
        if tree is not None:
            lab = segment_at(tree, R, h, min_voxels=min_voxels)
        else:
            lab = label_watershed(R, wet_threshold=wet_threshold, prominence=h,
                                  min_voxels=min_voxels)
        df = storm_table(R, lab, da.time.values, da.lat.values, da.lon.values)
        c = np.bincount(lab.ravel())
        c[0] = 0
        rows.append({
            "month": ym, "h": h, "method": method,
            "n_storms": int((c > 0).sum()),
            "percolation": percolation_share(lab),
            "captured": float(c.sum() / wet) if wet else 0.0,
            "vol_total_km3": float(df.total_volume_km3.sum()) if len(df) else 0.0,
            "vol_med_km3": float(df.total_volume_km3.median()) if len(df) else 0.0,
            "vol_p95_km3": float(df.total_volume_km3.quantile(.95)) if len(df) else 0.0,
            "dur_med_h": float(df.duration_h.median()) if len(df) else 0.0,
            "dur_p95_h": float(df.duration_h.quantile(.95)) if len(df) else 0.0,
            "area_p95_km2": float(df.max_area_km2.quantile(.95)) if len(df) else 0.0,
            "trunc_frac": float((df.truncated_time | df.truncated_space).mean())
                          if len(df) else 0.0,
            "sec": round(time.time() - t, 1),
        })
        r = rows[-1]
        print(f"  h={h:<5} storms={r['n_storms']:>7,}  perc={r['percolation']:.4f}  "
              f"capt={r['captured']:.3f}  dur_med={r['dur_med_h']:.1f}h  "
              f"{r['sec']:.0f}s", flush=True)
    return pd.DataFrame(rows)


def stability(df: pd.DataFrame, nominal: float = H_NOMINAL) -> pd.DataFrame:
    """Fractional change in storm count per step in h, against the 10% criterion.

    The criterion is defined for a plus-or-minus-20% change in h, so a step larger
    than that cannot decide it either way. Those rows are reported as "n/a" rather
    than silently counted as passes, which an earlier version did.
    """
    out = []
    for month, g in df.groupby("month", sort=False):
        g = g.sort_values("h").reset_index(drop=True)
        for i in range(1, len(g)):
            h0, h1 = g.h[i - 1], g.h[i]
            n0, n1 = g.n_storms[i - 1], g.n_storms[i]
            dh = (h1 - h0) / h0
            dn = (n1 - n0) / n0 if n0 else float("nan")
            verdict = ("n/a - step too big" if abs(dh) > 0.25
                       else "stable" if abs(dn) < 0.10 else "UNSTABLE")
            out.append({"month": month, "h_from": h0, "h_to": h1,
                        "d_h_frac": round(dh, 3), "d_count_frac": round(dn, 3),
                        "verdict": verdict})
    s = pd.DataFrame(out)

    # The decisive test: the full -20% to +20% span around the nominal h.
    lo, hi = round(nominal * 0.8, 2), round(nominal * 1.2, 2)
    for month, g in df.groupby("month", sort=False):
        have = set(g.h.round(2))
        if lo in have and hi in have:
            n_lo = int(g.loc[g.h.round(2) == lo, "n_storms"].iloc[0])
            n_hi = int(g.loc[g.h.round(2) == hi, "n_storms"].iloc[0])
            span = abs(n_hi - n_lo) / n_lo
            s = pd.concat([s, pd.DataFrame([{
                "month": month, "h_from": lo, "h_to": hi,
                "d_h_frac": 0.40, "d_count_frac": round((n_hi - n_lo) / n_lo, 3),
                "verdict": ("STABLE over +/-20%" if span < 0.10
                            else "UNSTABLE over +/-20%")}])], ignore_index=True)
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--months", nargs="+", required=True, help="e.g. 2020-01 2020-08")
    ap.add_argument("--h", type=float, nargs="+", default=list(DEFAULT_H))
    ap.add_argument("--wet-threshold", type=float, default=1.0)
    ap.add_argument("--min-voxels", type=int, default=6)
    ap.add_argument("--source", default="local")
    ap.add_argument("--product", default=None)
    ap.add_argument("--method", default="mergetree",
                    choices=["mergetree", "watershed"])
    a = ap.parse_args()

    parts = [sweep_month(m, a.h, a.wet_threshold, a.min_voxels, a.source,
                         a.product, a.method)
             for m in a.months]
    df = pd.concat(parts, ignore_index=True)

    pd.set_option("display.width", 200)
    print("\n\n===== SWEEP RESULT =====\n")
    print(df.round(4).to_string(index=False))

    print("\n----- storm count vs h -----")
    piv = df.pivot(index="h", columns="month", values="n_storms")
    print(piv.to_string())

    print("\n----- ratio between months (is the response seasonal?) -----")
    if piv.shape[1] == 2:
        a_, b_ = piv.columns
        print((piv[a_] / piv[b_]).round(3).to_string())

    print("\n----- stability of the storm count -----")
    print(stability(df).round(4).to_string(index=False))
    print("\nThe criterion is a plus-or-minus-20% change in h moving the count under")
    print("10%. Steps larger than 25% cannot decide it and are marked 'n/a'. The last")
    print("rows span the full -20% to +20% range and are the decisive test.")

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out = DATA_PROCESSED / f"sweep-prominence-{a.method}.csv"
    df.to_csv(out, index=False)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
