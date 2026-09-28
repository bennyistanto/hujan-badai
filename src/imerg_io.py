"""Loading IMERG. One entry point, `load_range`, whatever the source.

Reads only the days asked for, caches each day to the canonical layout, and
validates the result before handing it back. Downstream code never learns where
the data came from.

    from imerg_io import load_range
    da = load_range("2020-01-01", "2020-01-05")            # config.SOURCE
    da = load_range("2020-01-01", "2020-01-05", source="local")
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import xarray as xr

from config import (AOI_SHAPE, CACHE, DT_HOURS, EARTH_R_M, GRID_DEG,
                    MAX_ONLINE_DAYS, PRODUCT, STEPS_PER_DAY, VAR)
from sources import Source, cache_path, get_source


def load_range(start, end, source: str | Source | None = None, *,
               product: str | None = None, use_cache: bool = True,
               write_cache: bool = True, progress: bool = True,
               allow_long: bool = False) -> xr.DataArray:
    """Load [start, end] inclusive as one (time, lat, lon) DataArray in mm/hr.

    Raises on a missing day rather than leaving a silent gap. A gap would read
    downstream as a storm ending and restarting, which is invisible in the output
    and wrong.
    """
    start, end = _as_date(start), _as_date(end)
    if end < start:
        raise ValueError(f"end {end} before start {start}")
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]

    product = product or PRODUCT
    _check_span(days, source, product, use_cache, allow_long)
    if isinstance(source, Source):
        src = source
    else:
        kw = {'product': product}
        src = get_source(source, **kw)
    frames = []
    for k, day in enumerate(days, 1):
        cp = cache_path(day, product)
        if use_cache and cp.exists():
            frames.append(xr.open_dataset(cp)[VAR].load())
            continue
        if progress:
            print(f"  [{k}/{len(days)}] fetching {day} via {src.name}", flush=True)
        da = src.fetch_day(day)
        _validate_day(da, day)
        if write_cache:
            _write_cache(da, cp)
        frames.append(da)

    # join="override" takes lat/lon from the first frame instead of unioning them.
    # The default outer join silently doubled the grid to (364, 944) at 75% NaN,
    # because daily files in the Final archive carry coordinate values that differ
    # in their last float bits. compat="override" skips the equality check that
    # would otherwise reject those same near-identical coords.
    out = xr.concat(frames, dim="time", join="override", compat="override",
                    coords="minimal").sortby("time")
    _validate_range(out, days)
    return out


def _check_span(days, source, product: str, use_cache: bool,
                allow_long: bool) -> None:
    """Guard the online path against an accidentally huge request.

    Cached days cost nothing, so only count the ones that would be fetched.
    """
    from config import SOURCE
    name = (source.name if isinstance(source, Source)
            else (source or SOURCE)).lower()
    if name != "opendap" or allow_long:
        return
    todo = [d for d in days
            if not (use_cache and cache_path(d, product).exists())]
    if len(todo) > MAX_ONLINE_DAYS:
        raise ValueError(
            f"{len(todo)} uncached days requested over OPeNDAP, above the "
            f"MAX_ONLINE_DAYS ceiling of {MAX_ONLINE_DAYS}. That is roughly "
            f"{len(todo)*48} granules and {len(todo)*16/60:.0f} min. Use "
            f"source='local' for long spans, or pass allow_long=True.")

def _validate_day(da: xr.DataArray, day: dt.date) -> None:
    if da.sizes.get("time") != STEPS_PER_DAY:
        raise ValueError(f"{day}: {da.sizes.get('time')} steps, expected {STEPS_PER_DAY}")
    got = (da.sizes["lat"], da.sizes["lon"])
    if got != AOI_SHAPE:
        raise ValueError(f"{day}: grid {got}, expected {AOI_SHAPE}")


def _validate_range(da: xr.DataArray, days: list[dt.date]) -> None:
    n = len(days) * STEPS_PER_DAY
    if da.sizes["time"] != n:
        raise ValueError(f"got {da.sizes['time']} steps, expected {n}")
    # Check the spatial shape AFTER concat, not only per day. An outer join on
    # near-identical float coords doubled the grid once and this check is what
    # would have caught it immediately.
    got = (da.sizes["lat"], da.sizes["lon"])
    if got != AOI_SHAPE:
        raise ValueError(f"grid {got} after concat, expected {AOI_SHAPE}; "
                         "coordinate values probably differ between daily files")
    nan = float(np.isnan(da.values).mean())
    if nan > 0.5:
        raise ValueError(f"{nan:.1%} NaN after concat, which indicates a bad join")
    t = da["time"].values
    d = np.unique(np.diff(t).astype("timedelta64[m]").astype(int))
    if d.size != 1 or d[0] != int(DT_HOURS * 60):
        raise ValueError(f"non-uniform time step, found {d.tolist()} minutes")
    if da["lat"].values[0] > da["lat"].values[-1]:
        raise ValueError("lat is descending; downstream code assumes ascending")


def _write_cache(da: xr.DataArray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.nc")
    da.to_dataset(name=VAR).to_netcdf(
        tmp, encoding={VAR: {"zlib": True, "complevel": 4, "dtype": "float32"}})
    tmp.replace(path)          # atomic, so an interrupted run leaves no half file


def cached_days(product: str | None = None) -> list[dt.date]:
    out = []
    root = CACHE / (product or PRODUCT)
    for p in sorted(root.rglob("*.nc")):
        try:
            out.append(dt.datetime.strptime(p.stem, "%Y%m%d").date())
        except ValueError:
            pass
    return out


def _as_date(x) -> dt.date:
    if isinstance(x, dt.datetime):
        return x.date()
    if isinstance(x, dt.date):
        return x
    return dt.datetime.strptime(str(x), "%Y-%m-%d").date()


def cell_area_m2(lat: np.ndarray, deg: float = GRID_DEG) -> np.ndarray:
    """Per-latitude cell area in m2, shape (nlat,).

    Lat/lon cells are not equal area. Over this AOI the span is only about 2%,
    but the volume calculation uses the real value rather than a scalar.
    """
    half = np.deg2rad(deg / 2.0)
    latr = np.deg2rad(np.asarray(lat, dtype=float))
    return (EARTH_R_M ** 2) * np.deg2rad(deg) * (np.sin(latr + half) - np.sin(latr - half))
