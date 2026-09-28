"""Repair or extend the local IMERG archive.

The acquisition notebook (`references/notebook/...ipynb` section 5.1 Step 1) used
GES DISC **THREDDS NCSS**. That service is gone: it now answers **HTTP 410** and
returns an HTML error page, so it cannot be used to repair anything.

Two routes remain, and both reproduce the archive's exact 182 x 472 grid because
both cut on global indices `lat[784:965]`, `lon[2744:3215]`, verified to match the
existing files to float32 precision:

    opendap  (default)  server-side subset, about 0.07 MB per granule
    global              whole granule then clip locally, about 8.1 MB per granule

Measured on one granule: 0.070 MB / 4.8 s against 8.1 MB / 5.9 s, so `opendap`
moves roughly 100x less data for the same result. `global` exists because it needs
nothing but a file server, and is the fallback if Hyrax is unavailable.

Bounding box from the notebook's own output: north 6.550, south -11.550,
west 94.450, east 141.550.

Usage
-----
    .\\run.ps1 src\\download.py --verify 2020-06-01
    .\\run.ps1 src\\download.py --bad-days --out "G:\\temp\\imerg\\_repair_final"
    .\\run.ps1 src\\download.py --start 2025-09-01 --end 2025-09-30 --out <dir>
    .\\run.ps1 src\\download.py --bad-days --route global --out <dir>
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (AOI_SHAPE, CMR_SHORT_NAMES, CMR_VERSION, PRODUCT,  # noqa: E402
                    STEPS_PER_DAY, UNITS, VAR)
from sources import OPeNDAPSource, aoi_indices  # noqa: E402

# From the notebook's calculate_bbox(buffer=0.5) over the Indonesia land mask.
NORTH, SOUTH, WEST, EAST = 6.550, -11.550, 94.450, 141.550
MIN_BYTES = 10_000


def short_name(product: str) -> str:
    return CMR_SHORT_NAMES[(product or PRODUCT).lower()]


def filename(day: dt.date, product: str) -> str:
    return (f"{short_name(product)}_{CMR_VERSION}_subset_{day:%Y%m%d}_"
            f"{day.year}{day:%j}_halfhourly.nc4")


def validate(path: Path) -> tuple[bool, str]:
    """The notebook's own checks, plus the grid shape, so a repaired file meets
    the same bar as the originals."""
    if not path.exists():
        return False, "missing"
    if path.stat().st_size < MIN_BYTES:
        return False, "too_small"
    try:
        with xr.open_dataset(path, decode_times=False) as ds:
            if VAR not in ds.data_vars:
                return False, "missing_variable"
            if "time" not in ds.dims:
                return False, "missing_time_dim"
            if ds.sizes["time"] != STEPS_PER_DAY:
                return False, f"unexpected_time_steps_{ds.sizes['time']}"
            if (ds.sizes.get("lat"), ds.sizes.get("lon")) != AOI_SHAPE:
                return False, f"grid_{ds.sizes.get('lat')}x{ds.sizes.get('lon')}"
    except Exception as e:
        return False, f"netcdf_error_{type(e).__name__}"
    return True, "valid"


def write_day(da: xr.DataArray, path: Path) -> None:
    """Write in the archive's own layout, atomically."""
    da = da.rename(VAR)
    da.attrs.setdefault("units", UNITS)
    tmp = path.with_suffix(".tmp.nc4")
    da.to_dataset(name=VAR).to_netcdf(
        tmp, format="NETCDF4",
        encoding={VAR: {"zlib": True, "complevel": 4, "dtype": "float32"}})
    os.replace(tmp, path)


def fetch_opendap(day: dt.date, product: str) -> xr.DataArray:
    """Server-side subset. Reuses the tested source, including its assertion that
    the day's 48 frames are distinct."""
    return OPeNDAPSource(product=product).fetch_day(day)


def fetch_global(day: dt.date, product: str) -> xr.DataArray:
    """Whole global granules over HTTPS, clipped locally on the same indices.

    Slower and about 100x more data, but needs only a file server. Used when
    Hyrax is unavailable.
    """
    import io
    import netCDF4 as nc4
    import requests

    src = OPeNDAPSource(product=product)
    j0, j1, i0, i1 = aoi_indices()
    urls = src.granule_urls(day)
    sess = src.session()

    frames, lat, lon = [], None, None
    for u in urls:
        # CMR hands back the Hyrax URL; the plain file lives on the data host.
        name = u.rsplit("/", 1)[-1].split("%3A")[-1]
        direct = (f"https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/"
                  f"{short_name(product)}.{CMR_VERSION}/{day.year}/{day:%j}/{name}")
        r = sess.get(direct, timeout=300)
        if r.status_code != 200:
            raise RuntimeError(f"{day}: HTTP {r.status_code} for {direct[:90]}")
        with nc4.Dataset("g.nc4", mode="r", memory=r.content) as ds:
            g = ds.groups["Grid"] if "Grid" in ds.groups else ds
            # Native layout is (time, lon, lat); the archive is (time, lat, lon).
            a = np.asarray(g.variables[VAR][0, i0:i1 + 1, j0:j1 + 1]).T
            if lat is None:
                lat = np.asarray(g.variables["lat"][j0:j1 + 1], dtype="float64")
                lon = np.asarray(g.variables["lon"][i0:i1 + 1], dtype="float64")
        frames.append(a.astype("float32"))

    arr = np.stack(frames)
    arr[arr < -100] = np.nan
    times = [dt.datetime.combine(day, dt.time()) + dt.timedelta(minutes=30 * k)
             for k in range(STEPS_PER_DAY)]
    return xr.DataArray(arr, dims=("time", "lat", "lon"),
                        coords={"time": np.array(times, dtype="datetime64[ns]"),
                                "lat": lat, "lon": lon},
                        name=VAR, attrs={"units": UNITS, "source": "GES DISC HTTPS"})


FETCH = {"opendap": fetch_opendap, "global": fetch_global}


def verify(day: dt.date, product: str, route: str) -> int:
    """Re-fetch a day already held and compare cell by cell.

    Comparing domain totals is not enough. Earlier in this project a decode bug
    produced a cube whose total looked right while half its frames were
    duplicates, and only a per-cell comparison caught it.
    """
    from sources import LocalSource
    idx = LocalSource(product=product).index()
    if day not in idx:
        print(f"{day} is not in the local archive; pick a day that is")
        return 2
    print(f"re-fetching {day} via {route} and comparing to the archive copy")
    fresh = FETCH[route](day, product)
    with xr.open_dataset(idx[day]) as a:
        va, vb = a[VAR].values, fresh.values
        print(f"  archive {va.shape}   fresh {vb.shape}")
        if va.shape != vb.shape:
            print("  SHAPE MISMATCH"); return 1
        dlat = float(np.abs(a.lat.values - fresh.lat.values).max())
        dlon = float(np.abs(a.lon.values - fresh.lon.values).max())
        d = np.abs(np.nan_to_num(va) - np.nan_to_num(vb))
        nbad = int((d > 1e-4).sum())
        print(f"  lat max diff {dlat:.2e}   lon max diff {dlon:.2e}")
        print(f"  value max diff {d.max():.6f}   cells differing >1e-4: "
              f"{nbad:,} of {d.size:,}")
        ok = d.max() < 1e-3 and dlat < 1e-5 and dlon < 1e-5
        print("  VERDICT:", "matches the archive, safe to repair with this route"
              if ok else "DIFFERS, do not use until resolved")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", default=None)
    ap.add_argument("--route", default="opendap", choices=sorted(FETCH))
    ap.add_argument("--out")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--bad-days", action="store_true",
                    help="repair the days validate.py flagged unreadable")
    ap.add_argument("--verify", metavar="YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    product = (a.product or PRODUCT).lower()

    if a.verify:
        sys.exit(verify(dt.datetime.strptime(a.verify, "%Y-%m-%d").date(),
                        product, a.route))

    days: list[dt.date] = []
    if a.bad_days:
        from validate import known_bad
        days += sorted(known_bad(product))
    if a.start and a.end:
        s = dt.datetime.strptime(a.start, "%Y-%m-%d").date()
        e = dt.datetime.strptime(a.end, "%Y-%m-%d").date()
        days += [s + dt.timedelta(days=i) for i in range((e - s).days + 1)]
    days = sorted(set(days))
    if not days:
        ap.error("nothing to do: pass --bad-days and/or --start/--end")
    if not a.out:
        ap.error("--out is required; stage into a directory the archive move "
                 "cannot overwrite, then copy the files in")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    print(f"product : {short_name(product)}.{CMR_VERSION}")
    print(f"route   : {a.route}")
    print(f"bbox    : N {NORTH} S {SOUTH} W {WEST} E {EAST}  -> {AOI_SHAPE}")
    print(f"days    : {len(days)}  ({days[0]} .. {days[-1]})")
    print(f"out     : {out}\n")
    if a.dry_run:
        for d in days:
            print("  ", d, filename(d, product))
        return

    ok = skip = fail = 0
    failures = []
    for i, d in enumerate(days, 1):
        target = out / filename(d, product)
        good, _ = validate(target)
        if good:
            skip += 1
            print(f"[{i}/{len(days)}] {d}  already valid, skipped", flush=True)
            continue
        t = time.time()
        try:
            write_day(FETCH[a.route](d, product), target)
            good, why = validate(target)
        except Exception as e:
            good, why = False, f"{type(e).__name__}: {str(e)[:70]}"
        if good:
            ok += 1
            print(f"[{i}/{len(days)}] {d}  OK  {target.stat().st_size:,} bytes  "
                  f"{time.time()-t:.0f}s", flush=True)
        else:
            fail += 1
            failures.append((d, why))
            if target.exists():
                target.rename(target.with_name(target.name + f".bad"))
            print(f"[{i}/{len(days)}] {d}  FAILED  {why}", flush=True)

    print(f"\ndownloaded {ok}, already valid {skip}, failed {fail}")
    for d, why in failures:
        print(f"  {d}  {why}")


if __name__ == "__main__":
    main()
