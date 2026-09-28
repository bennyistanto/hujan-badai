# hujan-badai

Spatiotemporal storm detection and tracking over Indonesia from GPM IMERG half-hourly
precipitation.

Starting point is ST-CORA (Laverde-Barajas et al. 2019, 2020). Measured on this domain,
the published method's connected-component labelling percolates: at its own 1 mm/h
threshold a single object holds 90.1% of all wet voxels and spans the full domain and
window. The work here replaces that step with a partition-based segmentation that cannot
percolate. See `docs/plan.md` for the design and `docs/findings.md` for the evidence.

## Running

Use the `climate` conda env through the wrapper, which puts its `Library\bin` on PATH:

```powershell
.\run.ps1 src\probe.py --start 2020-01-01 --end 2020-01-05 --subregions
```

## Data

No local files required. `src/sources.py` fetches from NASA GES DISC over OPeNDAP with
server-side subsetting, and caches days locally. You need a free
[Earthdata Login](https://urs.earthdata.nasa.gov) in `~/.netrc`:

```
machine urs.earthdata.nasa.gov login <user> password <pass>
```

Sources are selected by `HUJAN_SOURCE` (`opendap`, `local`, `gee`) and the IMERG run by
`HUJAN_PRODUCT` (`final`, `late`, `early`). Final is the default. The three runs are
different products, not different packagings: Late reads about 9% higher in total
volume than Final over the same window, because Late is not gauge calibrated. Online is right for the notebook and for
windows of days to weeks. A multi-year climatology needs a local archive: one timestep
is about 4 s over OPeNDAP, so the full 2001-2025 record would be roughly 620 hours.

The notebook takes a date or a range and fetches only that period. One month is the
online ceiling (`MAX_ONLINE_DAYS`, about 8 min and 121 MB); beyond that use
`HUJAN_SOURCE=local`.

AWS S3 was evaluated and not adopted: the GES DISC bucket has no server-side
subsetting and IMERG's HDF5 chunks span all latitudes, so even an ideal byte-range
read moves about 19x more data than an OPeNDAP subset. It would win only if the
processing ran inside us-west-2.

## Status

Scaffolding, data access and diagnostics are done and tested. Segmentation is designed
but not yet implemented. See `HANDOFF.md`.

## Scope

This produces a storm catalogue. It does not claim accuracy: there is no independent
gauge or radar validation data for Indonesia in this project, and the 2020 ST-CORA paper
reports the same gap for its own study area.
