"""Import a small official FGIS/FSNB norm overlay into cache raw parquet.

This is intentionally narrower than ``gesn_bulk_import``.  Use it when the
runtime already has a broad legacy base, but a specific normative family needs a
typed overlay that preserves ``base_type``/``norm_key`` (for example GESNm10 for
structured cabling and optical fiber work).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from tools.gesn_pdf_import import build_parquet, parse_fgis_json

API = "https://fgiscs.minstroyrf.ru/api/FullTextSearch/SearchEstimatedRates?search="
DEFAULT_OUT = Path("storage/cache/gesn_fgis/gesn2022_overlay_raw.parquet")

PRESETS: dict[str, tuple[str, ...]] = {
    # GESNm10 candidates used by SCS/telecom estimates.  These are navigation
    # and trace-enabling overlays; the model still chooses applicability.
    "sks": (
        "10-01-014-01",  # subscriber / connecting line cross blocks
        "10-01-052-07",  # cross-connection in cabinet/cross
        "10-02-050-01",  # row frame / stative assembly
        "10-02-051-03",  # cable jumpers laid in cable channel
        "10-03-031-01",  # digital PBX cross, port-based telecom proxy
        "10-06-016-06",  # optical cable end preparation / termination
        "10-06-036-07",  # low-current screened steel pipe family
        "10-06-048-06",  # optical cable laying
        "10-06-057-04",  # optical cable stripping family
        "10-06-058-01",  # optical fiber splicing
        "10-06-059-05",  # optical measurements, 24 fibers
        "10-06-060-15",  # optical cross, 24 fibers
        "10-06-062-02",  # terminal measurements, two wavelengths
        "10-06-065-05",  # mounted optical section measurements, 24 fibers
        "10-06-068-17",  # object handover / acceptance tests
    ),
}


def _fetch_raw(search: str, *, timeout: int) -> list[dict[str, Any]]:
    url = API + urllib.parse.quote(str(search), safe="")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, list):
        return data
    return data.get("data") or data.get("items") or []


def import_overlay(
    codes: Iterable[str],
    *,
    out_path: str | Path = DEFAULT_OUT,
    timeout: int = 60,
    rate: float = 0.5,
    log: Any = sys.stderr,
) -> dict[str, Any]:
    """Fetch exact FGIS searches, parse official norm resources and append them.

    The function does not select estimate works.  It only makes official norm
    rows available to the calculator/provenance layer.
    """
    rows: list[dict[str, Any]] = []
    stats = {"codes": 0, "records": 0, "rows": 0, "errors": 0}
    delay = 1.0 / rate if rate > 0 else 0.0
    seen: set[str] = set()
    for code in codes:
        code = str(code or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        try:
            records = _fetch_raw(code, timeout=timeout)
            parsed = parse_fgis_json(records)
        except Exception as exc:  # noqa: BLE001 - network/FGIS JSON should not stop all imports
            stats["errors"] += 1
            print(f"[ERR ] {code}: {exc}", file=log, flush=True)
            if delay:
                time.sleep(delay)
            continue
        rows.extend(parsed)
        stats["codes"] += 1
        stats["records"] += len(records)
        stats["rows"] += len(parsed)
        base_types = ",".join(sorted({str(r.get("base_type") or "") for r in parsed if r.get("base_type")}))
        norm_count = len({r.get("norm_key") or r.get("norm_code") for r in parsed if r.get("norm_code")})
        print(
            f"[ok  ] {code}: records={len(records)} rows={len(parsed)} "
            f"norms={norm_count} base={base_types or '-'}",
            file=log,
            flush=True,
        )
        if delay:
            time.sleep(delay)
    if not rows:
        stats["parquet"] = str(out_path)
        return stats
    summary = build_parquet(rows, out_path, append=True)
    stats.update(summary)
    return stats


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import official FGIS norm overlay into gesn2022_v2.parquet")
    parser.add_argument("codes", nargs="*", help="Exact norm/table codes to fetch, e.g. 10-06-058-01")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Known code preset")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"Overlay Parquet path (default: {DEFAULT_OUT})")
    parser.add_argument("--timeout", type=int, default=60, help="Network timeout per FGIS request")
    parser.add_argument("--rate", type=float, default=0.5, help="Requests per second")
    args = parser.parse_args(list(argv) if argv is not None else None)

    codes: list[str] = []
    if args.preset:
        codes.extend(PRESETS[args.preset])
    codes.extend(args.codes)
    if not codes:
        parser.error("pass codes or --preset")
    stats = import_overlay(codes, out_path=args.out, timeout=args.timeout, rate=args.rate)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats.get("errors", 0) == 0 and stats.get("rows", 0) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
