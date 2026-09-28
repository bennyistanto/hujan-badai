# Runbook

Every command assumes the repo root as the working directory.

`run.ps1` and `run.cmd` are convenience wrappers and are **gitignored**, because they
hardcode nothing but still describe one machine's layout. If you do not have them, every
command below works after `conda activate`: substitute `python` for `.\run.ps1`. Both
wrappers read `HUJAN_ENV` / `HUJAN_CONDA` if you want to point them elsewhere.

## 0. Environment

### From cmd.exe

Activate the env and call python directly. **No wrapper is needed.** Conda's
`activate.d` scripts set `GDAL_DATA` and `PROJ_DATA` and put the env's
`Library\bin` on PATH, which is everything `run.ps1` does by hand. Verified.

```bat
conda activate climate
cd /d C:\Users\benny\OneDrive\Documents\Github\hujan-badai
python src\build_year.py --year 1998 2025 --prominence 4
```

For the long job, log to a file:

```bat
python src\build_year.py --year 1998 2025 --prominence 4 > data\processed\climatology.log 2>&1
```

`run.cmd` exists if you would rather not activate first, but it must be written
`.\run.cmd`: this machine sets `NoDefaultCurrentDirectoryInExePath=1`, so cmd does
not search the current directory and a bare `run.cmd` gives "not recognized as an
internal or external command".

What actually fails is calling the env's interpreter by full path **without**
activating, e.g. `C:\Users\benny\miniforge3\envs\climate\python.exe script.py`.
Extension modules cannot find their DLLs and the process dies with exit 127 and no
traceback. That is the trap `run.ps1` was written to avoid, not activation itself.

### From PowerShell

Use `run.ps1`, which sets the same variables without activating.

```powershell
.\run.ps1 src\probe.py --start 2020-01-01 --end 2020-01-02
```

If PowerShell refuses with *"running scripts is disabled on this system"*: the file
carries an internet-zone mark because the repo lives in OneDrive. Clear it once:

```powershell
Unblock-File .\run.ps1
```

Or bypass per call: `pwsh -ExecutionPolicy Bypass -File .\run.ps1 <args>`.
PowerShell 7 (`pwsh`) works; Windows PowerShell 5.1 is the one that objects.

Data sources are picked by environment variable, and default to `opendap` / `final`:

```powershell
$env:HUJAN_SOURCE  = "local"     # local | opendap | gee
$env:HUJAN_PRODUCT = "final"     # final | late | early
```

Online access needs a free Earthdata Login in `~/.netrc`:

```
machine urs.earthdata.nasa.gov login <user> password <pass>
```

---

## 1. Check the archive before any long run

```powershell
.\run.ps1 src\validate.py --product final
.\run.ps1 src\validate.py --product final --deep        # slower, opens every file
```

Reads the first 8 bytes of every file and reports which are not NetCDF, plus any
calendar gaps. **File size is not a usable signal**: dry days legitimately compress
to a third of a wet day. Run this first, because `load_range` raises on an
unreadable day rather than leaving a silent gap, so one bad file aborts a job.

Note the archive lives on Google Drive (`I:`). Cold files are fetched on first read,
around 5 s/day; once warm it is far quicker. A first full pass is slow.

---

## 2. Diagnostics on a window

```powershell
.\run.ps1 src\probe.py --start 2020-12-01 --end 2020-12-05 --subregions --advection
.\run.ps1 src\probe.py --start 2020-12-01 --end 2020-12-05 --source opendap
```

| flag | meaning |
|---|---|
| `--thresholds 1 2 5` | intensity thresholds to test, mm/hr |
| `--subregions` | percolation against domain size |
| `--advection` | frame-to-frame displacement |
| `--source` | `local`, `opendap`, `gee` |

Watch the **`share`** column: the fraction of wet voxels in the single largest
object. Above about 0.20 the labelling has percolated and is not producing storms.

---

## 3. One catalogue

```powershell
.\run.ps1 src\catalogue.py --start 2019-12-30 --end 2020-01-02 `
    --source local --product final --method mergetree --prominence 4
```

| flag | default | meaning |
|---|---|---|
| `--method` | `mergetree` | `mergetree`, `watershed`, `ccl` |
| `--prominence` | `4.0` | **the scale parameter**, mm/hr |
| `--wet-threshold` | `1.0` | bounds the analysis, mm/hr |
| `--min-voxels` | `6` | size filter |
| `--allow-long` | off | override the 31-day online ceiling |

Writes `data/processed/storms_<product>_<start>_<end>.parquet` plus a
`.meta.json` of the parameters and the git revision.

**Quote the prominence with every number you take from a catalogue, and the method
too**: merge tree and watershed give qualitatively different populations, not just
different counts.

---

## 4. The climatology

Resumable: a year whose Parquet already exists is skipped, and months missing days
from the archive are skipped with a warning rather than aborting the year.

```powershell
# one year, about 16 min
.\run.ps1 src\build_year.py --year 2020 --prominence 4

# the full record, inclusive range, about 7.4 h. Safe to stop and restart.
.\run.ps1 src\build_year.py --year 1998 2025 --prominence 4

# redo a year
.\run.ps1 src\build_year.py --year 2020 --overwrite

# selected months only
.\run.ps1 src\build_year.py --year 2025 --months 1 2 3
```

Run it detached so a closed terminal does not kill it:

```powershell
Start-Process pwsh -ArgumentList '-File','.\run.ps1','src\build_year.py','--year','1998','2025' `
    -RedirectStandardOutput 'data\processed\climatology.log' -NoNewWindow
```

Writes one `catalogue_<product>_<year>_h<h>.parquet` per year, roughly 420k storms
and 35 MB each, so about 11.7M storms and 1-2 GB for the full record.

**Month boundaries are handled**, by `--overlap-days` (default 1): each month is
segmented on a window padded a day either side, and a storm is claimed by the month
containing its volume-weighted centroid time. This removes the time-truncation flag
entirely (0.94% to 0.00% on June 2020) at no runtime cost. It does **not** change the
duration distribution: max and p99 are identical either way, because storms spanning
a month boundary are not the long ones. Measured in `docs/findings.md` Finding 35.

Storms still carrying `truncated_time` are ones where padding was unavailable, at the
very start or end of the archive. Exclude them from any fitted distribution.

---

## 5. Parameter sensitivity

```powershell
.\run.ps1 src\sweep.py --months 2020-12 2020-08 --method mergetree
.\run.ps1 src\sweep.py --months 2020-12 2020-08 --h 1 2 3.2 4 4.8 8 --method watershed
```

Takes 6-15 min per month depending on method. Writes
`data/processed/sweep-prominence-<method>.csv`.

The default h grid includes 3.2 and 4.8 deliberately: they are h=4 plus or minus
20%, which is the only way the stability criterion can actually be evaluated. A grid
of doublings cannot test it.

---

## 6. Monthly totals

```powershell
.\run.ps1 src\monthly.py --year 2020 --out data\processed\daily_2020.csv
```

Streams one day at a time, about 30 min for a year cold. Use it to pick genuinely
wet and dry months rather than assuming: in 2020, December was wettest and August
driest, and **January ranked 9th of 12**.

---

## 7. Severity

Needs a reference catalogue from step 4.

```powershell
.\run.ps1 -c "import sys; sys.path.insert(0,'src'); import pandas as pd, severity; from config import DATA_PROCESSED; ref = pd.read_parquet(DATA_PROCESSED/'catalogue_final_2020_h4.parquet'); sc = severity.fit(ref, n_years=1.0); print(sc.describe())"
```

`severity.fit(ref, n_years=...)` returns a scale whose `.basis` is `percentile`
below a 10-year record and `return_period` at or above it. It will not report a
return period from a short record, because a percentile is not one.

---

## 8. Notebook

```powershell
.\run.ps1 -m jupyterlab
```

Open `notebooks/01_storm_tracking.ipynb` and set `START` / `END` in the first code
cell. Defaults to the online source, so no local archive is needed. One month is the
online ceiling: about 8 min and 121 MB.

---

## Where things land

| Path | Contents | In git |
|---|---|---|
| `data/cache/imerg_v07/<run>/<year>/` | fetched days, canonical layout | no |
| `data/processed/` | catalogues, sweeps, logs | no |
| `docs/` | findings, plan, sweeps, this file | yes |
| `temp/` | scratch only | no |

Credentials never belong in the tree; `.gitignore` covers `.env*`, `.netrc`,
`s3credentials`, `*-credentials.json`, keys and `secrets.*`.
