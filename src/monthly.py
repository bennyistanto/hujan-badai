"""Monthly rain totals over the AOI, streamed one day at a time.

Used to pick genuinely wet and dry months rather than assuming them. Indonesia has
several rainfall regimes with opposing seasonality (monsoonal over Java and Nusa
Tenggara, semi-annual near the equator, anti-monsoonal over parts of Maluku), so a
domain-wide wettest month is a measurement, not a given.

    python src/monthly.py --year 2020
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DT_HOURS  # noqa: E402
from imerg_io import cell_area_m2, load_range  # noqa: E402


def daily_totals(year: int, source="local", product=None) -> pd.DataFrame:
    """Domain rain volume (km3) and wet fraction per day. Streams, never holds
    more than one day, so it is safe to run over a whole year."""
    rows = []
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    area = None
    for i, d in enumerate(days):
        ds = d.strftime("%Y-%m-%d")
        da = load_range(ds, ds, source=source, product=product, progress=False)
        R = np.nan_to_num(da.values, nan=0.0)
        if area is None:
            area = cell_area_m2(da.lat.values)[None, :, None]
        vol = float((R * DT_HOURS / 1000.0 * area).sum() / 1e9)
        rows.append({"date": d, "month": d.month,
                     "volume_km3": vol,
                     "wet_frac_1mm": float((R >= 1.0).mean()),
                     "max_mm_hr": float(R.max())})
        if (i + 1) % 30 == 0:
            print(f"  {i+1}/{len(days)} days", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--source", default="local")
    ap.add_argument("--product", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    df = daily_totals(a.year, a.source, a.product)
    m = df.groupby("month").agg(volume_km3=("volume_km3", "sum"),
                                mean_daily_km3=("volume_km3", "mean"),
                                wet_frac=("wet_frac_1mm", "mean"),
                                max_mm_hr=("max_mm_hr", "max"),
                                days=("volume_km3", "size"))
    m["share_of_year"] = m.volume_km3 / m.volume_km3.sum()
    pd.set_option("display.width", 160)
    print(f"\nAOI-wide monthly totals, {a.year}\n")
    print(m.round(4).to_string())
    print(f"\nwettest month: {int(m.volume_km3.idxmax())} "
          f"({m.volume_km3.max():.0f} km3)")
    print(f"driest  month: {int(m.volume_km3.idxmin())} "
          f"({m.volume_km3.min():.0f} km3)")
    print(f"wet/dry ratio : {m.volume_km3.max()/m.volume_km3.min():.2f}x")
    if a.out:
        df.to_csv(a.out, index=False)
        print(f"\ndaily series -> {a.out}")


if __name__ == "__main__":
    main()
