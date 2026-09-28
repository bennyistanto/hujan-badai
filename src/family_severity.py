"""Severity at the level of the EVENT, not the individual convective cell.

Why this exists
---------------
`severity.py` ranks storm objects. At h = 4.0 a storm object is a convective cell
lasting about 4 hours, and a flood is not caused by one cell. Tested directly against
the Jakarta flood of 2020-01-01 (docs/findings.md Finding 57): all 137 storm objects
over the city during the flood fell in the lowest of the nine severity classes, which
is true but carries almost no information, because 99.8% of every storm ever
catalogued falls there too. Measured as percentiles instead those same storms sat in
the top few percent. The class was the wrong instrument, not the storms.

This module applies the same nine-class scheme to storm FAMILIES, the linked
multi-hour to multi-day events built by `families.py`. An event is the unit a flood
responds to, and it is the unit a warning would be issued for.

What changes, and what does not
-------------------------------
The 3x3 structure is unchanged, so a family class and a storm class mean structurally
the same thing and the two can be compared. What changes is the population being
ranked, and therefore what a class boundary picks out.

One real gain: a family-level return period can be honest where a per-storm one
cannot. Finding 38 showed a per-storm return period is dominated by how finely the
field was partitioned rather than by the weather, because there are 449,000 storms a
year. For the largest events there are few enough per year that "exceeded about once
in N years" means something, as long as N stays inside the record length.

    python src/family_severity.py
    python src/family_severity.py --event 2019-12-30 2020-01-02 --bbox -7.8 -5.2 104.8 108.6
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, PRODUCT  # noqa: E402
import severity  # noqa: E402

DEFAULT_GAP_H = 3.0
DEFAULT_DIST_KM = 50.0

# Exceedance rates for the family bands, in events per year.
#
# NOT the storm scale's (500, 50). Those were chosen against a population of 449,000
# storms a year and, applied to families, would again leave almost everything in the
# lowest class. Families are only modestly rarer than storms, because most of them are
# a single unlinked cell: the median family holds one storm. So the rates here are set
# to pick out an operationally meaningful tail of EVENTS, checked against what the
# population actually does in `report()` rather than assumed.
FAMILY_RATE_BANDS = (200.0, 20.0)


def family_file(product: str = None, h: float = 4.0,
                gap_h: float = DEFAULT_GAP_H,
                dist_km: float = DEFAULT_DIST_KM) -> Path:
    return DATA_PROCESSED / (f"families_{product or PRODUCT}_h{h:g}"
                             f"_g{gap_h:g}_d{dist_km:g}.parquet")


def load(product: str = None, h: float = 4.0, **kw) -> pd.DataFrame:
    f = family_file(product, h, **kw)
    if not f.exists():
        raise SystemExit(
            f"no family catalogue at {f}.\n"
            f"Build it first:  python src/families.py --year 1998 2025")
    d = pd.read_parquet(f)
    d["start"] = pd.to_datetime(d.start)
    d["end"] = pd.to_datetime(d.end)
    return d


def n_years(fam: pd.DataFrame) -> float:
    """Record length in years, counted from distinct year-months present.

    Counting calendar years would call 2025 a full year. It holds nine months,
    because IMERG Final V07 ends 2025-09-30, and treating it as twelve would stretch
    the record and depress every exceedance threshold.
    """
    return float(fam.groupby(["year", "month"]).ngroups / 12.0)


def fit(fam: pd.DataFrame, rate_bands=FAMILY_RATE_BANDS) -> severity.SeverityScale:
    """A severity scale whose reference population is events, not cells."""
    ref = fam.rename(columns={"volume_km3": "total_volume_km3"})
    return severity.fit(ref, n_years=n_years(fam), rate_bands=rate_bands,
                        exclude_truncated=False, region="all")


def classify(fam: pd.DataFrame, sc: severity.SeverityScale) -> pd.DataFrame:
    out = sc.classify(fam.volume_km3.to_numpy(),
                      fam.max_intensity_mm_hr.to_numpy())
    return fam.reset_index(drop=True).join(out)


def percentile_of(fam: pd.DataFrame, values) -> np.ndarray:
    """Percentile of each value within the family volume distribution.

    Always reported alongside the class, because Finding 57 is precisely that a class
    alone misleads when one class holds most of the population.
    """
    ref = np.sort(fam.volume_km3.to_numpy())
    return np.searchsorted(ref, np.asarray(values)) / ref.size * 100.0


def event_families(fam: pd.DataFrame, t0, t1, bbox=None) -> pd.DataFrame:
    """Families overlapping a time window, optionally inside a bounding box.

    Overlap rather than containment: an event running past the end of the window is
    still that event. `bbox` is (lat_min, lat_max, lon_min, lon_max) and tests the
    family's mean centroid.
    """
    t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
    d = fam[(fam.start <= t1) & (fam.end >= t0)]
    if bbox is not None:
        a0, a1, o0, o1 = bbox
        d = d[d.lat.between(a0, a1) & d.lon.between(o0, o1)]
    return d.sort_values("volume_km3", ascending=False)


def rank_event(fam: pd.DataFrame, t0, t1, bbox=None, sc=None) -> dict:
    """Rank one event's largest family against the whole family population.

    Returns the pieces a caller needs to state the result honestly: the class, the
    percentile, the rank, and a return period that is flagged when it exceeds the
    record length and therefore cannot be supported.
    """
    sc = sc or fit(fam)
    ev = event_families(fam, t0, t1, bbox)
    if ev.empty:
        return {"n_families": 0}

    ny = n_years(fam)
    ref = np.sort(fam.volume_km3.to_numpy())
    n = ref.size
    top = ev.iloc[0]
    k = int(n - np.searchsorted(ref, top.volume_km3))     # how many are bigger or equal
    k = max(k, 1)
    T = ny / k

    cls = sc.classify([top.volume_km3], [top.max_intensity_mm_hr])
    return {
        "n_families": int(len(ev)),
        "combined_volume_km3": float(ev.volume_km3.sum()),
        "largest": {
            "family_uid": str(top.family_uid),
            "start": top.start.isoformat(),
            "end": top.end.isoformat(),
            "volume_km3": float(top.volume_km3),
            "max_intensity_mm_hr": float(top.max_intensity_mm_hr),
            "n_storms": int(top.n_storms),
            "age_h": float(top.age_h),
            "lat": float(top.lat), "lon": float(top.lon),
            "severity": str(cls.severity.iloc[0]),
            "severity_index": int(cls.severity_index.iloc[0]),
            "percentile": float(percentile_of(fam, [top.volume_km3])[0]),
            "rank": k,
            "exceeded_per_year": float(k / ny),
            "return_period_years": float(T),
            # A return period has to be inside the record to be evidenced AND at
            # least about a year to be worth stating. An earlier version checked
            # only the upper bound, so it called "1 in 0.001 years" supported: true
            # in the sense that the record covers it, and meaningless as a statement.
            "return_period_supported": bool(1.0 <= T <= ny),
        },
        "n_reference": int(n),
        "n_years": ny,
    }


def area_daily_volume(bbox, product: str = None, h: float = 4.0) -> pd.Series:
    """Catalogued storm volume falling inside `bbox` each day, 1998 to 2025.

    Attributes each storm to the day and place of its volume-weighted centroid. That
    is an approximation for a storm straddling the box edge, and it is the same
    approximation the regional breakdown uses, so the two stay consistent.
    """
    a0, a1, o0, o1 = bbox
    cols = ["wcentroid_lat", "wcentroid_lon", "wcentroid_time", "total_volume_km3"]
    out = []
    for f in sorted(DATA_PROCESSED.glob(
            f"catalogue_{product or PRODUCT}_*_h{h:g}.parquet")):
        d = pd.read_parquet(f, columns=cols)
        d = d[d.wcentroid_lat.between(a0, a1) & d.wcentroid_lon.between(o0, o1)]
        if d.empty:
            continue
        day = pd.to_datetime(d.wcentroid_time).dt.floor("D")
        out.append(d.groupby(day).total_volume_km3.sum())
    if not out:
        return pd.Series(dtype=float)
    s = pd.concat(out).groupby(level=0).sum().sort_index()
    # Reindex onto every calendar day so a dry day is a zero, not a gap. Without this
    # a rolling sum would silently span the gap and overstate the total.
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"),
                     fill_value=0.0)


def rank_area_event(series: pd.Series, t0, t1) -> dict:
    """Rank one multi-day total for one area against the record, by annual maxima.

    Why this exists
    ---------------
    Ranking the event's largest storm, or its largest family, does not work: measured
    on the Jakarta flood, both land in the lowest severity class and at about the
    99.6th percentile, because the strict linking that stops families percolating
    also stops them assembling a whole flood event (docs/findings.md Finding 60). The
    flood-relevant quantity is not the size of any one object. It is how much rain
    fell over an area in a window, which is what this measures.

    Annual maxima rather than every rolling window, because adjacent windows overlap
    and would count one event several times. One value per year gives a clean
    plotting position and a return period that can be stated.
    """
    t0, t1 = pd.Timestamp(t0).floor("D"), pd.Timestamp(t1).floor("D")
    ndays = int((t1 - t0).days) + 1
    roll = series.rolling(f"{ndays}D").sum()

    value = float(series.loc[t0:t1].sum())
    annual = roll.groupby(roll.index.year).max()
    # A partial year cannot be compared with full ones: its maximum is drawn from
    # fewer windows, so including it biases the ranking.
    full = [y for y in annual.index
            if series.loc[str(y)].size >= 365 - 1]
    annual = annual.loc[full]

    n = int(annual.size)
    bigger = int((annual > value).sum())
    rank = bigger + 1
    # Weibull plotting position, the standard choice for annual maxima.
    T = (n + 1) / rank

    # Three outcomes, because the arithmetic alone will happily produce a number for
    # a value that is smaller than every annual maximum. A first version reported
    # "1 in 1.0 years" for exactly that case, which reads like a finding and is not:
    # it means the window did not reach the typical yearly peak for this area.
    is_record = rank == 1
    below_typical = rank > n / 2
    return {
        "window_days": ndays,
        "value_km3": value,
        "n_years_compared": n,
        "rank": rank,
        "return_period_years": float(T),
        "is_record": bool(is_record),
        "below_typical_year": bool(below_typical),
        "return_period_supported": bool(not is_record and not below_typical),
        "verdict": ("highest in the record" if is_record else
                    "below the typical annual maximum" if below_typical else
                    f"about 1 in {T:.0f} years"),
        "annual_maxima": [{"year": int(y), "value_km3": float(v)}
                          for y, v in annual.items()],
        "median_annual_max_km3": float(annual.median()),
        "ratio_to_median": float(value / annual.median()) if annual.median() else None,
    }


def report(fam: pd.DataFrame, sc: severity.SeverityScale) -> pd.DataFrame:
    """Class occupancy. The check that the bands actually divide the population."""
    c = classify(fam, sc)
    t = (c.groupby("severity", observed=True)
         .agg(families=("volume_km3", "size"),
              volume_km3=("volume_km3", "sum"),
              median_storms=("n_storms", "median"),
              median_age_h=("age_h", "median"))
         .reindex(severity.CLASS_NAMES))
    t["families"] = t.families.fillna(0).astype(int)
    t["share_pct"] = t.families / t.families.sum() * 100.0
    t["volume_share_pct"] = t.volume_km3 / t.volume_km3.sum() * 100.0
    t["per_year"] = t.families / n_years(fam)
    return t


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--product", default=None)
    ap.add_argument("--h", type=float, default=4.0)
    ap.add_argument("--gap-h", type=float, default=DEFAULT_GAP_H)
    ap.add_argument("--dist-km", type=float, default=DEFAULT_DIST_KM)
    ap.add_argument("--rate-bands", type=float, nargs=2, default=FAMILY_RATE_BANDS,
                    metavar=("COMMON", "RARE"),
                    help="band edges as events per year")
    ap.add_argument("--event", nargs=2, metavar=("START", "END"),
                    help="rank one event, e.g. --event 2019-12-30 2020-01-02")
    ap.add_argument("--bbox", type=float, nargs=4, default=None,
                    metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"))
    a = ap.parse_args()

    fam = load(a.product, a.h, gap_h=a.gap_h, dist_km=a.dist_km)
    ny = n_years(fam)
    print(f"{len(fam):,} families over {ny:.2f} years "
          f"({len(fam)/ny:,.0f} a year), h={a.h:g}, "
          f"linked at {a.gap_h:g} h / {a.dist_km:g} km")
    print(f"largest family holds "
          f"{100*fam.volume_km3.max()/fam.volume_km3.sum():.3f}% of the rain "
          f"(percolation check; above 20% would mean the linking merged the domain)")

    sc = fit(fam, tuple(a.rate_bands))
    print()
    print(sc.describe())

    print("\nclass occupancy:")
    t = report(fam, sc)
    print(t.to_string(float_format=lambda x: f"{x:,.2f}"))

    lowest = t.loc["very low", "share_pct"]
    print(f"\nlowest class holds {lowest:.1f}% of families.")
    if lowest > 95:
        print("  That is still nearly everything. The bands are too extreme for this")
        print("  population: widen them, or quote percentiles instead of classes.")

    if a.event:
        print("\n" + "=" * 70)
        bbox = tuple(a.bbox) if a.bbox else None
        r = rank_event(fam, a.event[0], a.event[1], bbox, sc)
        if not r["n_families"]:
            print("no families in that window")
            return
        g = r["largest"]
        print(f"event {a.event[0]} to {a.event[1]}"
              + (f", bbox {bbox}" if bbox else ""))
        print(f"  {r['n_families']:,} families, "
              f"{r['combined_volume_km3']:.2f} km3 combined")
        print(f"\n  largest single family:")
        print(f"    {g['start']} to {g['end']}  ({g['age_h']:.1f} h, "
              f"{g['n_storms']} storms)")
        print(f"    volume        {g['volume_km3']:.3f} km3")
        print(f"    peak          {g['max_intensity_mm_hr']:.1f} mm/hr")
        print(f"    severity      {g['severity']}")
        print(f"    percentile    {g['percentile']:.4f}")
        print(f"    rank          {g['rank']:,} of {r['n_reference']:,}")
        rp = g["return_period_years"]
        if g["return_period_supported"]:
            print(f"    return period about 1 in {rp:.1f} years "
                  f"(record is {r['n_years']:.1f} yr, so this is supported)")
        else:
            print(f"    return period would be 1 in {rp:.1f} years, which EXCEEDS "
                  f"the {r['n_years']:.1f} yr record and is not supported")


if __name__ == "__main__":
    main()
