"""Single place for paths, grid facts, and data-source selection.

Nothing else in the project should hardcode a path or a source URL.

Environment
-----------
Use the `climate` conda env, not miniforge base:
    C:\\Users\\benny\\miniforge3\\envs\\climate\\python.exe
Its Library\\bin must be on PATH or extension modules fail to load with exit 127.
See `run.ps1` in the repo root, which sets this up.
"""
from pathlib import Path
import os

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
CACHE = DATA / "cache" / "imerg_v07"     # canonical on-disk layout, see sources.py
DATA_INTERIM = DATA / "interim"
DATA_PROCESSED = DATA / "processed"
TEMP = REPO / "temp"

# --- Data source -----------------------------------------------------------
# "opendap" : NASA GES DISC, authoritative V07, needs an Earthdata login in ~/.netrc.
#             Server-side subsetting. The default, so the notebook is portable.
# "local"   : a pre-downloaded daily archive. Fast. Required for multi-year runs.
# "gee"     : Google Earth Engine, V07, current to within a day. Needs `ee` auth.
SOURCE = os.environ.get("HUJAN_SOURCE", "opendap")

# Pre-downloaded archives, one per IMERG run. Only used when SOURCE == "local".
# Both verified 2026-09-26 against their own FileHeader; see docs/findings.md.
# Each is (directory, filename glob).
_DL = Path(r"I:\My Drive\hybrid-bias-correction\data\downloads")

# Candidate directories per run, tried in order; the first that exists and holds
# files wins. The Final archive is being moved from Google Drive (I:) to local
# disk (G:), so both are listed and the code follows whichever is live. Local disk
# reads roughly 4x faster than Google Drive File Stream on a cold file, which
# matters a great deal for the multi-hour climatology job.
LOCAL_ARCHIVE_CANDIDATES = {
    "final": [Path(r"G:\temp\imerg\GPM_3IMERGHH_07_subset_halfhourly"),
              _DL / "GPM_3IMERGHH_07_subset_halfhourly"],
    "late":  [Path(r"G:\temp\imerg\GPM_3IMERGHHL_07_subset_halfhourly"),
              _DL / "GPM_3IMERGHHL_07_subset_halfhourly",
              Path(r"F:\temp\imerg\GPM_3IMERGHHL_07_subset_halfhourly")],
}
LOCAL_GLOBS = {
    "final": "GPM_3IMERGHH_07_subset_*_halfhourly.nc4",
    "late":  "GPM_3IMERGHHL_07_subset_*_halfhourly.nc4",
}
# Note: sibling `*_extract_halfhourly` folders hold files named
# `idn_cli_imerg_hh_rate_YYYYMMDD.nc4` from another pipeline. xarray's installed
# backends cannot open them. Use the `_subset_` folders.
#
# The AOI deliberately includes ocean. Most storms here form over water, so the sea
# is signal, not padding. Do not mask it. A land/sea flag on each storm is for
# interpretation only, never for filtering.
# HUJAN_IMERG_DIR overrides the directory for the selected run.
_override = os.environ.get("HUJAN_IMERG_DIR")

# --- Product facts ---------------------------------------------------------
# Verified against the archive and against the GES DISC DMR, see docs/findings.md.
VAR = "precipitation"          # V07 name. V06 called it `precipitationCal`.
UNITS = "mm/hr"                # an intensity, NOT a depth
DT_HOURS = 0.5                 # depth_mm = rate_mm_per_hr * DT_HOURS
STEPS_PER_DAY = 48
FILL_BELOW = -100.0            # CodeMissingValue is -9999.9

# --- Which IMERG run ------------------------------------------------------
# The three runs are different products, not different formats:
#   final : gauge calibrated against GPCC, about 3.5 month latency. For climatology.
#   late  : no gauge calibration, about 14 h latency. For NRT prototyping.
#   early : no gauge calibration, about 4 h latency. For real time.
# Verified 2026-09-26: the local archive at LOCAL_ARCHIVE is **late**, despite the
# folder being described as Final. Its FileHeader says DOIshortName=3IMERGHH_LATE,
# DOI 10.5067/GPM/IMERG/3B-HH-L/07. The `L` in GPM_3IMERGHHL is the run.
# Measured difference between late and final for 2020-01-01 over the AOI: 8.4% in
# total volume, with 51% of cells differing by more than 1e-4 mm/hr.
PRODUCT = os.environ.get("HUJAN_PRODUCT", "final")
CMR_SHORT_NAMES = {
    "final": "GPM_3IMERGHH",
    "late": "GPM_3IMERGHHL",
    "early": "GPM_3IMERGHHE",
}
CMR_SHORT_NAME = CMR_SHORT_NAMES[PRODUCT]
CMR_VERSION = "07"


def local_archive(product: str | None = None) -> tuple[Path, str]:
    """Directory and filename glob of the local archive for one run.

    Picks the candidate holding the most files, so a half-finished move between
    drives resolves to whichever copy is currently more complete rather than to a
    directory that merely exists.
    """
    product = (product or PRODUCT).lower()
    if product not in LOCAL_ARCHIVE_CANDIDATES:
        raise ValueError(
            f"no local archive configured for run {product!r}; "
            f"have {sorted(LOCAL_ARCHIVE_CANDIDATES)}. Use SOURCE=opendap instead.")
    glob = LOCAL_GLOBS[product]
    if _override:
        return Path(_override), glob
    best, best_n = None, -1
    for cand in LOCAL_ARCHIVE_CANDIDATES[product]:
        try:
            n = sum(1 for _ in cand.glob(glob)) if cand.exists() else 0
        except OSError:
            n = 0
        if n > best_n:
            best, best_n = cand, n
    if best_n <= 0:
        raise FileNotFoundError(
            f"no {product} archive found. Looked in: "
            + ", ".join(str(c) for c in LOCAL_ARCHIVE_CANDIDATES[product])
            + ". Set HUJAN_IMERG_DIR, or use HUJAN_SOURCE=opendap.")
    return best, glob

# --- Notebook workflow -----------------------------------------------------
# The notebook pattern is: user picks a date or a range, the script gathers only
# that period. One month is the practical ceiling for the online path:
#   1 day    = 48 granules, about 16 s over OPeNDAP with 8 workers, 3.9 MB
#   31 days  = 1,488 granules, about 8 min, 121 MB, a 495 MB float32 cube
# Beyond that, use SOURCE=local. Pass allow_long=True to override deliberately.
MAX_ONLINE_DAYS = 31

# --- Storm attribute definitions (decided 2026-09-27) ----------------------
# max_intensity : peak single voxel in the object, not an area mean.
# start/end location : volume-weighted centroid of the object's first/last
#                      timestep, not the location of first threshold exceedance.
# 'Weighted' always means weighted by rain volume (depth x cell area), never by
# intensity alone or by the binary mask.

# --- Grid ------------------------------------------------------------------
GRID_DEG = 0.1
EARTH_R_M = 6_371_008.8        # IUGG mean radius

# Indonesia AOI. These bounds reproduce the 182 x 472 grid of the local archive
# exactly; see sources.py::aoi_indices for the index derivation.
AOI = dict(lat_min=-11.6, lat_max=6.6, lon_min=94.4, lon_max=141.6)
AOI_SHAPE = (182, 472)         # (nlat, nlon), asserted on load
