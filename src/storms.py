"""Storm attributes from a labelled cube.

Produces one row per storm with the nine requested attributes plus provenance and
truncation flags.

Definitions, decided 2026-09-27
-------------------------------
max_intensity_mm_hr
    Peak single voxel inside the object. Not an area mean.
start_lat / start_lon
    Volume-weighted centroid of the object's FIRST timestep. Not the location of
    first threshold exceedance.
end_lat / end_lon
    Volume-weighted centroid of the LAST timestep, by symmetry.

Weighting
---------
"Weighted" means weighted by rain volume, depth times cell area, not by intensity
alone. Over this AOI cell area varies only about 2% so the two nearly agree, but
volume is the physically meaningful weight for where the water actually fell.

Truncation
----------
A storm touching the spatial edge of the AOI, or the first or last timestep of the
processing window, has censored duration and volume. Those rows are flagged, never
silently dropped. Any duration or volume distribution that ignores the flags is
biased low.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from config import DT_HOURS
from imerg_io import cell_area_m2


def storm_table(R: np.ndarray, labels: np.ndarray, time, lat, lon,
                params: dict | None = None) -> pd.DataFrame:
    """One row per storm.

    Parameters
    ----------
    R
        Intensity cube, mm/hr, shape (nt, ny, nx). NaN treated as zero.
    labels
        int array, same shape, 0 for background.
    time, lat, lon
        Coordinate vectors. `lat` must be ascending.
    params
        Recorded verbatim into every row, so a catalogue always carries the
        settings that produced it.
    """
    R = np.nan_to_num(np.asarray(R, dtype=np.float64), nan=0.0)
    labels = np.asarray(labels)
    nt, ny, nx = R.shape
    nlab = int(labels.max())
    if nlab == 0:
        return pd.DataFrame()

    time = pd.to_datetime(np.asarray(time))
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)

    # Volume per voxel in km3. R is mm/hr, so depth over one step is R * DT_HOURS mm.
    area_m2 = cell_area_m2(lat)[None, :, None]
    vol = R * DT_HOURS / 1000.0 * area_m2 / 1e9          # mm/hr -> m -> m3 -> km3

    flat = labels.ravel()
    v = vol.ravel()
    r = R.ravel()
    nb = nlab + 1

    # Per-voxel coordinate broadcasts, flattened once and reused.
    ti = np.repeat(np.arange(nt), ny * nx)
    yi = np.tile(np.repeat(np.arange(ny), nx), nt)
    xi = np.tile(np.arange(nx), nt * ny)

    n_vox = np.bincount(flat, minlength=nb)
    sum_v = np.bincount(flat, weights=v, minlength=nb)
    max_r = np.zeros(nb)
    np.maximum.at(max_r, flat, r)

    # Volume-weighted centroid. Guard against a zero-volume object, which can occur
    # if every voxel in it happens to be exactly zero.
    w = np.where(sum_v > 0, sum_v, 1.0)
    cen_t = np.bincount(flat, weights=v * ti, minlength=nb) / w
    cen_y = np.bincount(flat, weights=v * yi, minlength=nb) / w
    cen_x = np.bincount(flat, weights=v * xi, minlength=nb) / w

    # Unweighted geometric centroid of the voxel set.
    nvx = np.where(n_vox > 0, n_vox, 1)
    geo_t = np.bincount(flat, weights=ti.astype(float), minlength=nb) / nvx
    geo_y = np.bincount(flat, weights=yi.astype(float), minlength=nb) / nvx
    geo_x = np.bincount(flat, weights=xi.astype(float), minlength=nb) / nvx

    t_min = _group_extreme(flat, ti, nb, np.minimum, nt)
    t_max = _group_extreme(flat, ti, nb, np.maximum, -1)
    y_min = _group_extreme(flat, yi, nb, np.minimum, ny)
    y_max = _group_extreme(flat, yi, nb, np.maximum, -1)
    x_min = _group_extreme(flat, xi, nb, np.minimum, nx)
    x_max = _group_extreme(flat, xi, nb, np.maximum, -1)

    # Max footprint: largest single-timestep area, in km2.
    area_km2_row = cell_area_m2(lat) / 1e6
    key = flat.astype(np.int64) * nt + ti
    a_per_vox = np.tile(np.repeat(area_km2_row, nx), nt)
    step_area = np.bincount(key, weights=a_per_vox, minlength=nb * nt)
    max_area = step_area.reshape(nb, nt).max(axis=1)

    tracks = _tracklines(flat, ti, yi, xi, v, nb, nt, lat, lon)

    rows = []
    for lb in range(1, nb):
        if n_vox[lb] == 0:
            continue
        tr = tracks[lb]
        n_steps = t_max[lb] - t_min[lb] + 1
        rows.append({
            "storm_id": lb,
            "start_time": time[t_min[lb]],
            "end_time": time[t_max[lb]],
            "duration_h": n_steps * DT_HOURS,
            "n_timesteps": int(n_steps),
            "total_volume_km3": sum_v[lb],
            "max_intensity_mm_hr": max_r[lb],          # peak voxel, as decided
            "max_area_km2": max_area[lb],
            "n_voxels": int(n_vox[lb]),
            "centroid_lat": np.interp(geo_y[lb], np.arange(ny), lat),
            "centroid_lon": np.interp(geo_x[lb], np.arange(nx), lon),
            "centroid_time": _interp_time(time, geo_t[lb]),
            "wcentroid_lat": np.interp(cen_y[lb], np.arange(ny), lat),
            "wcentroid_lon": np.interp(cen_x[lb], np.arange(nx), lon),
            "wcentroid_time": _interp_time(time, cen_t[lb]),
            "start_lat": tr[0][1], "start_lon": tr[0][2],   # first-step centroid
            "end_lat": tr[-1][1], "end_lon": tr[-1][2],
            "bbox_lat_min": lat[y_min[lb]], "bbox_lat_max": lat[y_max[lb]],
            "bbox_lon_min": lon[x_min[lb]], "bbox_lon_max": lon[x_max[lb]],
            "truncated_time": bool(t_min[lb] == 0 or t_max[lb] == nt - 1),
            "truncated_space": bool(y_min[lb] == 0 or y_max[lb] == ny - 1
                                    or x_min[lb] == 0 or x_max[lb] == nx - 1),
            "track": tr,
        })

    df = pd.DataFrame(rows)
    if params:
        for k, val in params.items():
            df[f"param_{k}"] = val
    return df


def _group_extreme(flat, vals, nb, op, init):
    out = np.full(nb, init, dtype=np.int64)
    op.at(out, flat, vals)
    return out


def _interp_time(time, fidx: float):
    n = len(time)
    i = int(np.clip(np.floor(fidx), 0, n - 2)) if n > 1 else 0
    frac = float(np.clip(fidx - i, 0.0, 1.0)) if n > 1 else 0.0
    return time[i] + (time[i + 1] - time[i]) * frac if n > 1 else time[0]


def _tracklines(flat, ti, yi, xi, v, nb, nt, lat, lon):
    """Volume-weighted centroid per (storm, timestep).

    This is the trackline, and start/end location come from its first and last
    vertex. Built with bincount on a combined (label, time) key so it stays fast
    on a month-sized cube.
    """
    key = flat.astype(np.int64) * nt + ti
    size = nb * nt
    wsum = np.bincount(key, weights=v, minlength=size)
    ysum = np.bincount(key, weights=v * yi, minlength=size)
    xsum = np.bincount(key, weights=v * xi, minlength=size)
    cnt = np.bincount(key, minlength=size)

    wsum, ysum, xsum, cnt = (a.reshape(nb, nt) for a in (wsum, ysum, xsum, cnt))
    # Fall back to the unweighted mean where a timestep's volume is exactly zero.
    ycnt = np.bincount(key, weights=yi.astype(float), minlength=size).reshape(nb, nt)
    xcnt = np.bincount(key, weights=xi.astype(float), minlength=size).reshape(nb, nt)

    ny, nx = len(lat), len(lon)
    out = {}
    for lb in range(1, nb):
        steps = np.flatnonzero(cnt[lb] > 0)
        if steps.size == 0:
            out[lb] = [(0, float("nan"), float("nan"))]
            continue
        wv = wsum[lb, steps]
        good = wv > 0
        yy = np.where(good, ysum[lb, steps] / np.where(good, wv, 1),
                      ycnt[lb, steps] / cnt[lb, steps])
        xx = np.where(good, xsum[lb, steps] / np.where(good, wv, 1),
                      xcnt[lb, steps] / cnt[lb, steps])
        out[lb] = [(int(t), float(np.interp(y, np.arange(ny), lat)),
                    float(np.interp(x, np.arange(nx), lon)))
                   for t, y, x in zip(steps, yy, xx)]
    return out


def track_wkt(track) -> str:
    """Trackline as a WKT LINESTRING in lon lat order, for GIS handoff.

    A single-timestep storm has no line, so it comes back as a POINT.
    """
    pts = [f"{lo:.4f} {la:.4f}" for _, la, lo in track if np.isfinite(la)]
    if not pts:
        return "LINESTRING EMPTY"
    if len(pts) == 1:
        return f"POINT ({pts[0]})"
    return "LINESTRING (" + ", ".join(pts) + ")"
