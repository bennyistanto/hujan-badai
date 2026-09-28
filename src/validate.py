"""Archive integrity check. Run this before any long job.

Opening 10,000 NetCDF files is slow, but a corrupt or truncated download is
visible in the first 8 bytes, so the sweep is cheap:

    NetCDF-4 / HDF5   \\x89HDF\\r\\n\\x1a\\n
    NetCDF-3 classic  CDF\\x01 or CDF\\x02

Anything else is not a NetCDF file, whatever its extension or size. File size is
**not** a usable signal here: dry days compress to a third of a wet day's size and
open perfectly well.

    .\\run.ps1 src\\validate.py --product final
    .\\run.ps1 src\\validate.py --product final --deep      # also open each file
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, PRODUCT, STEPS_PER_DAY  # noqa: E402
from sources import LocalSource  # noqa: E402

HDF5 = b"\x89HDF\r\n\x1a\n"
NC3 = (b"CDF\x01", b"CDF\x02")


def magic_ok(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head.startswith(HDF5) or head[:4] in NC3


def bad_days_file(product: str) -> Path:
    return DATA_PROCESSED / f"archive_bad_days_{product}.json"


def known_bad(product: str) -> set:
    """Days a previous validate run found unreadable. Empty if never run.

    Cached because the header sweep takes about 13 minutes against Google Drive,
    which is far too slow to repeat at the start of every job.
    """
    import json
    f = bad_days_file(product)
    if not f.exists():
        return set()
    return {dt.date.fromisoformat(x) for x in json.loads(f.read_text())["bad_days"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", default=None)
    ap.add_argument("--deep", action="store_true",
                    help="also open every readable file and check its shape")
    ap.add_argument("--list-all", action="store_true")
    a = ap.parse_args()

    src = LocalSource(product=a.product or PRODUCT)
    idx = src.index()
    days = sorted(idx)
    print(f"archive : {src.archive}")
    print(f"product : {src.product}")
    print(f"indexed : {len(days):,} days, {days[0]} .. {days[-1]}\n")

    span = (days[-1] - days[0]).days + 1
    have = set(days)
    gaps = [days[0] + dt.timedelta(days=i) for i in range(span)
            if days[0] + dt.timedelta(days=i) not in have]
    print(f"calendar gaps : {len(gaps)}")
    if gaps:
        print(f"  first few: {gaps[:10]}")

    t = time.time()
    bad = [d for d in days if not magic_ok(idx[d])]
    print(f"\nheader scan   : {len(days):,} files in {time.time()-t:.1f}s")
    print(f"NOT NetCDF    : {len(bad)}")
    if bad:
        by_month = {}
        for d in bad:
            by_month.setdefault((d.year, d.month), []).append(d)
        for (y, m), ds in sorted(by_month.items()):
            print(f"  {y}-{m:02d}: {len(ds):>4} bad day(s)"
                  + (f"  {[str(x) for x in ds]}" if a.list_all else
                     f"  first {ds[0]}, last {ds[-1]}"))

    if a.deep:
        import xarray as xr
        t, shape_bad, open_bad = time.time(), [], []
        good = [d for d in days if d not in set(bad)]
        for i, d in enumerate(good, 1):
            try:
                with xr.open_dataset(idx[d]) as ds:
                    if ds.sizes.get("time") != STEPS_PER_DAY:
                        shape_bad.append((d, dict(ds.sizes)))
            except Exception:
                open_bad.append(d)
            if i % 1000 == 0:
                print(f"  deep {i:,}/{len(good):,} ...", flush=True)
        print(f"\ndeep scan     : {len(good):,} files in {time.time()-t:.0f}s")
        print(f"fail to open  : {len(open_bad)}  {open_bad[:8]}")
        print(f"wrong n steps : {len(shape_bad)}  {shape_bad[:5]}")
        bad = sorted(set(bad) | set(open_bad))

    import json
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    bf = bad_days_file(src.product)
    bf.write_text(json.dumps({
        "product": src.product, "archive": str(src.archive),
        "checked": dt.datetime.now().isoformat(timespec="seconds"),
        "deep": bool(a.deep), "n_indexed": len(days),
        "bad_days": [str(d) for d in bad]}, indent=2), encoding="utf-8")
    print(f"\nwrote {bf}")

    usable = [d for d in days if d not in set(bad)]
    print(f"\nusable days   : {len(usable):,} of {len(days):,} "
          f"({100*len(usable)/len(days):.2f}%)")
    if bad:
        print("\nThese days will abort a run: load_range raises on a missing or")
        print("unreadable day rather than leaving a silent gap. Re-download them,")
        print("or restrict the run to whole months that are clean.")
        years = sorted({d.year for d in bad})
        print(f"affected years: {years}")


if __name__ == "__main__":
    main()
