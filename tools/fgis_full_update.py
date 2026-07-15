"""Download every public estimating source LES can obtain from FGIS CS.

The default operator job is intentionally bounded to the latest published
period of every price zone plus the complete GESN update.  Historical periods
are discoverable in the persisted catalogue and may be downloaded explicitly
with ``--all-periods``; doing that by default would create hundreds of large
books and is not needed for a current estimate.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from proxy.services import fgis_price_fetch_service as price_fetch
from tools import gesn_update_from_fgis

DEFAULT_STATUS = Path("storage/jobs/fgis_full_update_status.json")
DEFAULT_CATALOG = Path("data/price_base/fgis_catalog.json")
DEFAULT_MANIFEST = Path("data/price_base/fgis_latest_manifest.json")


def _slug(subject: str, quarter: str) -> str:
    """Build a portable pricebook stem without depending on optional CLI tools."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya", " ": "-", "-": "-",
    }
    base = "".join(translit.get(char, char if char.isascii() and char.isalnum() else "") for char in subject.casefold())
    base = re.sub(r"-+", "-", base).strip("-") or "region"
    match = re.search(r"(\d)\s*квартал\D*(\d{4})", quarter.casefold())
    period = f"{match.group(1)}kv{match.group(2)}" if match else re.sub(r"\W+", "", quarter.casefold())
    return f"{base}_{period or 'period'}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status(path: Path, **payload: Any) -> None:
    _write_json(path, {"updated_at": datetime.now(timezone.utc).isoformat(), **payload})


def _period_order(period: dict[str, Any]) -> tuple[int, int, int]:
    text = str(period.get("name") or "").casefold()
    year = re.search(r"(?:19|20)\d{2}", text)
    quarter = re.search(r"([1-4])\s*(?:кв|квартал)", text)
    return (int(year.group(0)) if year else 0, int(quarter.group(1)) if quarter else 0, int(period.get("id") or 0))


def discover_catalog() -> dict[str, Any]:
    """Read the public FGIS subject -> zone -> period catalogue without auth."""
    subjects_out: list[dict[str, Any]] = []
    for subject in price_fetch.list_subjects():
        zones_out: list[dict[str, Any]] = []
        for zone in price_fetch.price_zones(int(subject["id"])):
            periods = sorted(price_fetch.periods(int(zone["id"])), key=_period_order, reverse=True)
            zones_out.append({**zone, "periods": periods})
        subjects_out.append({**subject, "zones": zones_out})
    return {
        "schema": "les.fgis.public-catalog.v1",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "subjects": subjects_out,
    }


def _book_name(subject: dict[str, Any], zone: dict[str, Any], period: dict[str, Any]) -> str:
    base = _slug(str(subject.get("name") or "region"), str(period.get("name") or "period"))
    return f"{base}_zone-{int(zone.get('id') or 0)}"


def update_price_books(
    *,
    catalog: dict[str, Any],
    all_periods: bool = False,
    out_root: Path = Path("data/price_base"),
    rate: float = 0.3,
    status_out: Path = DEFAULT_STATUS,
) -> dict[str, Any]:
    """Download latest (or explicitly all) split forms for every price zone."""
    tasks: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for subject in catalog.get("subjects") or []:
        for zone in subject.get("zones") or []:
            periods = list(zone.get("periods") or [])
            for period in periods if all_periods else periods[:1]:
                tasks.append((subject, zone, period))

    done: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    delay = 1.0 / rate if rate > 0 else 0.0
    started = time.monotonic()
    bytes_downloaded = 0
    for index, (subject, zone, period) in enumerate(tasks, 1):
        elapsed = max(0.0, time.monotonic() - started)
        completed = index - 1
        eta = (elapsed / completed * (len(tasks) - completed)) if completed else None
        rate_bytes_per_second = (bytes_downloaded / elapsed) if elapsed > 0 and bytes_downloaded else None
        _write_status(
            status_out,
            status="running",
            stage="price_books",
            activity="downloading",
            message="Скачивается Сплит-форма ФГИС ЦС",
            completed=completed,
            total=len(tasks),
            remaining=len(tasks) - completed,
            percent=round(completed * 100 / len(tasks), 1) if tasks else 100.0,
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=round(eta, 1) if eta is not None else None,
            bytes_downloaded=bytes_downloaded,
            rate_bytes_per_second=round(rate_bytes_per_second, 1) if rate_bytes_per_second else None,
            current={"subject": subject.get("name"), "zone": zone.get("name"), "period": period.get("name")},
        )
        result = price_fetch.import_price_zone(
            subject=subject,
            zone=zone,
            period=period,
            name=_book_name(subject, zone, period),
            out_root=out_root,
        )
        (done if result.get("ok") else failed).append(result)
        bytes_downloaded += int(result.get("bytes") or 0)
        if delay and index < len(tasks):
            time.sleep(delay)
    return {
        "mode": "all_periods" if all_periods else "latest_per_zone",
        "requested": len(tasks),
        "done": len(done),
        "failed": len(failed),
        "rows": sum(int(item.get("rows") or 0) for item in done),
        "books": done,
        "errors": failed,
    }


def run_update(
    *,
    include_gesn: bool = True,
    all_periods: bool = False,
    rate: float = 0.3,
    status_out: Path = DEFAULT_STATUS,
    catalog_out: Path = DEFAULT_CATALOG,
    manifest_out: Path = DEFAULT_MANIFEST,
    price_root: Path = Path("data/price_base"),
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    _write_status(
        status_out,
        status="running",
        stage="catalog",
        activity="requesting_metadata",
        message="ФГИС ЦС: получаем список регионов, ценовых зон и периодов",
        started_at=started_at,
    )
    catalog = discover_catalog()
    _write_json(catalog_out, catalog)
    prices = update_price_books(
        catalog=catalog,
        all_periods=all_periods,
        out_root=price_root,
        rate=rate,
        status_out=status_out,
    )
    gesn: dict[str, Any] | None = None
    if include_gesn:
        _write_status(
            status_out,
            status="running",
            stage="gesn",
            activity="downloading",
            message="Скачиваются нормы и ресурсы ГЭСН из ФГИС ЦС",
            started_at=started_at,
            prices=prices,
        )

        def _gesn_progress(payload: dict[str, Any]) -> None:
            progress = payload.get("progress") or {}
            nested_stage = str(payload.get("stage") or "download")
            _write_status(
                status_out,
                status="running",
                stage="gesn" if nested_stage == "download" else nested_stage,
                activity="downloading" if nested_stage == "download" else "processing",
                message=(
                    "Скачиваются нормы и ресурсы ГЭСН из ФГИС ЦС"
                    if nested_stage == "download"
                    else "Скачивание завершено; собирается локальная база ГЭСН"
                ),
                started_at=started_at,
                prices=prices,
                gesn_progress=progress,
            )

        gesn = gesn_update_from_fgis.run_update(progress_callback=_gesn_progress)
    result = {
        "schema": "les.fgis.public-update.v1",
        "status": "done" if not prices["failed"] else "partial",
        "stage": "done",
        "scope": ["public_catalog", "split_forms", *( ["gesn_norms_resources"] if include_gesn else [])],
        "catalog": str(catalog_out),
        "prices": prices,
        "gesn": gesn,
        "limitations": [
            "Закрытые JSON-гриды ФГИС ЦС требуют Bearer и не скачиваются без авторизации.",
            "Bulk-экспорт документов ФРСН защищён captcha и не автоматизируется обходом защиты.",
        ],
    }
    _write_json(manifest_out, result)
    _write_status(status_out, **result)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update every public FGIS CS source used by LES")
    parser.add_argument("--skip-gesn", action="store_true")
    parser.add_argument("--all-periods", action="store_true")
    parser.add_argument("--rate", type=float, default=0.3)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = run_update(include_gesn=not args.skip_gesn, all_periods=args.all_periods, rate=args.rate)
    except Exception as exc:  # noqa: BLE001 - persist an operator-visible failed job
        result = {
            "schema": "les.fgis.public-update.v1",
            "status": "failed",
            "stage": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_status(DEFAULT_STATUS, **result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
