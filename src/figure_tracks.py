"""Render the storm-track map used at the top of the README.

A PNG rather than anything interactive, because GitHub does not run JavaScript in a
README. It is drawn from the catalogue by the same conventions as the dashboard: one
line per storm, tracing the volume-weighted centre, coloured by peak intensity.

    python src/figure_tracks.py                        # December 2020, every storm
    python src/figure_tracks.py --start 2019-12-31 --end 2020-01-01
    python src/figure_tracks.py --min-volume 0.05 --out docs/img/tracks_big.png

Whatever period and floor are chosen get written into the PNG's own caption strip, so
the image cannot be separated from the selection rule that produced it. That is
Finding 67: a display limit is a selection rule, and an unstated one manufactures
patterns.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import PowerNorm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AOI, DATA_PROCESSED, PRODUCT, REPO  # noqa: E402

LAND_JSON = REPO / "site" / "data" / "land_domain.json"

BG = "#0f1319"
LAND = "#2b323b"
EDGE = "#49525e"
INK = "#e8e6e2"
FAINT = "#6b7480"


def load_tracks(start, end, product, h, min_volume):
    """Storms alive in the window, with their tracklines as coordinate arrays."""
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    frames = []
    for y in range(t0.year, t1.year + 1):
        f = DATA_PROCESSED / f"catalogue_{product}_{y}_h{h:g}.parquet"
        if not f.exists():
            continue
        d = pd.read_parquet(f, columns=["start_time", "end_time", "track_wkt",
                                        "total_volume_km3", "max_intensity_mm_hr",
                                        "duration_h", "n_timesteps"])
        d = d[(d.start_time <= t1) & (d.end_time >= t0)]
        frames.append(d)
    if not frames:
        raise SystemExit(f"no catalogue covering {start} to {end}")
    d = pd.concat(frames, ignore_index=True)
    n_all = len(d)
    if min_volume:
        d = d[d.total_volume_km3 >= min_volume]
    return d, n_all


_NUM = r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)"


def wkt_segments(wkt):
    import re
    pts = [(float(a), float(b)) for a, b in re.findall(_NUM, wkt)]
    return np.asarray(pts) if len(pts) > 1 else None


def draw(d, start, end, out, min_volume, n_all, width=2400, dpi=200,
         lw=0.55, alpha=0.75):
    lat0, lat1 = AOI["lat_min"], AOI["lat_max"]
    lon0, lon1 = AOI["lon_min"], AOI["lon_max"]
    aspect = (lat1 - lat0) / (lon1 - lon0)

    fig_w = width / dpi
    strip = 0.78                          # caption strip height, inches
    fig_h = fig_w * aspect + strip
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=BG)
    ax = fig.add_axes([0, strip / fig_h, 1, 1 - strip / fig_h])
    ax.set_facecolor(BG)
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    # No set_aspect: the figure height is already the AOI's own aspect ratio, so one
    # degree of longitude and one of latitude are the same length on the page.
    # Asking matplotlib to enforce it as well makes it resize the axes box and crop.
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    if LAND_JSON.exists():
        land = json.loads(LAND_JSON.read_text(encoding="utf-8"))
        polys = []
        for feat in land["features"]:
            g = feat["geometry"]
            parts = ([g["coordinates"]] if g["type"] == "Polygon"
                     else g["coordinates"])
            for poly in parts:
                polys.append(np.asarray(poly[0]))
        for p in polys:
            ax.fill(p[:, 0], p[:, 1], color=LAND, zorder=1, linewidth=0)
            ax.plot(p[:, 0], p[:, 1], color=EDGE, linewidth=0.35, zorder=2)

    segs, vals = [], []
    for wkt, inten in zip(d.track_wkt, d.max_intensity_mm_hr):
        pts = wkt_segments(wkt)
        if pts is None:
            continue
        segs.append(pts)
        vals.append(inten)

    # PowerNorm(0.5) is a square-root stretch, matching the dashboard's colour scale so
    # a colour means the same thing in both places.
    lc = LineCollection(segs, cmap="turbo",
                        norm=PowerNorm(0.5, vmin=1.0, vmax=60.0),
                        linewidths=lw, alpha=alpha, zorder=3,
                        capstyle="round")
    lc.set_array(np.asarray(vals))
    ax.add_collection(lc)

    # Caption strip, so the image carries its own provenance.
    cap = fig.add_axes([0, 0, 1, strip / fig_h])
    cap.set_facecolor(BG)
    cap.axis("off")
    period = (f"{pd.Timestamp(start):%d %b %Y} to {pd.Timestamp(end):%d %b %Y}")
    rule = ("every storm" if not min_volume
            else f"storms above {min_volume:g} km³ ({len(segs):,} of {n_all:,})")
    cap.text(0.012, 0.66, f"{len(segs):,} storm tracks   ·   {period}",
             color=INK, fontsize=9.5, va="center", ha="left", weight="medium")
    cap.text(0.012, 0.26,
             f"GPM IMERG Final V07  ·  merge-tree segmentation, h = 4.0 mm/hr  "
             f"·  {rule}  ·  line colour is peak intensity",
             color=FAINT, fontsize=7.4, va="center", ha="left")

    # Colour bar, drawn by hand so it sits in the caption strip.
    cb = fig.add_axes([0.72, 0.40 / fig_h, 0.25, 0.10 / fig_h])
    grad = np.linspace(0, 1, 256)[None, :]
    cb.imshow(grad, aspect="auto", cmap="turbo")
    cb.set_yticks([])
    cb.set_xticks([])
    for v in (1, 10, 25, 60):
        frac = float(PowerNorm(0.5, vmin=1.0, vmax=60.0)(v))
        cap.text(0.72 + 0.25 * frac, 0.22, f"{v}", color=FAINT, fontsize=6.6,
                 ha="center", va="center")
    for s in cb.spines.values():
        s.set_visible(False)
    cb.text(-0.02, 0.5, "mm/hr", color=FAINT, fontsize=6.8, ha="right",
            va="center", transform=cb.transAxes)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, facecolor=BG)
    plt.close(fig)
    kb = out.stat().st_size / 1024
    print(f"  {out.relative_to(REPO)}  {len(segs):,} tracks  {kb:,.0f} KB  "
          f"{int(fig_w*dpi)}x{int(fig_h*dpi)} px")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2020-12-01")
    ap.add_argument("--end", default="2020-12-31 23:59")
    ap.add_argument("--product", default=PRODUCT)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--min-volume", type=float, default=0.0,
                    help="drop storms below this volume in km3; 0 keeps every one")
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--linewidth", type=float, default=0.55)
    ap.add_argument("--alpha", type=float, default=0.75)
    ap.add_argument("--out", default="docs/img/storm_tracks.png")
    a = ap.parse_args()

    d, n_all = load_tracks(a.start, a.end, a.product, a.h, a.min_volume)
    print(f"{n_all:,} storms in window, {len(d):,} after the volume floor")
    draw(d, a.start, a.end, REPO / a.out, a.min_volume, n_all, a.width,
         lw=a.linewidth, alpha=a.alpha)


if __name__ == "__main__":
    main()
