"""Build and persist a storm catalogue for a date range.

This is what the notebook calls. It gathers only the requested period, segments,
extracts attributes, and writes a Parquet table plus the tracklines as WKT.

    python src/catalogue.py --start 2020-01-01 --end 2020-01-05
    python src/catalogue.py --start 2020-01-01 --end 2020-01-31 --prominence 4

Or from a notebook:

    from catalogue import build
    df = build("2020-01-01", "2020-01-05")
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, PRODUCT, SOURCE  # noqa: E402
from imerg_io import load_range  # noqa: E402
from mergetree import build_merge_tree, hierarchy, segment_at  # noqa: E402
from segment import label_ccl, label_watershed, percolation_share  # noqa: E402
from storms import storm_table, track_wkt  # noqa: E402


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1]
                              ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build(start, end, *, source=None, product=None, method="mergetree",
          wet_threshold=1.0, prominence=4.0, min_voxels=6,
          allow_long=False, progress=True) -> pd.DataFrame:
    """Storm catalogue for [start, end] inclusive.

    `prominence` is the one parameter that decides what counts as a distinct
    storm. It is NOT scale-free: the storm count moves by roughly a factor of two
    for each doubling of h (measured, see docs/findings.md Run 6). Choose it
    for the scale of system you care about and state it alongside every number
    derived from the catalogue.
    """
    da = load_range(start, end, source=source, product=product,
                    allow_long=allow_long, progress=progress)
    R = da.values

    tree = None
    if method == "mergetree":
        # Build once, then the prominence can be re-cut without touching the data.
        tree = build_merge_tree(R, wet_threshold=wet_threshold)
        labels = segment_at(tree, R, prominence, min_voxels=min_voxels)
    elif method == "watershed":
        labels = label_watershed(R, wet_threshold=wet_threshold,
                                 prominence=prominence, min_voxels=min_voxels)
    elif method == "ccl":
        labels = label_ccl(R, threshold=wet_threshold, min_voxels=min_voxels)
    else:
        raise ValueError(f"unknown method {method!r}, "
                         "expected mergetree, watershed or ccl")

    params = {
        "method": method, "wet_threshold": wet_threshold,
        "prominence": prominence if method == "watershed" else None,
        "min_voxels": min_voxels,
        "source": source or SOURCE, "product": product or PRODUCT,
        "start": str(start), "end": str(end),
        "git_rev": _git_rev(),
        "percolation_share": round(percolation_share(labels), 4),
    }
    df = storm_table(R, labels, da.time.values, da.lat.values, da.lon.values,
                     params=params)
    if not df.empty:
        df["track_wkt"] = df["track"].map(track_wkt)
    if tree is not None and not df.empty:
        df = _attach_hierarchy(df, tree, prominence)
    return df


def _attach_hierarchy(df, tree, prominence):
    """Number of substorms each surviving system absorbed at this prominence.

    A substorm is a component whose own peak did not clear the prominence bar, so it
    was folded into a stronger neighbour. The count is a scale indicator: a storm
    with many substorms is a system that would fragment at a lower h.
    """
    h = hierarchy(tree, prominence)
    n_sub = {d["component"]: len(d["children"]) for d in h}
    deepest = {d["component"]: max([c["persistence"] for c in d["children"]],
                                   default=0.0) for d in h}
    order = sorted(n_sub, key=lambda c: -n_sub[c])
    # storm_id is assigned by label order, which segment_at derives from component
    # order, so rank-match rather than assume identity.
    df = df.copy()
    df["n_substorms"] = 0
    df["max_substorm_persistence"] = 0.0
    ranked = df.sort_values("n_voxels", ascending=False).index
    for idx, comp in zip(ranked, order):
        df.loc[idx, "n_substorms"] = n_sub[comp]
        df.loc[idx, "max_substorm_persistence"] = deepest[comp]
    return df


def save(df: pd.DataFrame, start, end, product=None, outdir=None) -> Path:
    """Write Parquet. The `track` column of tuples is dropped in favour of WKT,
    which round-trips through Parquet and opens in any GIS."""
    outdir = Path(outdir or DATA_PROCESSED)
    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir / f"storms_{product or PRODUCT}_{start}_{end}.parquet"
    out = df.drop(columns=["track"], errors="ignore")
    out.to_parquet(p, index=False)
    (p.with_suffix(".meta.json")).write_text(json.dumps(
        {c[6:]: df[c].iloc[0] for c in df.columns if c.startswith("param_")},
        indent=2, default=str), encoding="utf-8")
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--source", default=None)
    ap.add_argument("--product", default=None)
    ap.add_argument("--method", default="mergetree",
                    choices=["mergetree", "watershed", "ccl"])
    ap.add_argument("--wet-threshold", type=float, default=1.0)
    ap.add_argument("--prominence", type=float, default=4.0)
    ap.add_argument("--min-voxels", type=int, default=6)
    ap.add_argument("--allow-long", action="store_true")
    a = ap.parse_args()

    df = build(a.start, a.end, source=a.source, product=a.product,
               method=a.method, wet_threshold=a.wet_threshold,
               prominence=a.prominence, min_voxels=a.min_voxels,
               allow_long=a.allow_long)
    if df.empty:
        print("no storms found")
        return
    p = save(df, a.start, a.end, a.product)
    print(f"\n{len(df)} storms -> {p}")
    print(f"  total volume      {df.total_volume_km3.sum():.2f} km3")
    print(f"  percolation share {df['param_percolation_share'].iloc[0]:.4f}")
    print(f"  duration h        median {df.duration_h.median():.1f}, "
          f"p90 {df.duration_h.quantile(.9):.1f}, max {df.duration_h.max():.1f}")
    print(f"  truncated         {df.truncated_time.sum()} in time, "
          f"{df.truncated_space.sum()} in space")


if __name__ == "__main__":
    main()
