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
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from proxy.services import fgis_price_fetch_service as price_fetch
from tools import gesn_update_from_fgis

DEFAULT_STATUS = Path("storage/jobs/fgis_full_update_status.json")
DEFAULT_LOG = Path("storage/jobs/fgis_full_update.log")
DEFAULT_CHECKPOINT = Path("storage/jobs/fgis_full_update_checkpoint.json")
DEFAULT_CATALOG = Path("data/price_base/fgis_catalog.json")
DEFAULT_MANIFEST = Path("data/price_base/fgis_latest_manifest.json")
PACKAGED_BASELINE = Path("installers/windows/baseline/LES-smeta-baseline.zip")


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
    """Atomically write JSON with Windows-safe replace retries.

    On Windows the status file is polled by the UI while the updater rewrites it.
    A plain ``.tmp`` → replace can raise WinError 5; retry with a unique temp name
    and fall back to in-place write so a locked status file does not kill GESN.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary = path.with_name(f"{path.stem}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    last_error: Exception | None = None
    for attempt in range(8):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(min(1.0, 0.05 * (2**attempt)))
        except OSError as exc:
            last_error = exc
            # WinError 5 surfaces as PermissionError on some Pythons and OSError on others.
            if getattr(exc, "winerror", None) != 5 and getattr(exc, "errno", None) not in {13, 11}:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(min(1.0, 0.05 * (2**attempt)))
    try:
        path.write_text(text, encoding="utf-8")
        temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        if last_error is not None:
            raise last_error
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _book_checkpoint_key(zone: dict[str, Any], period: dict[str, Any]) -> str:
    return f"{int(zone.get('id') or 0)}:{int(period.get('id') or 0)}"


def _valid_checkpoint_book(item: dict[str, Any], *, out_root: Path | None = None) -> bool:
    path = Path(str(item.get("parquet") or ""))
    if not path.is_file() or path.stat().st_size < 1024 or int(item.get("rows") or 0) <= 0:
        return False
    # Foreign pytest/temp leftovers must never count as a resume source.
    # Entries under the active out_root are fine even inside a pytest tree.
    if out_root is not None:
        try:
            path.resolve().relative_to(Path(out_root).resolve())
        except ValueError:
            normalized = str(path).casefold().replace("\\", "/")
            if "pytest" in normalized or "/temp/" in normalized:
                return False
    try:
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(path).metadata.num_rows) == int(item.get("rows") or 0)
    except Exception:
        return False


def _existing_local_book(
    *,
    out_root: Path,
    name: str,
    subject: dict[str, Any],
    zone: dict[str, Any],
    period: dict[str, Any],
) -> dict[str, Any] | None:
    """Reuse an already-downloaded pricebook under out_root without hitting FGIS."""
    path = (Path(out_root) / f"{Path(name).name}.parquet").resolve()
    if not path.is_file() or path.stat().st_size < 1024:
        return None
    try:
        import pyarrow.parquet as pq

        rows = int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        return None
    if rows <= 0:
        return None
    return {
        "ok": True,
        "resumed": True,
        "name": path.stem,
        "rows": rows,
        "bytes": int(path.stat().st_size),
        "parquet": str(path),
        "subject_id": subject.get("id"),
        "price_zone_id": zone.get("id"),
        "period_id": period.get("id"),
        "region": zone.get("name") or subject.get("name"),
        "quarter": period.get("name"),
    }


def _repair_local_baseline() -> dict[str, Any]:
    """Validate/repair the immutable norms+FSEM starting point when packaged."""
    if not PACKAGED_BASELINE.is_file():
        return {
            "state": "unavailable",
            "message": "В установке нет резервной базы ФСНБ; нормы будут скачаны, ФСЭМ восстановить нельзя",
        }
    from tools.smeta_release_baseline import repair_archive

    result = repair_archive(PACKAGED_BASELINE, Path("."))
    return {
        "state": "ready",
        "message": "Базовый ФСНБ и ФСЭМ проверены",
        "action": result.get("action"),
        "norms": result.get("norm_count"),
        "fsem_rows": result.get("fsem_rows"),
        "backup": result.get("backup"),
    }
def _write_status(path: Path, **payload: Any) -> None:
    _write_json(path, {"updated_at": datetime.now(timezone.utc).isoformat(), **payload})
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    location = " · ".join(
        str(current.get(key) or "").strip()
        for key in ("subject", "zone", "period")
        if str(current.get(key) or "").strip()
    )
    progress = ""
    if payload.get("completed") is not None and payload.get("total"):
        progress = f" {payload.get('completed')}/{payload.get('total')}"
    message = str(payload.get("message") or payload.get("error") or payload.get("stage") or "обновление")
    line = f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {message}{progress}"
    if location:
        line += f" · {location}"
    log_path = DEFAULT_LOG if path == DEFAULT_STATUS else path.with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


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
    checkpoint_out: Path = DEFAULT_CHECKPOINT,
    retries: int = 3,
) -> dict[str, Any]:
    """Download latest (or explicitly all) split forms for every price zone."""
    tasks: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for subject in catalog.get("subjects") or []:
        for zone in subject.get("zones") or []:
            periods = list(zone.get("periods") or [])
            for period in periods if all_periods else periods[:1]:
                tasks.append((subject, zone, period))

    checkpoint = _read_json(checkpoint_out)
    completed_books = {
        key: value
        for key, value in (checkpoint.get("books") or {}).items()
        if isinstance(value, dict) and _valid_checkpoint_book(value, out_root=out_root)
    }
    done: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    delay = 1.0 / rate if rate > 0 else 0.0
    started = time.monotonic()
    bytes_downloaded = 0
    checkpoint_dirty = False
    for index, (subject, zone, period) in enumerate(tasks, 1):
        elapsed = max(0.0, time.monotonic() - started)
        completed = index - 1
        eta = (elapsed / completed * (len(tasks) - completed)) if completed else None
        rate_bytes_per_second = (bytes_downloaded / elapsed) if elapsed > 0 and bytes_downloaded else None
        key = _book_checkpoint_key(zone, period)
        book_name = _book_name(subject, zone, period)
        saved = completed_books.get(key) if isinstance(completed_books.get(key), dict) else {}
        local = _existing_local_book(
            out_root=out_root,
            name=book_name,
            subject=subject,
            zone=zone,
            period=period,
        )
        if local:
            result = local
            completed_books[key] = {k: v for k, v in local.items() if k != "resumed"}
            checkpoint_dirty = True
            activity = "resuming"
            message = "Пропускаем уже скачанную Сплит-форму"
        elif saved:
            result = {**saved, "ok": True, "resumed": True}
            activity = "resuming"
            message = "Пропускаем уже скачанную Сплит-форму"
        else:
            result = {}
            activity = "downloading"
            message = "Скачивается Сплит-форма ФГИС ЦС"
            for attempt in range(1, max(1, retries) + 1):
                _write_status(
                    status_out,
                    status="running",
                    stage="price_books",
                    activity="downloading" if attempt == 1 else "retrying",
                    message=(
                        message
                        if attempt == 1
                        else f"Повторяем Сплит-форму после ошибки ({attempt}/{max(1, retries)})"
                    ),
                    completed=completed,
                    total=len(tasks),
                    remaining=len(tasks) - completed,
                    percent=round(completed * 100 / len(tasks), 1) if tasks else 100.0,
                    elapsed_seconds=round(time.monotonic() - started, 1),
                    eta_seconds=round(eta, 1) if eta is not None else None,
                    bytes_downloaded=bytes_downloaded,
                    rate_bytes_per_second=(
                        round(rate_bytes_per_second, 1) if rate_bytes_per_second else None
                    ),
                    current={
                        "subject": subject.get("name"),
                        "zone": zone.get("name"),
                        "period": period.get("name"),
                    },
                    retry=(
                        {"attempt": attempt, "maximum": max(1, retries)}
                        if attempt > 1
                        else None
                    ),
                )
                result = price_fetch.import_price_zone(
                    subject=subject,
                    zone=zone,
                    period=period,
                    name=book_name,
                    out_root=out_root,
                )
                if result.get("ok"):
                    completed_books[key] = result
                    checkpoint_dirty = True
                    break
                if attempt < max(1, retries):
                    time.sleep(min(30.0, 2.0**attempt))
        _write_status(
            status_out,
            status="running",
            stage="price_books",
            activity=activity,
            message=message,
            completed=index if result.get("ok") else completed,
            total=len(tasks),
            remaining=max(0, len(tasks) - index) if result.get("ok") else len(tasks) - completed,
            percent=round((index if result.get("ok") else completed) * 100 / len(tasks), 1) if tasks else 100.0,
            elapsed_seconds=round(time.monotonic() - started, 1),
            eta_seconds=round(eta, 1) if eta is not None else None,
            bytes_downloaded=bytes_downloaded,
            rate_bytes_per_second=round(rate_bytes_per_second, 1) if rate_bytes_per_second else None,
            current={"subject": subject.get("name"), "zone": zone.get("name"), "period": period.get("name")},
        )
        if checkpoint_dirty and (index % 10 == 0 or index == len(tasks) or not result.get("resumed")):
            _write_json(
                checkpoint_out,
                {
                    "schema": "les.fgis.update-checkpoint.v1",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "books": completed_books,
                },
            )
            checkpoint_dirty = False
        (done if result.get("ok") else failed).append(result)
        if result.get("ok") and not result.get("resumed"):
            bytes_downloaded += int(result.get("bytes") or 0)
        if delay and index < len(tasks) and not result.get("resumed"):
            time.sleep(delay)
    if checkpoint_dirty:
        _write_json(
            checkpoint_out,
            {
                "schema": "les.fgis.update-checkpoint.v1",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "books": completed_books,
            },
        )
    return {
        "mode": "all_periods" if all_periods else "latest_per_zone",
        "requested": len(tasks),
        "done": len(done),
        "failed": len(failed),
        "rows": sum(int(item.get("rows") or 0) for item in done),
        "resumed": sum(1 for item in done if item.get("resumed")),
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
        stage="baseline",
        activity="validating",
        message="Проверяем локальную основу ФСНБ и при необходимости восстанавливаем её",
        started_at=started_at,
    )
    baseline = _repair_local_baseline()
    _write_status(
        status_out,
        status="running",
        stage="catalog",
        activity="requesting_metadata",
        message="ФГИС ЦС: получаем список регионов, ценовых зон и периодов",
        started_at=started_at,
        baseline=baseline,
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
            skipped = int(progress.get("otdels_skipped") or 0)
            downloaded = int(progress.get("otdels_done") or 0)
            resumed_complete = bool(progress.get("resumed_complete"))
            activity = str(progress.get("activity") or "")
            if nested_stage == "download":
                if resumed_complete or (skipped and not downloaded and activity != "downloading"):
                    activity_out = "resuming"
                    message = (
                        "Локальная база норм уже полная — пропускаем повторное скачивание ГЭСН"
                        if resumed_complete
                        else "Пропускаем уже скачанные отделы ГЭСН; новые дозаливаем при необходимости"
                    )
                else:
                    activity_out = "downloading"
                    message = "Скачиваются нормы и ресурсы ГЭСН из ФГИС ЦС"
            else:
                activity_out = "processing"
                message = "Скачивание завершено; собирается локальная база ГЭСН"
            _write_status(
                status_out,
                status="running",
                stage="gesn" if nested_stage == "download" else nested_stage,
                activity=activity_out,
                message=message,
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
        "baseline": baseline,
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
        previous = _read_json(DEFAULT_STATUS)
        result = {
            "schema": "les.fgis.public-update.v1",
            "status": "failed",
            "stage": "failed",
            "failed_stage": previous.get("stage"),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _write_status(DEFAULT_STATUS, **result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
