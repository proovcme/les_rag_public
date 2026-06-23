"""Массовая заливка ПОЛНОЙ базы ГЭСН-2022 из официального ФГИС ЦС → Parquet (схема gesn_import).

Зачем
=====
``tools/gesn_pdf_import.py`` тянет ОДНУ норму/таблицу по коду; ``gesn_fgis_service`` — on-demand
по встреченному коду. Этот модуль закрывает РАЗОВУЮ полную заливку всех 47 строительных сборников
ГЭСН-2022 (Приказ Минстроя 1046/пр) — десятки тысяч норм — в один Parquet, идемпотентно и вежливо.

Источник и перечисление кодов (доказано)
----------------------------------------
ФГИС ЦС раздаёт структурный расход через
``GET /api/FullTextSearch/SearchEstimatedRates?search=<код>`` (без auth/квоты/гео — прямой urllib).
Поиск — это ПРЕФИКСНЫЙ матч по шифру нормы: ``search=NN-NN`` (отдел) возвращает ВСЕ нормы всех
таблиц этого отдела одним ответом. Доказано: ``12-03`` ⊇ нормы ``12-03-001`` (per-table) без потерь;
``12-01`` → 86 таблиц/14МБ. Это и есть надёжная гранулярность перебора:

* перебираем ОТДЕЛЫ ``NN-NN`` (а не каждую таблицу — на порядок меньше запросов);
* сборник ``NN`` целиком (``search=NN``) — НЕнадёжно (>15МБ, рвётся по таймауту), не используем;
* отделы РАЗРЕЖЕНЫ (у сб.12: 01,02,03,09,20,…) — сканируем ``NN-01..NN-MAX`` с допуском пропусков
  (``--otdel-gap``), отбрасывая записи, чей шифр не начинается на запрошенный префикс (fulltext
  может зацепить мусор — defensively фильтруем).

Свойства прогона
----------------
* **Резюмируемость**: уже лежащие в Parquet ``norm_code`` (их отделы) пропускаются — повторный
  запуск дозаливает; прерванный — продолжает с места.
* **Вежливость**: rate-limit (``--rate`` req/сек, дефолт 1.0) + retry с экспоненциальным backoff.
* **Прогресс**: лог сделано/всего/ошибки/норм по каждому отделу.
* **Идемпотентно**: ``build_parquet(append=True)`` дедупит по ключу нормы.

Запуск
------
    # один сборник (проверка):
    uv run python -m tools.gesn_bulk_import --sbornik 12 --out data/gesn_base/gesn2022.parquet

    # ПОЛНАЯ база (часы — см. оценку в docs/ALGO-gesn.md):
    uv run python -m tools.gesn_bulk_import --all --rate 1.0 --out data/gesn_base/gesn2022.parquet

    # через VPS-egress (если прямая сеть режется): env LES_FGIS_VIA_SSH=root@HOST
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

from tools.gesn_pdf_import import DEFAULT_OUT, build_parquet, parse_fgis_json

API = "https://fgiscs.minstroyrf.ru/api/FullTextSearch/SearchEstimatedRates?search="

# Строительные сборники ГЭСН-2022 (Приказ 1046/пр): 01..47. Диапазон отделов в сборнике РАЗРЕЖЕН
# (напр. сб.12: 01,02,03,09,20…), поэтому отделы не перечисляем жёстко — сканируем с допуском.
SBORNIKI = tuple(range(1, 48))
DEFAULT_OTDEL_MAX = 40          # верхняя граница номера отдела при сканировании NN-01..NN-MAX
DEFAULT_OTDEL_GAP = 8           # подряд пустых отделов → конец сборника (разрежены, но не бесконечно)

_NORM_PREFIX_RE = re.compile(r"^(\d{2}-\d{2}-\d{3})")


# ── сеть ──────────────────────────────────────────────────────────────

def _fetch_raw(search: str, *, timeout: int = 90) -> list[dict[str, Any]]:
    """SearchEstimatedRates по префиксу. Прямой urllib; опц. VPS egress (env LES_FGIS_VIA_SSH)."""
    url = API + urllib.parse.quote(str(search), safe="")
    via = os.getenv("LES_FGIS_VIA_SSH", "").strip()
    if via:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", via,
             f"curl -sS -m {timeout - 5} '{url}'"],
            capture_output=True, text=True, timeout=timeout,
        )
        if out.returncode != 0:
            raise RuntimeError(f"ssh/curl failed ({out.returncode}): {out.stderr[:160]}")
        data = json.loads(out.stdout)
    else:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    if isinstance(data, list):
        return data
    return data.get("data") or data.get("items") or []


def _fetch_with_retry(search: str, *, retries: int = 4, backoff: float = 2.0,
                      timeout: int = 90) -> list[dict[str, Any]]:
    """Фетч с экспоненциальным backoff на сетевых сбоях. Поднимает последнее исключение."""
    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return _fetch_raw(search, timeout=timeout)
        except Exception as e:                       # noqa: BLE001 — сеть/JSON/таймаут
            last = e
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
    raise RuntimeError(f"fetch {search!r} failed after {retries} tries: {last}")


# ── перечисление кодов ────────────────────────────────────────────────

def _otdel_codes(sbornik: int, *, otdel_max: int = DEFAULT_OTDEL_MAX) -> list[str]:
    """Кандидаты отделов сборника: ['12-01','12-02',…,'12-MAX'] (сканируются с допуском пропусков)."""
    return [f"{sbornik:02d}-{o:02d}" for o in range(1, otdel_max + 1)]


def _records_for_prefix(prefix: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Оставить лишь записи, чей шифр нормы начинается на запрошенный отдел (анти-мусор fulltext)."""
    kept = []
    for rec in records:
        cols = rec.get("normTableJson")
        if isinstance(cols, str):
            cols = json.loads(cols)
        nums = [re.sub(r"</?em>", "", str(c.get("number") or "")) for c in (cols or [])]
        if any(n.startswith(prefix) for n in nums):
            kept.append(rec)
    return kept


# ── состояние Parquet (резюмируемость) ────────────────────────────────

def _existing_otdel_prefixes(parquet_path: Path) -> set[str]:
    """Отделы ('NN-NN'), уже представленные в базе → пропускаем при дозаливке."""
    if not parquet_path.exists():
        return set()
    import pandas as pd

    try:
        df = pd.read_parquet(parquet_path, columns=["norm_code"])
    except Exception:                                # noqa: BLE001 — битый/старый parquet → не резюмируем
        return set()
    out: set[str] = set()
    for code in df["norm_code"].dropna().astype(str):
        bare = re.sub(r"^(ГЭСН[А-Яа-яA-Za-z]*|GESN)", "", code, flags=re.I).strip()
        m = _NORM_PREFIX_RE.match(bare)
        if m:
            out.add(m.group(1)[:5])                  # 'NN-NN'
    return out


# ── основной прогон ───────────────────────────────────────────────────

def run(
    *,
    sborniki: Iterable[int],
    out_path: str | Path = DEFAULT_OUT,
    rate: float = 1.0,
    otdel_max: int = DEFAULT_OTDEL_MAX,
    otdel_gap: int = DEFAULT_OTDEL_GAP,
    limit: Optional[int] = None,
    resume: bool = True,
    log: Any = sys.stderr,
) -> dict[str, Any]:
    """Перебрать отделы сборников → ФГИС ЦС → дозалить в Parquet. Возвращает сводку.

    rate — запросов/сек (вежливость); otdel_gap — подряд пустых отделов → конец сборника;
    limit — стоп после N успешных отделов (для проверки). resume — пропускать уже залитые отделы.
    """
    out_path = Path(out_path)
    done_prefixes = _existing_otdel_prefixes(out_path) if resume else set()
    delay = 1.0 / rate if rate > 0 else 0.0

    stats = {"otdels_done": 0, "otdels_skipped": 0, "otdels_empty": 0,
             "errors": 0, "norms": 0, "resources": 0}

    def _emit(msg: str) -> None:
        print(msg, file=log, flush=True)

    for sb in sborniki:
        gap = 0
        for prefix in _otdel_codes(sb, otdel_max=otdel_max):
            if gap >= otdel_gap:
                break                                # длинная серия пустых → сборник кончился
            if resume and prefix in done_prefixes:
                stats["otdels_skipped"] += 1
                gap = 0                              # отдел существует (был залит) → не считаем пропуском
                _emit(f"[skip] {prefix} — уже в базе")
                continue
            try:
                raw = _fetch_with_retry(prefix)
            except RuntimeError as e:
                stats["errors"] += 1
                _emit(f"[ERR ] {prefix}: {e}")
                if delay:
                    time.sleep(delay)
                continue
            recs = _records_for_prefix(prefix, raw)
            if not recs:
                stats["otdels_empty"] += 1
                gap += 1
                if delay:
                    time.sleep(delay)
                continue
            gap = 0
            rows = parse_fgis_json(recs)
            if not rows:
                stats["otdels_empty"] += 1
                if delay:
                    time.sleep(delay)
                continue
            summary = build_parquet(rows, out_path, append=True)
            n_norms = summary.get("norms") or 0
            stats["otdels_done"] += 1
            stats["norms"] += n_norms
            stats["resources"] += summary.get("resources") or 0
            done_prefixes.add(prefix)
            total_norms = summary.get("resources")  # это всего строк в базе
            _emit(f"[ok  ] {prefix}: +{n_norms} норм / {len(rows)} строк "
                  f"(база: {total_norms} строк, отделов done={stats['otdels_done']} "
                  f"err={stats['errors']})")
            if limit is not None and stats["otdels_done"] >= limit:
                _emit(f"[stop] достигнут --limit {limit}")
                return stats
            if delay:
                time.sleep(delay)
    return stats


def _main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Массовая заливка базы ГЭСН-2022 из ФГИС ЦС → Parquet")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all", action="store_true", help="все строительные сборники 01..47")
    grp.add_argument("--sbornik", type=int, metavar="NN", help="один сборник (напр. 12)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"Parquet (по умолч. {DEFAULT_OUT})")
    ap.add_argument("--rate", type=float, default=1.0, help="запросов/сек (вежливость, дефолт 1.0)")
    ap.add_argument("--limit", type=int, default=None, help="стоп после N залитых отделов (проверка)")
    ap.add_argument("--otdel-max", type=int, default=DEFAULT_OTDEL_MAX,
                    help=f"верхний номер отдела при сканировании (дефолт {DEFAULT_OTDEL_MAX})")
    ap.add_argument("--otdel-gap", type=int, default=DEFAULT_OTDEL_GAP,
                    help=f"подряд пустых отделов → конец сборника (дефолт {DEFAULT_OTDEL_GAP})")
    ap.add_argument("--no-resume", action="store_true", help="не пропускать уже залитые отделы")
    args = ap.parse_args(list(argv) if argv is not None else None)

    sborniki = list(SBORNIKI) if args.all else [args.sbornik]
    try:
        stats = run(
            sborniki=sborniki, out_path=args.out, rate=args.rate,
            otdel_max=args.otdel_max, otdel_gap=args.otdel_gap,
            limit=args.limit, resume=not args.no_resume,
        )
    except KeyboardInterrupt:
        print("\nпрервано пользователем (база сохранена по отделам — резюмируемо)", file=sys.stderr)
        return 130
    print(f"OK: отделов залито={stats['otdels_done']} пропущено={stats['otdels_skipped']} "
          f"пусто={stats['otdels_empty']} ошибок={stats['errors']} | "
          f"+{stats['norms']} норм / +{stats['resources']} строк → {args.out}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())
