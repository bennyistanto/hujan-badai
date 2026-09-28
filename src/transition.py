"""Sea-to-land storm transitions, and the lead time they offer.

Why this matters
----------------
Most storms over the maritime continent form over water (69.9% of storm initiations
by weighted centroid, docs/findings.md Finding 49). For flood warning the question is
not where a storm formed but **how long it spent at sea before reaching land**, since
that interval is the warning lead time a nowcast could in principle exploit.

Two stages, because the second is expensive:

1. Classify every storm's start and end location as land or sea, using the rasterised
   province polygons. This needs no track parsing and covers the whole catalogue.
2. For the sea-to-land subset, walk the trackline vertex by vertex to find the first
   land contact, giving the actual over-water time rather than an upper bound from
   the storm's total duration.

    .\\run.ps1 src\\transition.py
    .\\run.ps1 src\\transition.py --min-volume 0.05
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, DT_HOURS, GRID_DEG  # noqa: E402
from geo import coast_distance_km, land_mask, lookup, province_grid  # noqa: E402

CLASSES = ["sea -> land", "sea -> sea", "land -> land", "land -> sea"]


def classify_points(lat, lon, mask, mlat, mlon) -> np.ndarray:
    return lookup(lat, lon, mask, mlat, mlon)


def parse_track(wkt: str):
    """Vertices from a WKT LINESTRING or POINT, as (lon, lat) arrays.

    The catalogue stores tracks as WKT because that round-trips through Parquet and
    opens in any GIS; the raw tuple column is dropped on save.
    """
    if not isinstance(wkt, str) or "EMPTY" in wkt:
        return None, None
    body = wkt[wkt.find("(") + 1: wkt.rfind(")")]
    try:
        pts = [p.strip().split() for p in body.split(",")]
        lon = np.array([float(p[0]) for p in pts])
        lat = np.array([float(p[1]) for p in pts])
    except (ValueError, IndexError):
        return None, None
    return lon, lat


def first_landfall(wkt: str, mask, mlat, mlon):
    """First land vertex: index, vertex count, and its position.

    Returns (idx, n_vertices, lat, lon); idx is None if the track never lands.
    """
    lon, lat = parse_track(wkt)
    if lon is None or len(lon) == 0:
        return None, 0, None, None
    onland = classify_points(lat, lon, mask, mlat, mlon)
    hits = np.flatnonzero(onland)
    if not hits.size:
        return None, len(lon), None, None
    i = int(hits[0])
    return i, len(lon), float(lat[i]), float(lon[i])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--min-volume", type=float, default=0.0,
                    help="restrict stage 2 to storms above this volume, km3")
    ap.add_argument("--year", type=int, nargs="*", default=None)
    a = ap.parse_args()

    from climatology import load, record_years
    cols = ["year", "month", "duration_h", "total_volume_km3",
            "max_intensity_mm_hr", "start_lat", "start_lon", "end_lat", "end_lon",
            "wcentroid_lat", "wcentroid_lon", "track_wkt",
            "truncated_time", "truncated_space"]
    df = load(cols=cols, h=a.h)
    if a.year:
        df = df[df.year.isin(a.year)]
    yrs = record_years(df)
    d = df[~(df.truncated_time | df.truncated_space)].dropna(
        subset=["start_lat", "end_lat"]).copy()
    print(f"{len(d):,} untruncated storms over {yrs:.2f} yr\n")

    mask, mlat, mlon = land_mask()
    d["start_land"] = classify_points(d.start_lat, d.start_lon, mask, mlat, mlon)
    d["end_land"] = classify_points(d.end_lat, d.end_lon, mask, mlat, mlon)
    d["transition"] = np.select(
        [~d.start_land & d.end_land, ~d.start_land & ~d.end_land,
         d.start_land & d.end_land, d.start_land & ~d.end_land],
        CLASSES, default="?")

    print("--- stage 1: where storms start and end ---")
    g = d.groupby("transition").agg(storms=("duration_h", "size"),
                                    per_year=("duration_h", lambda s: len(s) / yrs),
                                    volume=("total_volume_km3", "sum"),
                                    dur_med=("duration_h", "median"),
                                    dur_p99=("duration_h", lambda s: s.quantile(.99)),
                                    vol_med=("total_volume_km3", "median"))
    g["share"] = g.storms / g.storms.sum()
    g["vol_share"] = g.volume / g.volume.sum()
    print(g.reindex([c for c in CLASSES if c in g.index]).to_string(
        float_format=lambda x: f"{x:,.4f}"))

    sl = d[d.transition == "sea -> land"]
    print(f"\nsea -> land storms carry {g.loc['sea -> land','vol_share']:.1%} of the "
          f"rain from {g.loc['sea -> land','share']:.1%} of the storms")

    print("\n--- stage 2: time at sea before first landfall ---")
    sub = sl[sl.total_volume_km3 >= a.min_volume]
    print(f"walking {len(sub):,} tracks (volume >= {a.min_volume} km3)")
    idx, nv, flat, flon = [], [], [], []
    for w in sub.track_wkt.to_numpy():
        i, n, la, lo = first_landfall(w, mask, mlat, mlon)
        idx.append(i); nv.append(n); flat.append(la); flon.append(lo)
    sub = sub.assign(landfall_idx=idx, n_vertices=nv,
                     landfall_lat=flat, landfall_lon=flon)
    ok = sub[sub.landfall_idx.notna()].copy()
    ok["hours_at_sea"] = ok.landfall_idx.astype(float) * DT_HOURS
    ok["hours_over_land"] = (ok.n_vertices - 1 - ok.landfall_idx) * DT_HOURS

    print(f"  {len(ok):,} of {len(sub):,} have an identifiable landfall vertex")
    print(f"\n  hours at sea before landfall:")
    for q in (10, 25, 50, 75, 90, 99):
        print(f"    p{q:<3} {ok.hours_at_sea.quantile(q/100):6.1f} h")
    print(f"    max  {ok.hours_at_sea.max():6.1f} h")
    print(f"  fraction making landfall on their FIRST step (no lead time): "
          f"{(ok.landfall_idx == 0).mean():.1%}")

    print("\n  lead time by storm size (volume quartile):")
    ok["q"] = pd.qcut(ok.total_volume_km3, 4, labels=["Q1 small", "Q2", "Q3", "Q4 large"])
    q = ok.groupby("q", observed=True).agg(
        storms=("hours_at_sea", "size"),
        sea_med=("hours_at_sea", "median"),
        sea_p90=("hours_at_sea", lambda s: s.quantile(.9)),
        land_med=("hours_over_land", "median"),
        vol_med=("total_volume_km3", "median"))
    print(q.to_string(float_format=lambda x: f"{x:,.2f}"))

    # ---- where does landfall happen, and does lead time vary by coast? ----
    pr, pnames, plat, plon = province_grid()
    dist, dlat, dlon = coast_distance_km()
    pid = lookup(ok.landfall_lat, ok.landfall_lon, pr, plat, plon)
    ok["province"] = [pnames.get(int(i), "outside Indonesia") for i in pid]
    ok["offshore_km_at_start"] = lookup(ok.start_lat, ok.start_lon,
                                        dist, dlat, dlon)

    reg_file = DATA_PROCESSED / "regions_k3.parquet"
    if reg_file.exists():
        reg = pd.read_parquet(reg_file)
        rmap = {(r.glat, r.glon): r.region for r in reg.itertuples()}
        key = list(zip(np.floor(ok.landfall_lat), np.floor(ok.landfall_lon)))
        ok["region"] = [rmap.get(k, -1) for k in key]
        RN = {0: "monsoonal", 1: "transitional", 2: "equatorial", -1: "unassigned"}
        print("\n  lead time by climate region of landfall:")
        rg = ok.groupby("region").agg(
            storms=("hours_at_sea", "size"), sea_med=("hours_at_sea", "median"),
            sea_p90=("hours_at_sea", lambda s: s.quantile(.9)),
            vol_med=("total_volume_km3", "median"),
            offshore_med=("offshore_km_at_start", "median"))
        rg.index = [RN.get(i, i) for i in rg.index]
        print(rg.to_string(float_format=lambda x: f"{x:,.2f}"))
    else:
        print("\n  (regions_k3.parquet not found, skipping region breakdown)")

    print("\n  lead time by province of landfall, 14 busiest coasts:")
    pg = ok.groupby("province").agg(
        storms=("hours_at_sea", "size"),
        per_year=("hours_at_sea", lambda s: len(s) / yrs),
        sea_med=("hours_at_sea", "median"),
        sea_p90=("hours_at_sea", lambda s: s.quantile(.9)),
        vol_med=("total_volume_km3", "median"),
        offshore_med=("offshore_km_at_start", "median"))
    pg = pg.sort_values("storms", ascending=False).head(14)
    print(pg.to_string(float_format=lambda x: f"{x:,.2f}"))

    print(f"\n  a domain-wide median lead time of {ok.hours_at_sea.median():.1f} h "
          f"hides a range of {pg.sea_med.min():.1f} to {pg.sea_med.max():.1f} h "
          "between provinces.")

    out = DATA_PROCESSED / f"transitions_h{a.h:g}.parquet"
    ok.drop(columns=["track_wkt"]).to_parquet(out, index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
