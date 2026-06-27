"""ФГИС ЦС — НАПОЛНЕНИЕ локальной ценовой базы из официального источника (БЕЗ auth). 0 LLM.

Архитектура (принцип Олега)
===========================
* **Все базы локально.** Query-time цена в костинге берётся ТОЛЬКО из локального
  Parquet (`fgis_price_service.PriceBook` / `data/price_base/*.parquet`). Канал
  (ФГИС/Cloudflare режутся из рантайма) НЕ участвует в горячем ответе чата.
* **Канал — лишь для обновления базы по запросу, и ему НЕ доверяем.** Короткий
  таймаут (env `LES_FGIS_TIMEOUT`, дефолт 8с на метаданные; файл — отдельный
  `LES_FGIS_FILE_TIMEOUT`), retry с лимитом и backoff, сбой → graceful (как «нет
  в базе» → КАЦ), чат не вешаем.

Доказанный источник цен — ФАЙЛ, не per-code API
-----------------------------------------------
Раскопка webpack-чанков (`public.js`/`121.js`/…) + curl с VPS (РФ-IP) показали:

* Per-строчный JSON-грид цены ``EstimatedPrice/BuildingResources/Materials``
  (и ``…/Machines``) отвечает **401 ``WWW-Authenticate: Bearer``** — закрыт.
* Метаданные открыты (200, без auth): ``EstimatedPrice/CountrySubjects`` (субъекты),
  ``…/PriceZones?subjectId=`` (зоны), ``…/Periods?priceZoneId=`` (кварталы).
* **``EstimatedPrice/BuildingResources/ExportSplitForm?priceZoneId=&periodId=``
  отдаёт ПОЛНУЮ «Сплит-форму» XLSX (≈8 МБ, 161k строк) — 200, БЕЗ auth.**

Значит per-code price API НЕТ. Ценовая база доступна только файлом-выгрузкой на
``(priceZoneId, periodId)``. Локальный Parquet, собранный из этого файла, И ЕСТЬ
база (см. ``fgis_price_service.build_price_parquet``). Различение в костинге:
  (a) кода нет в свежей полной выгрузке ФГИС ЦС → корректный КАЦ-кейс;
  (b) есть в выгрузке, но не в нашей локальной нарезке → добор: обновить Parquet.

Сеть прямая (urllib); опц. VPS-egress: env ``LES_FGIS_VIA_SSH=root@host`` (как в
``gesn_fgis_service``) — на случай гео-резки прямого канала из рантайма.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from proxy.services import fgis_price_service as fps

_BASE = "https://fgiscs.minstroyrf.ru/api"

# Короткий таймаут на МЕТАДАННЫЕ (мелкий JSON) — недоверенный канал не должен вешать.
_META_TIMEOUT = int(os.getenv("LES_FGIS_TIMEOUT", "8"))
# Файл «Сплит-формы» — крупный (≈8 МБ); отдельный, более щедрый таймаут наполнения.
_FILE_TIMEOUT = int(os.getenv("LES_FGIS_FILE_TIMEOUT", "120"))


def _via_ssh() -> str:
    return os.getenv("LES_FGIS_VIA_SSH", "").strip()


def _get_json(path: str, *, timeout: int = _META_TIMEOUT) -> Any:
    """GET открытого JSON-эндпоинта ФГИС ЦС. Прямой urllib; опц. VPS-egress."""
    url = f"{_BASE}/{path}"
    via = _via_ssh()
    if via:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", via,
             f"curl -sS -m {timeout} '{url}'"],
            capture_output=True, text=True, timeout=timeout + 6,
        )
        if out.returncode != 0:
            raise RuntimeError(f"ssh/curl failed ({out.returncode}): {out.stderr[:160]}")
        return json.loads(out.stdout)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download_file(path: str, dest: Path, *, timeout: int = _FILE_TIMEOUT) -> int:
    """Скачать файл-эндпоинт (ExportSplitForm) в dest. Возвращает размер в байтах."""
    url = f"{_BASE}/{path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    via = _via_ssh()
    if via:
        # Качаем на VPS, затем scp на хост (канал режется только напрямую из рантайма).
        remote = f"/tmp/les_split_{os.getpid()}.xlsx"
        dl = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", via,
             f"curl -sS -m {timeout} -o {remote} '{url}' && stat -c %s {remote}"],
            capture_output=True, text=True, timeout=timeout + 10,
        )
        if dl.returncode != 0:
            raise RuntimeError(f"ssh/curl download failed ({dl.returncode}): {dl.stderr[:160]}")
        subprocess.run(
            ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
             f"{via}:{remote}", str(dest)],
            capture_output=True, text=True, timeout=timeout + 10, check=True,
        )
        subprocess.run(["ssh", "-o", "BatchMode=yes", via, f"rm -f {remote}"],
                       capture_output=True, text=True, timeout=20)
        return dest.stat().st_size
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    dest.write_bytes(data)
    return len(data)


def _retry(fn, *, retries: int = 3, backoff: float = 1.5):
    """Вызвать fn() с лимитированным retry и экспоненциальным backoff. Поднимает последнее."""
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:                       # noqa: BLE001 — сеть/JSON/таймаут
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    raise RuntimeError(f"failed after {retries} tries: {last}")


# ─────────────────────────────────────────
# Открытая навигация по справочнику (метаданные)
# ─────────────────────────────────────────

def list_subjects() -> list[dict[str, Any]]:
    """Субъекты РФ ФГИС ЦС: [{'id', 'name'}, …] (открыто, без auth)."""
    return _get_json("EstimatedPrice/CountrySubjects") or []


def price_zones(subject_id: int) -> list[dict[str, Any]]:
    """Ценовые зоны субъекта: [{'id', 'name'}, …]."""
    return _get_json(f"EstimatedPrice/PriceZones?subjectId={int(subject_id)}") or []


def periods(price_zone_id: int) -> list[dict[str, Any]]:
    """Доступные периоды (кварталы) зоны: [{'id', 'name'}, …], свежий первым."""
    return _get_json(f"EstimatedPrice/Periods?priceZoneId={int(price_zone_id)}") or []


def resolve_subject(name_substr: str) -> Optional[dict[str, Any]]:
    """Найти субъект по подстроке имени (напр. 'Петербург')."""
    needle = name_substr.casefold()
    for s in list_subjects():
        if needle in str(s.get("name", "")).casefold():
            return s
    return None


def resolve_period(price_zone_id: int, quarter_substr: str) -> Optional[dict[str, Any]]:
    """Найти период зоны по подстроке имени (напр. '2 квартал 2025')."""
    needle = quarter_substr.casefold().replace("кв.", "квартал")
    for p in periods(price_zone_id):
        if needle in str(p.get("name", "")).casefold():
            return p
    return None


# ─────────────────────────────────────────
# Наполнение локальной базы (файл-выгрузка → Parquet)
# ─────────────────────────────────────────

def fetch_split_form(price_zone_id: int, period_id: int, dest: str | Path) -> int:
    """Скачать «Сплит-форму» XLSX по (зона, период) в dest. Возвращает размер в байтах.

    Полная книга цен (материалы+машины) — то, из чего строится локальный Parquet.
    """
    path = (f"EstimatedPrice/BuildingResources/ExportSplitForm"
            f"?priceZoneId={int(price_zone_id)}&periodId={int(period_id)}")
    return _retry(lambda: _download_file(path, Path(dest)))


def import_region(
    *,
    subject: str,
    quarter: str,
    name: str,
    out_root: str | Path = fps.DEFAULT_PRICE_ROOT,
    region_label: Optional[str] = None,
) -> dict[str, Any]:
    """Наполнить локальную книгу цен по (субъект, квартал): метаданные → файл → Parquet.

    subject/quarter — подстроки ('Петербург', '2 квартал 2025'). name — stem Parquet
    (напр. 'spb_2kv2025'). Канал-безопасно: сбой любого шага → graceful dict ok=False.
    """
    subj = resolve_subject(subject)
    if not subj:
        return {"ok": False, "stage": "subject", "note": f"субъект {subject!r} не найден"}
    zones = price_zones(subj["id"])
    if not zones:
        return {"ok": False, "stage": "zone", "note": f"нет зон у субъекта {subj['name']!r}"}
    zone = zones[0]
    period = resolve_period(zone["id"], quarter)
    if not period:
        avail = ", ".join(p.get("name", "") for p in periods(zone["id"]))
        return {"ok": False, "stage": "period", "note": f"период {quarter!r} не найден (есть: {avail})"}

    out = Path(out_root) / f"{Path(name).name}.parquet"
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        size = fetch_split_form(zone["id"], period["id"], tmp)
        if size < 1024:
            return {"ok": False, "stage": "download", "note": f"файл подозрительно мал ({size} б)"}
        summary = fps.build_price_parquet(
            tmp, out,
            region=region_label or subj["name"],
            quarter=period.get("name", quarter),
        )
        fps.get_pricebook.cache_clear()
        return {
            "ok": True, "name": out.stem, "rows": summary["rows"],
            "region": summary["region"], "quarter": summary["quarter"],
            "subject_id": subj["id"], "price_zone_id": zone["id"], "period_id": period["id"],
            "bytes": size, "parquet": summary["parquet"],
        }
    except RuntimeError as e:
        # Недоверенный канал упал — graceful, не вешаем и не роняем.
        return {"ok": False, "stage": "download", "note": str(e)}
    finally:
        tmp.unlink(missing_ok=True)


# ─────────────────────────────────────────
# Локаль-первый lookup (костинг) + добор-по-промаху
# ─────────────────────────────────────────

def lookup_local_first(
    code: str,
    *,
    book: Optional[str] = None,
    refresh_on_miss: bool = False,
    subject: str = "Петербург",
    quarter: str = "2 квартал 2025",
    name: str = "spb_2kv2025",
) -> dict[str, Any]:
    """Цена по коду: ЛОКАЛЬ первой; промах + refresh_on_miss → обновить базу и повторить.

    Возвращает {'found', 'price', 'source': 'local'|'fgis'|'none', 'needs_kac', …}.
    refresh_on_miss=False по умолчанию: query-time канал НЕ дёргаем (он недоверенный).
    Добор включают явно — для наполнения базы, не в горячем пути ответа чата.
    """
    path: Optional[str] = None
    if book:
        path = next((p for p in fps.available_pricebooks() if Path(p).stem == book), None)
    else:
        books = fps.available_pricebooks()
        path = books[0] if books else None

    if path:
        rec = fps.get_pricebook(path).lookup(code)
        if rec is not None:
            return {"found": True, "code": code, "source": "local",
                    "book": Path(path).stem, "price": rec.get("price_current_eff"),
                    "needs_kac": False, "row": rec}

    if not refresh_on_miss:
        # Локаль-only: промах → корректный сигнал «нет в локальной базе» (→ КАЦ).
        return {"found": False, "code": code, "source": "none",
                "needs_kac": True, "note": "нет в локальной книге; добор канала отключён"}

    # Промах + явный добор: обновить локальную книгу из ФГИС ЦС, затем повторить ЛОКАЛЬНО.
    upd = import_region(subject=subject, quarter=quarter, name=name)
    if not upd.get("ok"):
        # Канал упал — graceful: ведём себя как «нет в базе» (→ КАЦ), не вешаем.
        return {"found": False, "code": code, "source": "none", "needs_kac": True,
                "note": f"добор не удался: {upd.get('note')}", "refresh": upd}
    rec = fps.get_pricebook(upd["parquet"]).lookup(code)
    if rec is not None:
        return {"found": True, "code": code, "source": "fgis", "book": upd["name"],
                "price": rec.get("price_current_eff"), "needs_kac": False,
                "refresh": upd, "row": rec}
    # Есть в навигации ФГИС ЦС, но кода нет в полной выгрузке → корректный КАЦ-кейс.
    return {"found": False, "code": code, "source": "fgis", "needs_kac": True,
            "note": "кода нет в полной выгрузке ФГИС ЦС → КАЦ", "refresh": upd}
