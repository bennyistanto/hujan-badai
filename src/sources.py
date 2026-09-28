"""Pluggable IMERG data sources.

The project does not depend on any one place the data lives. Every source
populates the same canonical on-disk layout:

    data/cache/imerg_v07/{YYYY}/{YYYYMMDD}.nc
        precipitation(time: 48, lat: 182, lon: 472)  float32, mm/hr

so a day fetched from NASA and a day copied from a local archive are
byte-comparable and interchangeable downstream.

Sources
-------
opendap : NASA GES DISC, the authoritative V07 product. Server-side subsetting
          over DAP4. Needs a free Earthdata Login in ~/.netrc. This is the
          default, so the notebook runs for anyone with an account.
local   : a pre-downloaded daily archive. The only viable source for multi-year
          runs (see the timing note below).
gee     : Google Earth Engine, V07, current to within about a day.

Why not Microsoft Planetary Computer
------------------------------------
Checked on 2026-09-26 and rejected on three counts, all verified:
  1. It serves IMERG **V06** ("Now in the latest Version 06 release", collection
     description), whose variable is `precipitationCal`, not V07's `precipitation`.
  2. Its temporal extent ends **2021-05-31**.
  3. Its Zarr chunks are [12 time, 3600 lon, 1800 lat], i.e. globally whole in
     space, so extracting Indonesia means pulling entire global slabs.
See docs/findings.md, Run 3.

Timing, measured
----------------
One constrained OPeNDAP timestep over the AOI: 0.346 MB in 5.1 s, versus 25.9 MB
in 25.1 s for the full global granule. Subsetting saves 75x bytes.
At 5.1 s per timestep a single day is 48 requests, and the full 2001-2025 archive
would be about 620 hours served serially. Hence: online for the notebook and for
MVP windows, local archive for the climatology. The cache makes the first choice
cheap on rerun.
"""
from __future__ import annotations

import datetime as dt
import netrc
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import netCDF4 as nc4
import numpy as np
import requests
import xarray as xr

from config import (AOI, AOI_SHAPE, CACHE, CMR_SHORT_NAMES, CMR_VERSION, FILL_BELOW,
                    GRID_DEG, PRODUCT, STEPS_PER_DAY, UNITS, VAR, local_archive)

# Global IMERG grid, centre registered.
GLOBAL_LAT = -89.95 + GRID_DEG * np.arange(1800)
GLOBAL_LON = -179.95 + GRID_DEG * np.arange(3600)

HDF5_MAGIC = bytes([0x89]) + b"HDF" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"
EDL_HOST = "urs.earthdata.nasa.gov"


def aoi_indices(aoi: dict = AOI) -> tuple[int, int, int, int]:
    """Index window on the global grid. Verified to reproduce the 182 x 472 local
    grid exactly, with residuals at float32 precision (docs/findings.md Run 3)."""
    j = np.where((GLOBAL_LAT > aoi["lat_min"]) & (GLOBAL_LAT < aoi["lat_max"]))[0]
    i = np.where((GLOBAL_LON > aoi["lon_min"]) & (GLOBAL_LON < aoi["lon_max"]))[0]
    return int(j[0]), int(j[-1]), int(i[0]), int(i[-1])


def cache_path(day: dt.date, product: str = None) -> Path:
    """Cache is keyed by run. A late day and a final day are different data
    and must never share a filename."""
    return CACHE / (product or PRODUCT) / f"{day:%Y}" / f"{day:%Y%m%d}.nc"


# --------------------------------------------------------------------------
# Source implementations
# --------------------------------------------------------------------------
class Source:
    name = "base"

    def fetch_day(self, day: dt.date) -> xr.DataArray:
        raise NotImplementedError


class LocalSource(Source):
    """Read a pre-downloaded daily archive. Fast, and the only option at
    climatology scale."""

    name = "local"
    _DATE_RE = re.compile(r"_(\d{8})_\d{7}_halfhourly\.nc4$")

    def __init__(self, archive: Path | None = None, glob: str | None = None,
                 product: str | None = None):
        self.product = (product or PRODUCT).lower()
        d, g = local_archive(self.product)
        self.archive = Path(archive) if archive else d
        self._glob = glob or g
        self._index: dict[dt.date, Path] | None = None

    def index(self) -> dict[dt.date, Path]:
        if self._index is None:
            out = {}
            for p in self.archive.glob(self._glob):
                m = self._DATE_RE.search(p.name)
                if m:
                    out[dt.datetime.strptime(m.group(1), "%Y%m%d").date()] = p
            self._index = dict(sorted(out.items()))
        return self._index

    def fetch_day(self, day: dt.date) -> xr.DataArray:
        idx = self.index()
        if day not in idx:
            raise FileNotFoundError(
                f"{day} not in the {self.product} archive at {self.archive} "
                f"(covers {min(idx)} .. {max(idx)})" if idx else
                f"{day}: no files matched {self._glob} in {self.archive}")
        return xr.open_dataset(idx[day])[VAR].load()


class OPeNDAPSource(Source):
    """NASA GES DISC over DAP4, with server-side spatial subsetting.

    Granule URLs are discovered through CMR rather than constructed, because the
    V07 filename carries a sub-version letter (V07A / V07B) that changes across
    the record. Constructing them would silently break on some years.
    """

    name = "opendap"

    def __init__(self, workers: int = 8, aoi: dict = AOI, product: str = None):
        self.workers = workers
        self.aoi = aoi
        self.product = (product or PRODUCT).lower()
        if self.product not in CMR_SHORT_NAMES:
            raise ValueError(f"unknown product {self.product!r}, "
                             f"expected one of {list(CMR_SHORT_NAMES)}")
        self.short_name = CMR_SHORT_NAMES[self.product]
        self.j0, self.j1, self.i0, self.i1 = aoi_indices(aoi)
        self._session: requests.Session | None = None

    def session(self) -> requests.Session:
        if self._session is None:
            try:
                user, _, pw = netrc.netrc().authenticators(EDL_HOST)
            except (FileNotFoundError, TypeError) as e:
                raise RuntimeError(
                    f"No Earthdata Login found for {EDL_HOST} in ~/.netrc. "
                    "Register free at https://urs.earthdata.nasa.gov and add:\n"
                    f"  machine {EDL_HOST} login <user> password <pass>"
                ) from e
            s = requests.Session()
            s.auth = (user, pw)
            self._session = s
        return self._session

    def granule_urls(self, day: dt.date) -> list[str]:
        """OPeNDAP URLs for one day's 48 granules, in time order.

        CMR search is public and returns 401 if basic auth is attached, so this
        deliberately does not use the Earthdata-authenticated session. Auth is
        only needed for the data host.
        """
        r = requests.get(CMR_GRANULES, params={
            "short_name": self.short_name,
            "version": CMR_VERSION,
            "temporal": f"{day:%Y-%m-%d}T00:00:00Z,{day:%Y-%m-%d}T23:59:59Z",
            "page_size": 100,
            "sort_key": "start_date",
        }, timeout=60)
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        urls = []
        for e in entries:
            for link in e.get("links", []):
                h = link.get("href", "")
                if "opendap" in h and h.endswith(".HDF5"):
                    urls.append(h)
                    break
        if len(urls) != STEPS_PER_DAY:
            raise RuntimeError(
                f"{day}: CMR returned {len(entries)} granules, "
                f"{len(urls)} with OPeNDAP links, expected {STEPS_PER_DAY}"
            )
        return urls

    def _fetch_nc(self, url: str, ce: str) -> dict[str, np.ndarray]:
        """Ask the server for a netCDF4 response and read it from memory.

        Deliberately NOT hand-decoding the raw DAP4 binary. An earlier version did,
        guessing the payload offset and validating with np.isfinite. That check is
        useless here because the -9999.9 fill value is finite, so a wrong offset
        silently returned plausible garbage: 48 timesteps decoded to only 2 distinct
        fields. Letting netCDF4 parse a real file removes the whole class of bug.
        """
        full = url + ".dap.nc4?dap4.ce=" + requests.utils.quote(ce, safe="")
        body = None
        last = "unknown"
        for attempt in range(1, 4):
            try:
                r = self.session().get(full, timeout=180)
            except requests.RequestException as e:
                last = f"{type(e).__name__}"
                time.sleep(2 * attempt)
                continue
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:120]}"
                time.sleep(2 * attempt)
                continue
            # A 200 can still carry an HTML error page or a truncated body, which
            # netCDF4 reports only as "Unknown file format". Check the HDF5 magic
            # before trusting it, and retry rather than failing the whole day.
            if not r.content.startswith(HDF5_MAGIC):
                last = f"not HDF5, {len(r.content)} bytes, starts {r.content[:16]!r}"
                time.sleep(2 * attempt)
                continue
            body = r.content
            break
        if body is None:
            raise RuntimeError(f"DAP4 failed after 3 attempts for {ce}: {last}")
        r = type("R", (), {"content": body})()
        out = {}
        # The dummy name must carry a .nc4 extension: netCDF4 infers the format from
        # it even for an in-memory read, and a bare name fails with
        # "NetCDF: Unknown file format".
        with nc4.Dataset("inmem.nc4", mode="r", memory=r.content) as ds:
            grp = ds.groups["Grid"] if "Grid" in ds.groups else ds
            for k, v in grp.variables.items():
                out[k] = np.asarray(v[:], dtype="float64")
        return out

    @staticmethod
    def _prefix(url: str) -> str:
        """Variable path prefix, which differs by OPeNDAP host.

        The Earthdata Cloud host (opendap.earthdata.nasa.gov, which is what CMR
        returns) preserves the HDF5 group structure, so variables live under
        /Grid/. The older GES DISC host (gpm1.gesdisc.eosdis.nasa.gov) flattens
        groups and exposes them at the root. Getting this wrong yields a DAP4
        400 "referenced a variable that was not found".
        """
        return "/Grid" if "opendap.earthdata.nasa.gov" in url else ""

    def fetch_day(self, day: dt.date) -> xr.DataArray:
        urls = self.granule_urls(day)
        ny, nx = self.j1 - self.j0 + 1, self.i1 - self.i0 + 1
        pre = self._prefix(urls[0])
        ce = (f"{pre}/{VAR}[0][{self.i0}:{self.i1}][{self.j0}:{self.j1}];"
              f"{pre}/lat[{self.j0}:{self.j1}];{pre}/lon[{self.i0}:{self.i1}]")

        def one(u):
            d = self._fetch_nc(u, ce)
            a = np.squeeze(d[VAR])
            if a.shape != (nx, ny):
                raise RuntimeError(f"expected {(nx, ny)} from server, got {a.shape}")
            # Server axis order is (time, lon, lat). Local files are (time, lat, lon).
            return a.T, d["lat"], d["lon"]

        with ThreadPoolExecutor(self.workers) as ex:
            results = list(ex.map(one, urls))

        frames = [r[0] for r in results]
        lat, lon = results[0][1], results[0][2]

        # The decode bug that motivated _fetch_nc produced duplicate frames, so
        # assert distinctness rather than trusting it silently.
        sums = np.array([np.nansum(np.where(f > FILL_BELOW, f, 0.0)) for f in frames])
        if np.unique(np.round(sums, 3)).size < STEPS_PER_DAY * 0.5:
            raise RuntimeError(
                f"{day}: only {np.unique(np.round(sums,3)).size} distinct frames of "
                f"{STEPS_PER_DAY}; the fetch is returning duplicates")

        times = [dt.datetime.combine(day, dt.time()) + dt.timedelta(minutes=30 * k)
                 for k in range(STEPS_PER_DAY)]

        arr = np.stack(frames).astype("float32")
        arr[arr < FILL_BELOW] = np.nan
        return xr.DataArray(
            arr, dims=("time", "lat", "lon"),
            coords={"time": np.array(times, dtype="datetime64[ns]"),
                    "lat": lat.astype("float64"), "lon": lon.astype("float64")},
            name=VAR, attrs={"units": UNITS, "source": "GES DISC OPeNDAP",
                             "product": f"{self.short_name}.{CMR_VERSION}",
                             "imerg_run": self.product},
        )


class GEESource(Source):
    """Google Earth Engine, asset NASA/GPM_L3/IMERG_V07.

    Verified 2026-09-26: band `precipitation`, 30-minute cadence, temporal extent
    1998-01-01 to 2026-09-25, so it is the only checked source that is current.

    Caveat that decides where this is useful: GEE is built for server-side
    reduction, not for handing back raw cubes. The segmentation in this project
    needs the whole 3D field client-side, so GEE acts purely as a download
    mechanism, which is not its strength. Use it for quick looks and for recent
    dates the Final product has not reached yet. `xee` is not installed; without
    it this path goes through ee.data.computePixels and is slower than OPeNDAP.
    """

    name = "gee"
    ASSET = "NASA/GPM_L3/IMERG_V07"

    def __init__(self, aoi: dict = AOI, product: str | None = None):
        self.aoi = aoi
        self.product = (product or PRODUCT).lower()

    def fetch_day(self, day: dt.date) -> xr.DataArray:
        raise NotImplementedError(
            "GEE path not implemented yet. It needs a confirmed ee project id "
            "(ee.Initialize(project=...)). Credentials were found at "
            "~/.config/earthengine/credentials but the project is unknown. "
            "Use SOURCE=opendap or SOURCE=local until that is supplied."
        )


def get_source(name: str | None = None, **kw) -> Source:
    from config import SOURCE
    name = (name or SOURCE).lower()
    try:
        return {"local": LocalSource, "opendap": OPeNDAPSource, "gee": GEESource}[name](**kw)
    except KeyError:
        raise ValueError(f"unknown source {name!r}, expected local/opendap/gee")
