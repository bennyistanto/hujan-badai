"""Export small JSON summaries of the catalogue for the static dashboard.

The catalogue is about 2.6 GB and is not in the repository, so GitHub Actions cannot
recompute any of this. It publishes what this script writes. Run it locally after a
catalogue build, commit `site/data/`, and the site is current:

    python src/export_site.py
    python src/export_site.py --tracks-month 2020-12 --tracks-n 400

Every file carries a `meta` block naming this script, the inputs it read and the
parameters it read them at, so a number on the page can be traced to the settings that
produced it. Two numbers on the page are NOT from the catalogue: the CCL baselines in
`method.json`, which come from a one-off diagnostic run recorded in docs/findings.md.
They are tagged `from_findings` and the site labels them as such. Nothing else is
hand-entered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from config import DATA_PROCESSED, REPO

import severity

SITE_DATA = REPO / "site" / "data"

# Written at 4 significant figures. The page shows 2-3; the rest is headroom so a
# recomputed value can be compared against an old file without rounding noise.
ROUND = 6


def _git_rev() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                           capture_output=True, text=True, timeout=10)
        rev = r.stdout.strip() or "unknown"
        d = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True, timeout=10)
        return rev + ("+dirty" if d.stdout.strip() else "")
    except Exception:
        return "unknown"


def _meta(inputs, **extra) -> dict:
    m = {
        "script": "src/export_site.py",
        "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_rev": _git_rev(),
        "inputs": [str(Path(i).name) for i in inputs],
    }
    m.update(extra)
    return m


def _write(name: str, payload: dict) -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    p = SITE_DATA / name
    p.write_text(json.dumps(payload, separators=(",", ":"), default=_plain),
                 encoding="utf-8")
    kb = p.stat().st_size / 1024
    print(f"  {name:<22} {kb:>8.1f} KB")


def _plain(o):
    """numpy scalars serialise as numbers, not strings."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else round(float(o), ROUND)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, dt.datetime, dt.date)):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def catalogue_files(product: str = "final", h: float = 4.0) -> list[Path]:
    tag = f"_h{h:g}"
    f = sorted(DATA_PROCESSED.glob(f"catalogue_{product}_*{tag}.parquet"))
    if not f:
        raise SystemExit(
            f"no catalogues matching catalogue_{product}_*{tag}.parquet in "
            f"{DATA_PROCESSED}. Build one first: python src/build_year.py")
    return f


# --------------------------------------------------------------------------- pass 1

NEEDED = ["year", "month", "total_volume_km3", "max_intensity_mm_hr", "duration_h",
          "truncated_time", "truncated_space", "wcentroid_lat", "wcentroid_lon",
          "param_percolation_share", "param_prominence", "param_method"]


def scan(files: list[Path], regions: pd.DataFrame | None):
    """One pass over every catalogue, accumulating only what the page needs.

    Year by year rather than one concat: 13.4M rows of the full 43 columns does not
    need to be in memory at once, and this keeps peak use near 200 MB.
    """
    monthly, annual, regional = [], [], []
    vols, ints, perc = [], [], []
    params = set()

    for f in files:
        d = pd.read_parquet(f, columns=NEEDED)
        yr = int(d.year.iloc[0])
        params.add((str(d.param_method.iloc[0]), float(d.param_prominence.iloc[0])))

        keep = ~(d.truncated_time | d.truncated_space)
        clean = d[keep]

        g = d.groupby("month", observed=True)
        monthly.append(pd.DataFrame({
            "year": yr,
            "month": g.size().index,
            "storms": g.size().to_numpy(),
            "volume_km3": g.total_volume_km3.sum().to_numpy(),
        }))

        annual.append({
            "year": yr,
            "storms": int(len(d)),
            "volume_km3": float(d.total_volume_km3.sum()),
            "median_duration_h": float(d.duration_h.median()),
            "p95_duration_h": float(d.duration_h.quantile(0.95)),
            "truncated_frac": float(1.0 - keep.mean()),
            "months": int(d.month.nunique()),
        })

        if regions is not None:
            r = d[["month", "total_volume_km3"]].copy()
            # Same 1-degree floor convention as regions.seasonal_grid, so the join
            # lands on the cells k-means was actually fitted on.
            r["glat"] = np.floor(d.wcentroid_lat.to_numpy())
            r["glon"] = np.floor(d.wcentroid_lon.to_numpy())
            r = r.merge(regions, on=["glat", "glon"], how="inner")
            # Kept at cell resolution, not region resolution, because the two
            # seasonal-contrast estimators need different weightings and only the
            # per-cell numbers can produce both. 912 cells x 12 months is tiny.
            rg = (r.groupby(["region", "glat", "glon", "month"], observed=True)
                  .total_volume_km3.sum())
            regional.append(rg.rename("volume_km3").reset_index())

        # float32 halves the footprint of the two arrays that must be global.
        vols.append(clean.total_volume_km3.to_numpy(dtype="float32"))
        ints.append(clean.max_intensity_mm_hr.to_numpy(dtype="float32"))
        perc.append(d.param_percolation_share.dropna().unique())
        print(f"    {f.name}: {len(d):>9,} storms")

    return (pd.concat(monthly, ignore_index=True),
            pd.DataFrame(annual),
            pd.concat(regional, ignore_index=True) if regional else None,
            np.concatenate(vols),
            np.concatenate(ints),
            np.concatenate(perc),
            sorted(params))


# --------------------------------------------------------------------------- panels

def export_summary(annual, perc, params, vols, files):
    n_years = float(annual.months.sum() / 12.0)
    method, h = params[0]
    _write("summary.json", {
        "meta": _meta([f.name for f in files], n_catalogues=len(files)),
        "params": {"method": method, "prominence_mm_hr": h,
                   "wet_threshold_mm_hr": 1.0, "product": "IMERG Final V07"},
        "storms": int(annual.storms.sum()),
        "volume_km3": float(annual.volume_km3.sum()),
        "year_min": int(annual.year.min()),
        "year_max": int(annual.year.max()),
        "n_years": n_years,
        "storms_per_year": float(annual.storms.sum() / n_years),
        "percolation": {"min": float(perc.min()), "max": float(perc.max()),
                        "median": float(np.median(perc))},
        "median_volume_km3": float(np.median(vols)),
        "note": ("2025 is a 9-month year: IMERG Final V07 ends 2025-09-30. "
                 "n_years counts months, not calendar years."),
    })


def export_seasonal(monthly, files):
    """Monthly share of annual rain, by three estimators that do not agree.

    Finding 37 pooled every year, including 2025, which holds only January to
    September. That adds nine months of volume with no matching October to December,
    so it deflates the late-year shares and inflates the dry-season ones. The size of
    the bias is small but systematic, and it is worth showing rather than hiding: it
    moves the December-over-August ratio from 1.87x to 1.98x.

    `pooled_complete` is the headline series here: same estimator as the finding, with
    the partial year dropped.
    """
    per_year = monthly.pivot_table(index="year", columns="month",
                                   values="volume_km3", aggfunc="sum")
    full = per_year.notna().all(axis=1)          # drops 2025, a 9-month year

    pooled_all = per_year.sum() / per_year.sum().sum() * 100.0
    pooled_complete = (per_year[full].sum() / per_year[full].sum().sum() * 100.0)
    # Share within each year first, so one wet year cannot dominate the mean shape.
    share = per_year.div(per_year.sum(axis=1), axis=0) * 100.0
    mean_of_shares = share[full].mean()

    rows = []
    for m in range(1, 13):
        s = share.loc[full, m]
        rows.append({"month": m,
                     "pooled_complete_pct": float(pooled_complete[m]),
                     "pooled_all_pct": float(pooled_all[m]),
                     "mean_of_shares_pct": float(mean_of_shares[m]),
                     "p10_share_pct": float(s.quantile(0.10)),
                     "p90_share_pct": float(s.quantile(0.90)),
                     "min_share_pct": float(s.min()),
                     "max_share_pct": float(s.max())})

    def ratio(series):
        return float(series[12] / series[8])

    _write("seasonal.json", {
        "meta": _meta([f.name for f in files],
                      years_used=int(full.sum()),
                      excluded_years=[int(y) for y in share.index[~full]],
                      estimators=("pooled_complete is the headline. pooled_all "
                                  "reproduces docs/findings.md Finding 37 exactly, "
                                  "including its partial-year bias.")),
        "dec_over_aug": {"pooled_complete": ratio(pooled_complete),
                         "pooled_all": ratio(pooled_all),
                         "mean_of_shares": ratio(mean_of_shares)},
        "months": rows,
        "by_year": [{"year": int(y), "month": int(m),
                     "share_pct": float(share.loc[y, m])}
                    for y in share.index[full] for m in range(1, 13)],
    })


def export_annual(annual, files):
    _write("annual.json", {
        "meta": _meta([f.name for f in files]),
        "years": annual.to_dict("records"),
    })


REGION_NAMES = {0: "monsoonal", 1: "transitional", 2: "equatorial"}


def export_regional(regional, files):
    """Seasonal contrast per region, by both estimators that Finding 44 could mean.

    `cell_mean` gives every 1-degree cell equal weight, which is what k-means
    clustered on and what Finding 44's 54.52x reports. `volume_weighted` sums actual
    rainfall, so wet cells count for more, and gives 43.76x. Neither is wrong; they
    answer different questions, and quoting one number without saying which would make
    the figure unreproducible.
    """
    if regional is None:
        print("  regional.json         skipped (no regions_k3.parquet)")
        return

    cell = (regional.groupby(["region", "glat", "glon", "month"], observed=True)
            .volume_km3.sum().reset_index())

    tot = cell.groupby(["region", "month"], observed=True).volume_km3.sum().reset_index()
    tot["share_pct"] = (tot.volume_km3
                        / tot.groupby("region", observed=True).volume_km3
                        .transform("sum") * 100.0)

    # Each cell's own seasonal shape, then averaged across the cells of a region.
    wide = cell.pivot_table(index=["region", "glat", "glon"], columns="month",
                            values="volume_km3", aggfunc="sum").fillna(0.0)
    shapes = wide.div(wide.sum(axis=1), axis=0)
    cm = shapes.groupby("region").mean()

    domain = tot.groupby("month", observed=True).volume_km3.sum()

    contrast = []
    for reg, g in tot.groupby("region", observed=True):
        v = g.set_index("month").volume_km3
        c = cm.loc[reg]
        contrast.append({
            "region": int(reg),
            "name": REGION_NAMES.get(int(reg), str(reg)),
            "cells": int((wide.index.get_level_values("region") == reg).sum()),
            "volume_share_of_domain_pct": float(v.sum() / tot.volume_km3.sum() * 100.0),
            "volume_weighted": {"contrast": float(v.max() / v.min()),
                                "peak_month": int(v.idxmax()),
                                "trough_month": int(v.idxmin())},
            "cell_mean": {"contrast": float(c.max() / c.min()),
                          "peak_month": int(c.idxmax()),
                          "trough_month": int(c.idxmin())},
        })

    _write("regional.json", {
        "meta": _meta(["regions_k3.parquet", "catalogue_final_*_h4.parquet"],
                      note=("region ids are k-means labels from src/regions.py; the "
                            "names are descriptive, not part of the clustering. "
                            "cell_mean reproduces Finding 44's 54.52x.")),
        "domain": {"contrast": float(domain.max() / domain.min()),
                   "peak_month": int(domain.idxmax()),
                   "trough_month": int(domain.idxmin())},
        "cells": [{"region": int(r), "month": int(m),
                   "volume_km3": float(v), "share_pct": float(s)}
                  for r, m, v, s in tot[["region", "month", "volume_km3",
                                         "share_pct"]].itertuples(index=False)],
        "shapes": [{"region": int(r), "month": int(m), "share": float(cm.loc[r, m])}
                   for r in cm.index for m in range(1, 13)],
        "contrast": contrast,
    })


def export_concentration(vols, files):
    v = np.sort(vols)[::-1]
    cum = np.cumsum(v, dtype="float64")
    cum /= cum[-1]
    n = v.size
    # Log-spaced in storm rank, so the head of the curve is resolved without
    # shipping 13.4M points.
    idx = np.unique(np.round(np.geomspace(1, n, 400)).astype(np.int64)) - 1
    _write("concentration.json", {
        "meta": _meta([f.name for f in files], n_storms=int(n),
                      note="truncated storms excluded"),
        "curve": [{"storm_frac": float((i + 1) / n),
                   "volume_frac": float(cum[i])} for i in idx],
        "milestones": [
            {"top_pct": p,
             "volume_share_pct": float(cum[max(int(round(p / 100 * n)) - 1, 0)] * 100)}
            for p in (1, 5, 10, 13, 20, 50)],
    })


def export_severity(sc, vols, ints, files):
    lo, hi = sc.vol_edges
    ilo, ihi = sc.int_edges
    vb = np.digitize(vols, [lo, hi])
    ib = np.digitize(ints, [ilo, ihi])
    names = severity.CLASS_NAMES
    grid = []
    for i in range(3):
        for j in range(3):
            grid.append({"vol_band": i, "int_band": j,
                         "name": names[i * 3 + j],
                         "storms": int(((vb == i) & (ib == j)).sum())})
    _write("severity.json", {
        "meta": _meta([f.name for f in files],
                      note=("the full 3x3 grid: volume band by intensity band. "
                            "Bands are exceedance rates, not return periods, "
                            "because per-storm return periods are meaningless at "
                            "449k storms a year: docs/findings.md Finding 40.")),
        "basis": sc.basis,
        "band_kind": sc.band_kind,
        "rate_bands_per_year": list(sc.bands),
        "volume_edges_km3": [float(lo), float(hi)],
        "intensity_edges_mm_hr": [float(ilo), float(ihi)],
        "grid": grid,
        "n_storms": int(vols.size),
        "n_years": float(sc.n_years),
    })


def export_sweep():
    rows, inputs = [], []
    for p in sorted(DATA_PROCESSED.glob("sweep-prominence-*.csv")):
        d = pd.read_csv(p)
        d["method"] = p.stem.replace("sweep-prominence-", "")
        rows.append(d)
        inputs.append(p.name)
    if not rows:
        print("  sweep.json            skipped (no sweep CSVs)")
        return
    d = pd.concat(rows, ignore_index=True)
    _write("sweep.json", {
        "meta": _meta(inputs, note="one row per month per h per method"),
        "columns": list(d.columns),
        "rows": d.to_dict("records"),
    })


def export_diurnal():
    p = DATA_PROCESSED / "diurnal_h4.parquet"
    if not p.exists():
        print("  diurnal.json          skipped (no diurnal_h4.parquet)")
        return
    d = pd.read_parquet(p)
    _write("diurnal.json", {
        "meta": _meta([p.name],
                      note=("share of storm initiations per 2-hour bin. local = "
                            "UTC + 7/8/9 by longitude; see src/diurnal.py")),
        "bins": d.to_dict("records"),
    })


def export_leadtime():
    p = DATA_PROCESSED / "transitions_h4.parquet"
    if not p.exists():
        print("  leadtime.json         skipped (no transitions_h4.parquet)")
        return
    d = pd.read_parquet(p)
    sea = d[d.transition == "sea -> land"]

    # MIN_N = 1000 reproduces Finding 53's r = +0.877 across 30 provinces exactly.
    # The correlation is mildly sensitive to this cut (0.836 with all 34 provinces),
    # because the provinces it drops are small-sample ones with noisy medians. Stated
    # rather than tuned: the threshold is the finding's, not a search for a better r.
    MIN_N = 1000
    agg = (sea.groupby("province", observed=True)
           .agg(n=("hours_at_sea", "size"),
                median_lead_h=("hours_at_sea", "median"),
                p90_lead_h=("hours_at_sea", lambda s: s.quantile(0.90)),
                offshore_km=("offshore_km_at_start", "median"))
           .reset_index())
    prov = agg[agg.n >= MIN_N].sort_values("median_lead_h")

    def pearson(t):
        return float(np.corrcoef(t.offshore_km, t.median_lead_h)[0, 1])

    hist = (sea.hours_at_sea.clip(upper=24)
            .value_counts().sort_index().rename("n").reset_index())
    hist.columns = ["hours_at_sea", "n"]

    quart = (sea.groupby("q", observed=True)
             .agg(n=("hours_at_sea", "size"),
                  median_lead_h=("hours_at_sea", "median"),
                  p90_lead_h=("hours_at_sea", lambda s: s.quantile(0.90)))
             .reset_index())

    by_region = (sea.groupby("region", observed=True)
                 .agg(n=("hours_at_sea", "size"),
                      median_lead_h=("hours_at_sea", "median"),
                      p90_lead_h=("hours_at_sea", lambda s: s.quantile(0.90)))
                 .reset_index())

    _write("leadtime.json", {
        "meta": _meta([p.name],
                      min_storms_per_province=MIN_N,
                      note=("r is across provinces, not across storms. Per storm it "
                            "is +0.505: aggregation removes within-province scatter "
                            "and the two numbers are not interchangeable. See "
                            "docs/findings.md Finding 53.")),
        "n_sea_formed": int(len(sea)),
        "median_lead_h": float(sea.hours_at_sea.median()),
        "p90_lead_h": float(sea.hours_at_sea.quantile(0.90)),
        "r_offshore_vs_lead": pearson(prov),
        "r_all_provinces": pearson(agg),
        "n_provinces": int(len(prov)),
        "n_provinces_total": int(len(agg)),
        "provinces": prov.to_dict("records"),
        "histogram": hist.to_dict("records"),
        "by_volume_quartile": quart.to_dict("records"),
        "by_region": by_region.to_dict("records"),
    })


def export_families():
    p = DATA_PROCESSED / "families_final_h4_g3_d50.parquet"
    if not p.exists():
        print("  families.json         skipped (no families parquet)")
        return
    d = pd.read_parquet(p)
    g = (d.groupby("age_class", observed=True)
         .agg(families=("fam", "size"),
              volume_km3=("volume_km3", "sum"),
              median_storms=("n_storms", "median"),
              max_age_h=("age_h", "max"))
         .reset_index())
    g["volume_share_pct"] = g.volume_km3 / g.volume_km3.sum() * 100.0
    _write("families.json", {
        "meta": _meta([p.name],
                      note=("families link storms within 3 h and 50 km. Linking "
                            "is deliberately strict: bounding-box overlap "
                            "percolates, see docs/findings.md Finding 47.")),
        "n_families": int(len(d)),
        "classes": g.to_dict("records"),
    })


def export_family_severity(event_start, event_end, bbox):
    """Severity with the EVENT as the unit, and the Jakarta event ranked against it.

    This is the answer to the problem Finding 57 exposed: a per-storm class could not
    say anything useful about a flood, because a storm at h = 4 is one convective cell
    and 99.8% of cells share the bottom class. Ranking linked events instead gives a
    population where the top of the distribution is small enough for a return period
    to mean something inside a 28-year record.
    """
    try:
        import family_severity as fs
    except ImportError as e:
        print(f"  family_severity.json  skipped ({e})")
        return
    try:
        fam = fs.load()
    except SystemExit:
        print("  family_severity.json  skipped (no family catalogue; run "
              "src/families.py --year 1998 2025)")
        return

    sc = fs.fit(fam)
    occ = fs.report(fam, sc).reset_index().rename(columns={"index": "severity"})
    ny = fs.n_years(fam)

    # Occupancy at several band rates, so the page can show that the choice was made
    # by measurement rather than taken from the storm scale.
    # The grid spans operational rates (tens of events a year) up to rates that
    # correspond to ordinary percentiles, because the trade-off between the two is the
    # whole story: a rate low enough to mean "worth a warning" is necessarily deep in
    # the tail of a population this size, so the bottom class stays crowded whatever
    # is chosen. Showing that is more useful than hiding it behind one setting.
    ref = np.sort(fam.volume_km3.to_numpy())
    alts = []
    for bands in [(500.0, 50.0), (200.0, 20.0), (20.0, 2.0),
                  (25000.0, 2500.0), (100000.0, 12500.0)]:
        s2 = fs.fit(fam, bands)
        t2 = fs.report(fam, s2)
        lo = float(s2.vol_edges[0])
        alts.append({
            "bands": list(bands),
            "volume_edges_km3": [lo, float(s2.vol_edges[1])],
            "lower_edge_percentile": float(np.searchsorted(ref, lo) / ref.size * 100),
            "lowest_class_share_pct": float(t2.loc["very low", "share_pct"]),
            "top3_families": int(t2.loc[["intense", "severe", "extreme"],
                                        "families"].sum()),
        })

    ranked = fs.rank_event(fam, event_start, event_end, bbox, sc)

    # The third level. Ranking objects, at either the cell or the event layer, does
    # not identify this flood; ranking rainfall over an area and a window does. Both
    # the area and the window length change the answer, so several of each are
    # exported rather than one, and the page shows the dependence instead of picking
    # the flattering combination.
    JABODETABEK = (-6.80, -5.95, 106.30, 107.20)
    area_rank = []
    for area_name, box in [("Jabodetabek", JABODETABEK),
                           ("Jakarta and West Java", tuple(bbox))]:
        try:
            s = fs.area_daily_volume(box)
        except Exception as e:
            print(f"    area series failed for {area_name}: {e}")
            continue
        for days, start in [(1, "2020-01-01"), (2, "2019-12-31"),
                            (3, "2019-12-31"), (4, "2019-12-30"),
                            (7, "2019-12-28")]:
            t0 = pd.Timestamp(start)
            r = fs.rank_area_event(s, t0, t0 + pd.Timedelta(days=days - 1))
            r["area"] = area_name
            r["bbox"] = list(box)
            r["start"] = str(t0.date())
            # The full annual-maxima series is only needed for the headline case.
            if not (area_name == "Jabodetabek" and days == 2):
                r.pop("annual_maxima", None)
            area_rank.append(r)

    # The biggest events in the record, for context next to the Jakarta one.
    top = fam.nlargest(12, "volume_km3")
    pct = fs.percentile_of(fam, top.volume_km3.to_numpy())
    tcls = sc.classify(top.volume_km3.to_numpy(), top.max_intensity_mm_hr.to_numpy())

    _write("family_severity.json", {
        "meta": _meta([fs.family_file().name],
                      note=("families are storms linked within 3 h and 50 km. The "
                            "linking must stay strict: looser rules percolate exactly "
                            "as the segmentation did, see docs/findings.md Finding "
                            "47. Percolation share is reported so that check is "
                            "visible.")),
        "n_families": int(len(fam)),
        "n_years": ny,
        "families_per_year": float(len(fam) / ny),
        "percolation_share": float(fam.volume_km3.max() / fam.volume_km3.sum()),
        "rate_bands_per_year": list(sc.bands),
        "volume_edges_km3": [float(sc.vol_edges[0]), float(sc.vol_edges[1])],
        "intensity_edges_mm_hr": [float(sc.int_edges[0]), float(sc.int_edges[1])],
        "band_choice": alts,
        "occupancy": occ.to_dict("records"),
        "distribution": {
            "volume_p50": float(fam.volume_km3.median()),
            "volume_p99": float(fam.volume_km3.quantile(0.99)),
            "volume_max": float(fam.volume_km3.max()),
            "n_storms_p50": float(fam.n_storms.median()),
            "n_storms_max": int(fam.n_storms.max()),
            "age_h_p50": float(fam.age_h.median()),
            "age_h_max": float(fam.age_h.max()),
        },
        "event": ranked,
        "area_rank": area_rank,
        "largest_in_record": [
            {"start": pd.Timestamp(r.start).isoformat(),
             "volume_km3": round(float(r.volume_km3), 3),
             "n_storms": int(r.n_storms), "age_h": float(r.age_h),
             "lat": round(float(r.lat), 2), "lon": round(float(r.lon), 2),
             "severity": str(c), "percentile": round(float(p), 5)}
            for r, p, c in zip(top.itertuples(index=False), pct, tcls.severity)],
    })


_WKT = re.compile(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)")


TRACK_COLS = ["track_wkt", "total_volume_km3", "max_intensity_mm_hr", "duration_h",
              "start_time", "end_time", "start_lat", "start_lon", "end_lat",
              "end_lon", "n_timesteps", "truncated_time", "truncated_space"]


def _tracks_in_window(start: str, end: str, product: str, h: float,
                      bbox=None, n=None):
    """Storms overlapping [start, end], optionally intersecting a bounding box.

    Reads every calendar year the window touches, so a window crossing New Year (the
    Jakarta event does) is not silently truncated to one file.
    """
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    frames, used = [], []
    for y in range(t0.year, t1.year + 1):
        f = DATA_PROCESSED / f"catalogue_{product}_{y}_h{h:g}.parquet"
        if not f.exists():
            continue
        d = pd.read_parquet(f, columns=TRACK_COLS)
        # Overlap, not containment: a storm alive at the window edge belongs in it.
        d = d[(d.start_time <= t1) & (d.end_time >= t0)]
        frames.append(d)
        used.append(f.name)
    if not frames:
        return None, []
    d = pd.concat(frames, ignore_index=True)

    if bbox:
        lo_lat, hi_lat, lo_lon, hi_lon = bbox
        # Track endpoints are enough to catch anything crossing the box at this size.
        inside = (((d.start_lat.between(lo_lat, hi_lat)) &
                   (d.start_lon.between(lo_lon, hi_lon))) |
                  ((d.end_lat.between(lo_lat, hi_lat)) &
                   (d.end_lon.between(lo_lon, hi_lon))))
        d = d[inside]

    d = d.sort_values("total_volume_km3", ascending=False)
    if n:
        d = d.head(n)
    return d, used


def _features(d, sc):
    feats = []
    for row in d.itertuples(index=False):
        pts = [[float(a), float(b)] for a, b in _WKT.findall(row.track_wkt)]
        if not pts:
            continue
        cls = sc.classify([row.total_volume_km3], [row.max_intensity_mm_hr])
        feats.append({
            "type": "Feature",
            "geometry": ({"type": "Point", "coordinates": pts[0]} if len(pts) == 1
                         else {"type": "LineString", "coordinates": pts}),
            "properties": {
                "volume_km3": round(float(row.total_volume_km3), 4),
                "max_intensity_mm_hr": round(float(row.max_intensity_mm_hr), 2),
                "duration_h": float(row.duration_h),
                "start": pd.Timestamp(row.start_time).isoformat(),
                "end": pd.Timestamp(row.end_time).isoformat(),
                "truncated": bool(row.truncated_time or row.truncated_space),
                "severity": str(cls.severity.iloc[0]),
                "severity_index": int(cls.severity_index.iloc[0]),
            },
        })
    return feats


# Jakarta, Banten and West Java: the coast that flooded on 2020-01-01. Wide enough to
# show storms arriving from the Java Sea and from the Indian Ocean side.
JAKARTA_BBOX = (-7.8, -5.2, 104.8, 108.6)

JAKARTA_PLACES = [
    {"name": "Jakarta", "lon": 106.845, "lat": -6.209},
    {"name": "Bogor", "lon": 106.800, "lat": -6.595},
    {"name": "Bandung", "lon": 107.619, "lat": -6.917},
    {"name": "Serang", "lon": 106.150, "lat": -6.120},
]

# DKI Jakarta, and the Ciliwung headwaters behind it. The flood water that reached the
# city came off both, which is the whole point of the accumulation panel: the relevant
# unit is rain over a catchment, not the rank of any one storm object.
ACCUM_AREAS = {
    "DKI Jakarta": (-6.40, -6.08, 106.68, 107.00),
    "Bogor and the Ciliwung headwaters": (-6.75, -6.40, 106.70, 107.05),
    "Jabodetabek": (-6.80, -5.95, 106.30, 107.20),
}


def export_rank_context(vols, start, end, bbox, product, h):
    """Where the event's storms sit in the 28-year population, as percentiles.

    This panel exists because the dashboard previously said every storm over Jakarta
    fell in the lowest severity class and read that as the storms being unremarkable.
    The class is real but it holds 99.8% of all storms, so membership of it carries
    almost no information. The percentiles say something quite different: the largest
    of these storms sits above the 99.5th, which is a genuinely large object. Both
    numbers are exported so the page cannot state one without the other.
    """
    ref = np.sort(vols)
    n = ref.size
    d, used = _tracks_in_window(start, end, product, h, bbox=bbox)
    if d is None:
        print("  rank_context.json     skipped (no catalogue)")
        return
    v = d.total_volume_km3.to_numpy()
    pct = np.searchsorted(ref, v) / n * 100.0

    top = d.assign(percentile=pct, rank=n - np.searchsorted(ref, v)) \
           .nlargest(10, "total_volume_km3")

    _write("rank_context.json", {
        "meta": _meta(used, window=f"{start} to {end}",
                      note=("percentile of each event storm's volume within the "
                            "28-year population of non-truncated storms. The "
                            "severity class and the percentile disagree because the "
                            "class edges are exceedance rates set for operational "
                            "rarity, not quantiles.")),
        "n_reference": int(n),
        "n_event": int(len(d)),
        "event_total_km3": float(v.sum()),
        "reference_quantiles": {
            str(q): float(np.quantile(ref, q / 100))
            for q in (50, 90, 99, 99.9, 99.99)},
        "above": [{"quantile": q,
                   "threshold_km3": float(np.quantile(ref, q / 100)),
                   "n": int((v > np.quantile(ref, q / 100)).sum()),
                   "share_pct": float((v > np.quantile(ref, q / 100)).mean() * 100)}
                  for q in (50, 90, 99, 99.9, 99.99)],
        "top": [{"start": pd.Timestamp(r.start_time).isoformat(),
                 "volume_km3": round(float(r.total_volume_km3), 4),
                 "max_intensity_mm_hr": round(float(r.max_intensity_mm_hr), 2),
                 "duration_h": float(r.duration_h),
                 "percentile": round(float(r.percentile), 4),
                 "rank": int(r.rank)}
                for r in top.itertuples(index=False)],
    })


def export_accumulation(start, end, product):
    """What actually fell, in mm, over the days of the flood.

    The catalogue answers "what storms were there". A flood answers to accumulated
    depth over a catchment, which no single storm object represents. This reads the
    IMERG cube directly so the page can show both and say which is which.

    Depth per step is R * 0.5, because IMERG `precipitation` is mm/hr on half-hourly
    steps. Omitting that factor doubles every number here.
    """
    try:
        from imerg_io import load_range
        from config import DT_HOURS
    except ImportError as e:
        print(f"  accumulation.json     skipped ({e})")
        return
    try:
        da = load_range(start, end, source="local", product=product, progress=False)
    except Exception as e:
        print(f"  accumulation.json     skipped (load failed: {e})")
        return

    depth = da * DT_HOURS                       # mm/hr on a 0.5 h step -> mm
    lo_lat, hi_lat, lo_lon, hi_lon = JAKARTA_BBOX
    sub = depth.sel(lat=slice(lo_lat, hi_lat), lon=slice(lo_lon, hi_lon))
    total = sub.sum("time")

    grid = [{"lat": round(float(la), 2), "lon": round(float(lo), 2),
             "mm": round(float(total.sel(lat=la, lon=lo)), 1)}
            for la in total.lat.values for lo in total.lon.values]

    areas = []
    for name, (a0, a1, o0, o1) in ACCUM_AREAS.items():
        box = depth.sel(lat=slice(a0, a1), lon=slice(o0, o1))
        tot = box.sum("time")
        # Rolling 24 h = 48 half-hourly steps, the window a daily gauge would report.
        roll = box.rolling(time=48, min_periods=48).sum().max("time")
        areas.append({
            "name": name,
            "cells": int(tot.size),
            "mean_mm": round(float(tot.mean()), 1),
            "max_cell_mm": round(float(tot.max()), 1),
            "peak_24h_max_cell_mm": round(float(roll.max()), 1),
            "peak_24h_mean_mm": round(float(roll.mean()), 1),
        })

    # Daily totals on the LOCAL calendar day, which is what a gauge reports and the
    # only form directly comparable with the 200 to 380 mm figures published for
    # 1 January 2020. Indonesia's western zone is UTC+7.
    local = depth.assign_coords(time=depth.time + np.timedelta64(7, "h"))
    daily = []
    for name_, (a0, a1, o0, o1) in ACCUM_AREAS.items():
        box = local.sel(lat=slice(a0, a1), lon=slice(o0, o1))
        per_day = box.resample(time="1D").sum()
        for t, arr in zip(per_day.time.values, per_day.values):
            daily.append({"area": name_, "local_date": str(t)[:10],
                          "mean_mm": round(float(arr.mean()), 1),
                          "max_cell_mm": round(float(arr.max()), 1)})

    # The most generous reading available anywhere near the city, so the comparison
    # with gauges is not made artificially unflattering by a too-small box.
    wide = depth.sel(lat=slice(-7.2, -5.6), lon=slice(106.0, 107.6))
    best24 = float(wide.rolling(time=48, min_periods=48).sum().max())

    dki = depth.sel(lat=slice(*ACCUM_AREAS["DKI Jakarta"][:2]),
                    lon=slice(*ACCUM_AREAS["DKI Jakarta"][2:]))
    ser = pd.DataFrame({"mean_mm": dki.mean(("lat", "lon")).values,
                        "max_mm": dki.max(("lat", "lon")).values},
                       index=pd.to_datetime(dki.time.values))
    hourly = ser.resample("1h").sum()
    hourly["cum_mean_mm"] = hourly.mean_mm.cumsum()

    _write("accumulation.json", {
        "meta": _meta([f"IMERG {product} {start} to {end}"],
                      note=("IMERG accumulation, read straight from the cube, not "
                            "from the catalogue. Satellite estimates smooth extremes: "
                            "gauges in Jakarta recorded far more in 24 h than the "
                            "grid shows, and the page says so.")),
        "window": [start, end],
        "bbox": list(JAKARTA_BBOX),
        "areas": areas,
        "daily_local": daily,
        "best_24h_near_jakarta_mm": round(best24, 1),
        "gauge_reference": {
            "note": ("Gauges in Jakarta recorded 200 to 380 mm on 1 January 2020, "
                     "the highest daily total in the city's record. The satellite "
                     "figures above are what IMERG sees on an 11 km grid, and they "
                     "are roughly half that. Stated so the gap is visible, not "
                     "hidden."),
            "reported_range_mm": [200, 380],
        },
        "grid": grid,
        "hourly": [{"t": t.isoformat(),
                    "mean_mm": round(float(r.mean_mm), 3),
                    "max_mm": round(float(r.max_mm), 3),
                    "cum_mean_mm": round(float(r.cum_mean_mm), 2)}
                   for t, r in hourly.iterrows()],
    })


def _step_series(R, labels, lat, nt):
    """Per (storm, timestep) volume, footprint and peak intensity.

    `storms.py` computes exactly these inside `_tracklines` and then throws them away,
    keeping only the centroid. The dashboard's detail panel needs them, so they are
    recomputed here with the same bincount-on-a-combined-key trick and, importantly,
    the same unit convention: R is mm/hr on half-hourly steps, so depth over one step
    is R * DT_HOURS. Getting that wrong is a factor-of-two error.
    """
    from config import DT_HOURS
    from imerg_io import cell_area_m2

    R = np.nan_to_num(np.asarray(R, dtype=np.float64), nan=0.0)
    nt_, ny, nx = R.shape
    nb = int(labels.max()) + 1
    area_m2 = cell_area_m2(lat)[None, :, None]

    flat = labels.ravel()
    ti = np.repeat(np.arange(nt_), ny * nx)
    key = flat.astype(np.int64) * nt_ + ti
    size = nb * nt_

    vol = (R * DT_HOURS / 1000.0 * area_m2 / 1e9).ravel()
    a_row = np.tile(np.repeat(cell_area_m2(lat) / 1e6, nx), nt_)

    v = np.bincount(key, weights=vol, minlength=size).reshape(nb, nt_)
    a = np.bincount(key, weights=a_row, minlength=size).reshape(nb, nt_)
    pk = np.zeros(size)
    np.maximum.at(pk, key, R.ravel())
    pk = pk.reshape(nb, nt_)
    return v, a, pk


def export_event(start: str, end: str, bbox, h: float, product: str, sc,
                 pad_days: int = 1, name: str = "tracks_jakarta.json",
                 places=None, label: str = "", domain_n: int = 400):
    """Re-segment one short window and export its storms with per-step detail.

    Deliberately NOT read from the year catalogues. Those carry only whole-storm
    attributes, and the detail panel needs each storm's hour-by-hour evolution. Doing
    the segmentation here also makes this section reproducible on its own: four days of
    IMERG rather than a 2.6 GB archive.

    The window is padded by a day on each side and a storm is kept by where its
    volume-weighted centroid time falls, the same rule `build_year.py` uses, so storms
    alive at midnight on the 30th are not cut in half.
    """
    try:
        from imerg_io import load_range
        from mergetree import build_merge_tree, segment_at
        from storms import storm_table
    except ImportError as e:
        print(f"  {name:<22} skipped ({e})")
        return

    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    pad = pd.Timedelta(days=pad_days)
    try:
        da = load_range((t0 - pad).strftime("%Y-%m-%d"),
                        (t1 + pad).strftime("%Y-%m-%d"),
                        source="local", product=product, progress=False)
    except Exception as e:
        print(f"  {name:<22} skipped (load failed: {e})")
        return

    R = da.values
    lat = da.lat.values
    lon = da.lon.values
    time = pd.to_datetime(da.time.values)

    tree = build_merge_tree(R, wet_threshold=1.0)
    labels = segment_at(tree, R, h, min_voxels=6)
    df = storm_table(R, labels, time, lat, lon,
                     params=dict(method="mergetree", wet_threshold=1.0,
                                 prominence=h, min_voxels=6))
    if df.empty:
        print(f"  {name:<22} skipped (no storms)")
        return

    v, a, pk = _step_series(R, labels, lat, len(time))

    # Claim by volume-weighted centroid time, the same rule build_year.py uses, so a
    # storm alive at the window edge belongs to exactly one side.
    in_window = df.wcentroid_time.between(t0, t1)
    lo_lat, hi_lat, lo_lon, hi_lon = bbox
    in_box = (((df.start_lat.between(lo_lat, hi_lat)) &
               (df.start_lon.between(lo_lon, hi_lon))) |
              ((df.end_lat.between(lo_lat, hi_lat)) &
               (df.end_lon.between(lo_lon, hi_lon))))

    def _build(sel):
        return _event_features(df[sel].sort_values("total_volume_km3",
                                                   ascending=False),
                               v, a, pk, time, sc)

    # Both maps are cut from THIS one segmentation. They used to come from different
    # ones: the domain map read the year catalogues while this window was re-segmented
    # for its per-step detail. Same days, different objects, and the two maps visibly
    # disagreed. One segmentation, two views, is the only way they can agree.
    dom = df[in_window].nlargest(domain_n, "total_volume_km3")
    _write("tracks_domain.json", {
        "meta": _meta([f"IMERG {product} {start} to {end}"],
                      window=f"{start} to {end}", n_requested=domain_n,
                      n_written=int(len(dom)), prominence=h,
                      note=("the largest storms by volume in this window, cut from "
                            "the same segmentation as the detail map below it, so "
                            "the same storm is the same object on both.")),
        "severity_edges": {"volume_km3": list(sc.vol_edges),
                           "intensity_mm_hr": list(sc.int_edges),
                           "bands": list(sc.bands), "basis": sc.basis},
        "bbox": [-11.6, 6.6, 94.4, 141.6],
        "window": [start, end],
        "type": "FeatureCollection",
        "features": _event_features(dom, v, a, pk, time, sc,
                                    with_series=False),
    })

    df = df[in_window & in_box].sort_values("total_volume_km3", ascending=False)
    feats = _event_features(df, v, a, pk, time, sc)
    _write_event_file(name, feats, df, start, end, bbox, h, product, pad_days,
                      sc, places, label)
    return df


def _event_features(df, v, a, pk, time, sc, with_series=True):
    feats = []
    for row in df.itertuples(index=False):
        # `storm_table` hands back the track as (timestep, lat, lon). Using it rather
        # than re-parsing the WKT keeps the step index, which is what aligns each
        # vertex with its own volume and area in the series below.
        tr = [(int(t), float(la), float(lo)) for t, la, lo in row.track
              if np.isfinite(la) and np.isfinite(lo)]
        if not tr:
            continue
        pts = [[lo, la] for _, la, lo in tr]
        steps = [t for t, _, _ in tr]
        lb = int(row.storm_id)
        cls = sc.classify([row.total_volume_km3], [row.max_intensity_mm_hr])
        feats.append({
            "type": "Feature",
            "geometry": ({"type": "Point", "coordinates": pts[0]} if len(pts) == 1
                         else {"type": "LineString", "coordinates": pts}),
            "properties": {
                "id": lb,
                "volume_km3": round(float(row.total_volume_km3), 4),
                "max_intensity_mm_hr": round(float(row.max_intensity_mm_hr), 2),
                "duration_h": float(row.duration_h),
                "max_area_km2": round(float(row.max_area_km2), 1),
                "start": pd.Timestamp(row.start_time).isoformat(),
                "end": pd.Timestamp(row.end_time).isoformat(),
                "truncated": bool(row.truncated_time or row.truncated_space),
                "severity": str(cls.severity.iloc[0]),
                "severity_index": int(cls.severity_index.iloc[0]),
            },
        })
        if not with_series:
            continue
        # Hour by hour: what the storm was doing at each half-hourly step. One entry
        # per track vertex, so the series and the line agree. Only the detail map
        # needs this; carrying it on the 400 domain storms tripled that file for
        # data nothing reads.
        feats[-1]["properties"]["series"] = {
            "t": [pd.Timestamp(time[i]).isoformat() for i in steps],
            "volume_km3": [round(float(v[lb, i]), 5) for i in steps],
            "area_km2": [round(float(a[lb, i]), 1) for i in steps],
            "peak_mm_hr": [round(float(pk[lb, i]), 2) for i in steps],
            "lon": [q[0] for q in pts],
            "lat": [q[1] for q in pts],
        }
    return feats


def _write_event_file(name, feats, df, start, end, bbox, h, product, pad_days,
                      sc, places, label):
    _write(name, {
        "meta": _meta([f"IMERG {product} {start} to {end}"],
                      window=f"{start} to {end}", pad_days=pad_days,
                      prominence=h, n_written=len(feats),
                      note=("segmented from the IMERG cube for this window alone, not "
                            "read from the year catalogues, because the detail panel "
                            "needs per-step values the catalogue does not store. "
                            "Storms are claimed by volume-weighted centroid time.")),
        "severity_edges": {"volume_km3": list(sc.vol_edges),
                           "intensity_mm_hr": list(sc.int_edges),
                           "bands": list(sc.bands), "basis": sc.basis},
        "bbox": list(bbox),
        "window": [start, end],
        "label": label,
        "places": places or [],
        "type": "FeatureCollection",
        "features": feats,
    })


def export_tracks(start: str, end: str, n: int, product: str, h: float, sc):
    """The full-AOI map, over the same window the Jakarta section uses.

    An earlier version showed December 2020, which was the default left over from the
    sweep study. That month is not remarkable: it ranks 36th of the 333 months in the
    record by volume. It was only the wettest month OF 2020. Showing the same days as
    the detail map instead lets the two be read together, and removes an implied claim
    that the month was special.

    Coloured by the full-record severity scale, passed in rather than refitted, so a
    colour means the same thing on both maps.
    """
    edges = {"volume_km3": list(sc.vol_edges),
             "intensity_mm_hr": list(sc.int_edges),
             "basis": sc.basis, "band_kind": sc.band_kind,
             "bands": list(sc.bands)}

    d, used = _tracks_in_window(start, end, product, h, n=n)
    if d is None:
        print("  tracks_domain.json    skipped (no catalogue for that window)")
        return
    _write("tracks_domain.json", {
        "meta": _meta(used, window=f"{start} to {end}", n_requested=n,
                      n_written=len(d),
                      note=("the largest storms by volume alive in this window, not a "
                            "random sample. Same days as the Jakarta detail map. "
                            "Severity is on the full-record scale, so a colour means "
                            "the same thing on both maps.")),
        "severity_edges": edges,
        "bbox": [-11.6, 6.6, 94.4, 141.6],
        "window": [start, end],
        "type": "FeatureCollection",
        "features": _features(d, sc),
    })


def export_geography():
    """Natural Earth land, clipped and simplified, one file per map extent.

    Vendored rather than fetched at page load: the page then has no runtime dependency
    on a third-party tile or atlas service, and the two extents can be simplified
    differently. The domain map is 5,200 km wide and does not need 10m detail; the
    Jakarta map is 400 km wide and does.
    """
    try:
        import geopandas as gpd
        from cartopy.io import shapereader
        from shapely.geometry import box
    except ImportError as e:
        print(f"  land_*.json           skipped ({e})")
        return

    p = shapereader.natural_earth(resolution="10m", category="physical", name="land")
    land = gpd.read_file(p)

    for name, bbox, tol in [
            ("land_domain.json", (94.4, -11.6, 141.6, 6.6), 0.02),
            ("land_jakarta.json", (JAKARTA_BBOX[2], JAKARTA_BBOX[0],
                                   JAKARTA_BBOX[3], JAKARTA_BBOX[1]), 0.004)]:
        clip = gpd.clip(land, box(*bbox))
        clip = clip[~clip.is_empty]
        # Simplify after clipping, so a coastline is not smoothed across the cut.
        clip = clip.assign(geometry=clip.geometry.simplify(tol, preserve_topology=True))
        SITE_DATA.mkdir(parents=True, exist_ok=True)
        out = SITE_DATA / name
        out.write_text(clip.to_json(drop_id=True), encoding="utf-8")
        print(f"  {name:<22} {out.stat().st_size / 1024:>8.1f} KB")


def export_method(perc, files):
    """The percolation comparison: the finding the whole method rests on.

    The merge-tree column is measured here, from every catalogue. The CCL columns are
    from a one-off diagnostic (src/probe.py) recorded in docs/findings.md, because
    reproducing them needs the IMERG cube rather than the catalogue. Tagged so the
    page can say which is which.
    """
    _write("method.json", {
        "meta": _meta([f.name for f in files]),
        "window": "2020-01-01 to 2020-01-05, full AOI, wet threshold 1.0 mm/h",
        "rows": [
            {"method": "CCL, 1.0 mm/h (as published)", "storms": 3378,
             "largest_object_share": 0.901, "rain_captured": 0.993,
             "from_findings": "Finding 1"},
            {"method": "CCL, 5.0 mm/h (de-percolated)", "storms": 2045,
             "largest_object_share": 0.220, "rain_captured": 0.187,
             "from_findings": "Finding 15"},
            {"method": "merge tree, h = 4.0", "storms": 5801,
             "largest_object_share": 0.003, "rain_captured": 0.955,
             "from_findings": "Finding 15"},
        ],
        "measured_percolation_full_archive": {
            "min": float(perc.min()), "max": float(perc.max()),
            "median": float(np.median(perc)),
            "note": ("param_percolation_share from every catalogue chunk, "
                     "1998-2025. This one is measured here, not quoted."),
        },
    })


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--product", default="final")
    ap.add_argument("--prominence", type=float, default=4.0)
    ap.add_argument("--event-start", default="2019-12-30",
                    help="first day of the window both maps show")
    ap.add_argument("--event-end", default="2020-01-02",
                    help="last day, inclusive")
    ap.add_argument("--tracks-n", type=int, default=400,
                    help="cap on storms drawn on the domain map")
    a = ap.parse_args()

    files = catalogue_files(a.product, a.prominence)
    print(f"{len(files)} catalogues, {a.product}, h={a.prominence:g}")

    rp = DATA_PROCESSED / "regions_k3.parquet"
    regions = pd.read_parquet(rp) if rp.exists() else None
    if regions is not None:
        regions = regions[["glat", "glon", "region"]]

    print("  scanning:")
    monthly, annual, regional, vols, ints, perc, params = scan(files, regions)
    if len(params) > 1:
        raise SystemExit(f"catalogues disagree on parameters: {params}. "
                         "Rebuild the odd ones out before exporting.")

    # One scale for the whole page. n_years counts months, so the 9-month 2025 does
    # not inflate the record length and depress the exceedance thresholds.
    n_years = float(annual.months.sum() / 12.0)
    sc = severity.fit(pd.DataFrame({"total_volume_km3": vols.astype("float64"),
                                    "max_intensity_mm_hr": ints.astype("float64")}),
                      n_years=n_years, exclude_truncated=False)

    print("\nwriting:")
    export_summary(annual, perc, params, vols, files)
    export_method(perc, files)
    export_seasonal(monthly, files)
    export_annual(annual, files)
    export_regional(regional, files)
    export_concentration(vols, files)
    export_severity(sc, vols, ints, files)
    export_sweep()
    export_diurnal()
    export_leadtime()
    export_families()
    export_geography()
    # One call, both maps: export_event segments the window once and cuts the
    # domain view and the Jakarta view from the same labels.
    export_event(a.event_start, f"{a.event_end} 23:59", JAKARTA_BBOX,
                 a.prominence, a.product, sc, places=JAKARTA_PLACES,
                 label="Jakarta, New Year 2020", domain_n=a.tracks_n)
    export_rank_context(vols, a.event_start, f"{a.event_end} 23:59",
                        JAKARTA_BBOX, a.product, a.prominence)
    export_accumulation(a.event_start, a.event_end, a.product)
    export_family_severity(a.event_start, f"{a.event_end} 23:59", JAKARTA_BBOX)

    total = sum(p.stat().st_size for p in SITE_DATA.glob("*.json")) / 1024
    print(f"\n{total:.0f} KB total in {SITE_DATA.relative_to(REPO)}")


if __name__ == "__main__":
    main()
