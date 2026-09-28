"""Land, coastline and province rasters on the analysis grid.

Natural Earth is used rather than the project's geoBoundaries copy, for two reasons:
it is **global**, so nothing here needs rewriting if the AOI is extended beyond
Indonesia; and its physical land polygons are built for coastlines, where the
geoBoundaries file is an administrative product that happens to have a coastal edge.

Rasterising once and looking up by grid cell replaces point-in-polygon over 12.5M
storms, which would be far too slow, and gives the same answer at this resolution.

Data is whatever cartopy has cached under `cartopy.config["data_dir"]`; it downloads
on first use. Resolution 10m is the finest Natural Earth offers and is a good match
for a 0.1 degree grid (about 11 km, against 10m-scale mapping at roughly 1:10 million).
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AOI, GRID_DEG  # noqa: E402

RESOLUTION = "10m"


def grid_axes(deg: float = GRID_DEG) -> tuple[np.ndarray, np.ndarray]:
    """Cell-centre latitudes (ascending) and longitudes for the AOI."""
    lat = np.arange(AOI["lat_min"] + deg / 2, AOI["lat_max"], deg)
    lon = np.arange(AOI["lon_min"] + deg / 2, AOI["lon_max"], deg)
    return lat, lon


def _rasterise(shapes, deg: float, dtype="uint8", fill=0):
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    lat, lon = grid_axes(deg)
    tr = from_origin(lon[0] - deg / 2, lat[-1] + deg / 2, deg, deg)
    arr = rasterize(shapes, out_shape=(len(lat), len(lon)), transform=tr,
                    fill=fill, dtype=dtype)
    return arr[::-1], lat, lon        # flip: row 0 becomes the south edge


@functools.lru_cache(maxsize=4)
def land_mask(deg: float = GRID_DEG, resolution: str = RESOLUTION):
    """Boolean land raster from Natural Earth physical land polygons."""
    from cartopy.io import shapereader
    p = shapereader.natural_earth(resolution=resolution, category="physical",
                                  name="land")
    geoms = list(shapereader.Reader(p).geometries())
    arr, lat, lon = _rasterise(((g, 1) for g in geoms), deg)
    return arr == 1, lat, lon


@functools.lru_cache(maxsize=4)
def province_grid(deg: float = GRID_DEG, resolution: str = RESOLUTION,
                  country: str = "Indonesia"):
    """Province id raster plus the id -> name mapping.

    0 means "no province", which over this AOI means sea or another country.
    """
    from cartopy.io import shapereader
    p = shapereader.natural_earth(resolution=resolution, category="cultural",
                                  name="admin_1_states_provinces")
    recs = [r for r in shapereader.Reader(p).records()
            if r.attributes.get("admin") == country]
    names = [r.attributes.get("name") or r.attributes.get("name_en") or "?"
             for r in recs]
    shapes = ((r.geometry, i + 1) for i, r in enumerate(recs))
    arr, lat, lon = _rasterise(shapes, deg, dtype="int32")
    return arr, {i + 1: n for i, n in enumerate(names)}, lat, lon


def lookup(lat_vals, lon_vals, arr, mlat, mlon, deg: float = GRID_DEG):
    """Sample a raster at storm positions, clamped to the grid."""
    iy = np.clip(((np.asarray(lat_vals) - mlat[0]) / deg).round().astype(int),
                 0, arr.shape[0] - 1)
    ix = np.clip(((np.asarray(lon_vals) - mlon[0]) / deg).round().astype(int),
                 0, arr.shape[1] - 1)
    return arr[iy, ix]


def coast_distance_km(deg: float = GRID_DEG, resolution: str = RESOLUTION):
    """Distance from each cell to the nearest land cell, in km.

    Signed is not attempted: this is distance to land, zero on land itself. Useful
    for asking how far offshore a storm formed.
    """
    from scipy import ndimage as ndi
    land, lat, lon = land_mask(deg, resolution)
    # Cell size in km varies with latitude; use the AOI mean, which over this
    # domain varies by about 2% and is well inside the grid resolution anyway.
    km_per_cell = deg * 111.32
    d = ndi.distance_transform_edt(~land) * km_per_cell
    return d, lat, lon
