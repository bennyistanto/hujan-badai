"""Storm severity from a reference population.

Structure follows the SERVIR Storm Tracker manual, which describes nine severity
levels "using the relationship between the return period of the Maximum intensity
and the total volume of the storm event", citing Laverde-Barajas et al. (2020).

**The thresholds here are ours.** That poster (in references/paper/) classifies
storms only into short-lived and long-lived by k-means; it contains no severity
levels, no return-period axes and no bin edges. Neither does either other paper.
So this module adopts the published *structure* and cites the concept, but every
boundary below is defined from our own reference population. Do not describe the
output as "the Laverde-Barajas classification".

Percentile or return period
---------------------------
Both axes are ranked against a reference catalogue. What the rank *means* depends
entirely on how long that catalogue is:

- under ~10 years: percentile only. A percentile says "big for this record". It is
  not a return period and must never be labelled as one.
- 10 years or more: empirical return period, T = (N + 1) / rank in years, honest to
  roughly N years. Beyond the record, a fitted GEV or GPD is required and this
  module does not do that.

`SeverityScale.basis` records which of the two applies, and it is carried into
every classified row so a figure caption cannot get it wrong.

Why these two axes are the right ones
-------------------------------------
Volume and max intensity are the quantities measured to be robust against the
segmentation prominence h: an 8x change in h moves captured volume 1.3-1.4% and
barely touches a voxel-wise maximum, while the storm count moves 8.3x
(docs/sweep-prominence.md). A severity scheme built on counts would inherit the
instability; built on these two it largely does not.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MIN_YEARS_FOR_RETURN_PERIOD = 10

# Row-major, increasing severity. Rows are volume bands, columns intensity bands.
#                    intensity: common      uncommon      rare
CLASS_MATRIX = [   # volume common
                   ["very low",   "low",        "moderate"],
                   # volume uncommon
                   ["medium",     "heavy",      "very heavy"],
                   # volume rare
                   ["intense",    "severe",     "extreme"]]
CLASS_NAMES = [n for row in CLASS_MATRIX for n in row]      # 9, ordered

# Band edges as percentiles of the reference population. Used only when the record
# is too short for return periods.
DEFAULT_BANDS = (90.0, 99.0)        # common < p90 <= uncommon < p99 <= rare

# Band edges as EXCEEDANCE RATES in storms per year, not as return periods.
#
# Measured on the 28-year catalogue (docs/findings.md Finding 38): a per-storm
# return period is dominated by how finely the field is partitioned, not by the
# weather. A 1-in-1-year storm is simply the 28th largest in a 28-year record
# whatever the population size, so bands at T = 0.01 and 1 year put 99.96% of
# storms in the lowest class and leave three of the nine classes empty.
#
# Stating the band as "exceeded about N times a year" is the same arithmetic
# (T = 1/N) but it is honest about what it measures and it produces usable classes.
# Quote the rate, and the prominence that produced it, with any severity figure.
DEFAULT_RATE_BANDS = (500.0, 50.0)  # common | >=500/yr uncommon | >=50/yr rare


@dataclass
class SeverityScale:
    vol_sorted: np.ndarray
    int_sorted: np.ndarray
    n_years: float
    bands: tuple
    vol_edges: tuple
    int_edges: tuple
    region: str = "all"
    band_kind: str = "percentile"      # "percentile" or "return_period_years"

    @property
    def basis(self) -> str:
        return ("return_period" if self.n_years >= MIN_YEARS_FOR_RETURN_PERIOD
                else "percentile")

    @property
    def max_honest_T(self) -> float:
        return float(self.n_years)

    def describe(self) -> str:
        b = self.basis
        s = (f"SeverityScale[{self.region}] n={self.vol_sorted.size:,} storms over "
             f"{self.n_years:.1f} yr, basis={b}")
        if b == "percentile":
            s += "  (record too short for return periods; percentile only)"
        else:
            s += f", honest to T<={self.max_honest_T:.0f} yr"
        s += (f"\n  volume band edges    p{self.bands[0]:g}={self.vol_edges[0]:.4f} "
              f"p{self.bands[1]:g}={self.vol_edges[1]:.4f} km3"
              f"\n  intensity band edges p{self.bands[0]:g}={self.int_edges[0]:.1f} "
              f"p{self.bands[1]:g}={self.int_edges[1]:.1f} mm/hr")
        return s

    # -- lookups ----------------------------------------------------------
    def _pct(self, arr, v):
        return np.searchsorted(arr, np.asarray(v), side="right") / arr.size * 100.0

    def percentiles(self, volume, intensity):
        return self._pct(self.vol_sorted, volume), self._pct(self.int_sorted, intensity)

    def return_periods(self, volume, intensity):
        """Empirical T in years. NaN when the record is too short to mean anything."""
        if self.basis != "return_period":
            n = np.size(volume)
            return np.full(n, np.nan), np.full(n, np.nan)
        n = self.vol_sorted.size
        # How many storms in the record exceeded this one.
        rv = n - np.searchsorted(self.vol_sorted, np.asarray(volume), side="right")
        ri = n - np.searchsorted(self.int_sorted, np.asarray(intensity), side="right")
        # Exceedance rate is rv / n_years per year, so T = n_years / rv. The record
        # maximum has rv = 0, which would divide by zero, so floor the count at 1:
        # T then saturates at the record length, which is the honest ceiling anyway.
        return (self.n_years / np.maximum(rv, 1),
                self.n_years / np.maximum(ri, 1))

    def bands_of(self, volume, intensity):
        vb = np.digitize(volume, self.vol_edges)
        ib = np.digitize(intensity, self.int_edges)
        return vb, ib

    def threshold_for_T(self, T: float) -> tuple[float, float]:
        """Volume and intensity exceeded once every T years.

        A T-year event is exceeded k = n_years / T times in the record, so the
        threshold is the k-th largest value. It is NOT a fraction of the storm
        count: dividing by the population makes thresholds fall as T rises.
        """
        return self.threshold_for_rate(1.0 / T)

    def threshold_for_rate(self, per_year: float) -> tuple[float, float]:
        """Volume and intensity exceeded about `per_year` times a year."""
        k = max(int(round(per_year * self.n_years)), 1)
        k = min(k, self.vol_sorted.size)
        return float(self.vol_sorted[-k]), float(self.int_sorted[-k])

    def classify(self, volume, intensity) -> pd.DataFrame:
        volume = np.asarray(volume, dtype=float)
        intensity = np.asarray(intensity, dtype=float)
        vb, ib = self.bands_of(volume, intensity)
        idx = vb * 3 + ib
        pv, pi = self.percentiles(volume, intensity)
        tv, ti = self.return_periods(volume, intensity)
        return pd.DataFrame({
            "severity": [CLASS_NAMES[i] for i in idx],
            "severity_index": idx,                 # 0..8
            "vol_band": vb, "int_band": ib,
            "vol_pct": pv, "int_pct": pi,
            "vol_T_years": tv, "int_T_years": ti,
            "severity_basis": self.basis,
        })


def fit(ref: pd.DataFrame, n_years: float, bands=None,
        region: str = "all", exclude_truncated: bool = True,
        rate_bands=DEFAULT_RATE_BANDS) -> SeverityScale:
    """Build a scale from a reference catalogue.

    With a record of at least MIN_YEARS_FOR_RETURN_PERIOD, band edges are set from
    `rate_bands` (exceedances per year). Below that they fall back to percentiles
    from `bands`, and the scale reports `basis == "percentile"` so nothing
    downstream can call the result a return period.

    Truncated storms are excluded by default. Their volume and duration are
    censored by a domain or window edge, so including them biases the
    distribution low and inflates everyone else's rank.
    """
    d = ref
    if exclude_truncated and "truncated_time" in d.columns:
        d = d[~(d.truncated_time | d.truncated_space)]
    v = np.sort(d.total_volume_km3.to_numpy())
    i = np.sort(d.max_intensity_mm_hr.to_numpy())
    sc = SeverityScale(
        vol_sorted=v, int_sorted=i, n_years=float(n_years),
        bands=tuple(bands or DEFAULT_BANDS), vol_edges=(0.0, 0.0),
        int_edges=(0.0, 0.0), region=region)

    if sc.basis == "return_period" and bands is None:
        lo_v, lo_i = sc.threshold_for_rate(rate_bands[0])
        hi_v, hi_i = sc.threshold_for_rate(rate_bands[1])
        sc.vol_edges, sc.int_edges = (lo_v, hi_v), (lo_i, hi_i)
        sc.bands = tuple(rate_bands)
        sc.band_kind = "per_year"
    else:
        b = bands or DEFAULT_BANDS
        sc.vol_edges = tuple(np.percentile(v, b))
        sc.int_edges = tuple(np.percentile(i, b))
        sc.bands = tuple(b)
        sc.band_kind = "percentile"
    return sc


def contribution_curve(df: pd.DataFrame, fracs=(0.01, 0.05, 0.10, 0.13, 0.20, 0.50)):
    """What share of total rain comes from the largest X% of storms.

    Built to test the AGU 2020 poster's headline for the Lower Mekong: long-lived
    storms were 13% of the population and contributed more than 97% of monsoon
    rainfall. Running the same calculation here is one of the few checkable
    comparisons this project has against published work.
    """
    v = np.sort(df.total_volume_km3.to_numpy())[::-1]
    tot = v.sum()
    cum = np.cumsum(v) / tot
    n = v.size
    rows = [{"top_frac": f, "n_storms": int(round(f * n)),
             "volume_share": float(cum[min(int(round(f * n)), n) - 1])}
            for f in fracs]
    out = pd.DataFrame(rows)
    # inverse: what fraction of storms is needed to reach a share of the rain
    inv = {s: float(np.searchsorted(cum, s) + 1) / n for s in (0.5, 0.9, 0.97, 0.99)}
    return out, inv
