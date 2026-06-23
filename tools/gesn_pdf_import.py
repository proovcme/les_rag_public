"""Импортёр ОФИЦИАЛЬНОГО ФСНБ-2022 (ГЭСН-2022) из PDF ФГИС ЦС → Parquet (схема gesn_import).

Зачем
=====
``tools/gesn_import.py`` берёт ГОТОВУЮ табличную выгрузку (XLSX/CSV из ГРАНД-Сметы или БД).
Этот модуль закрывает ПРЯМОЙ путь от **официального первоисточника**: PDF сборника ГЭСН-2022,
который раздаёт ФГИС ЦС (fgiscs.minstroyrf.ru, Приказ Минстроя 1046/пр) — БЕЗ квоты API,
БЕЗ коммерческой НСИ. PDF → нормы → строки-ресурсы → тот же нормализованный Parquet
(схема ``tools.gesn_import.RESOURCE_FIELDS``), который читает ``proxy/services/gesn_service``.

Источник (как добыт, доказано)
------------------------------
ФГИС ЦС — React-SPA; реальный публичный API раскопан из webpack-чанка ``/public.js``:

- ``GET /api/FullTextSearch/SearchEstimatedRates?search=<код>`` — поиск нормы, возвращает
  СТРУКТУРИРОВАННЫЙ JSON нормы (``normTableJson`` — колонки-нормы; ``normTableValueTableJson`` —
  строки-ресурсы с расходом по каждой норме; ``normLegalDocPublishedGuid`` — GUID документа).
  Без captcha, без auth. Это и есть машиночитаемый официальный расход ресурсов.
- ``GET /api/NormLegalDocFilePublished/GetByGuid/<guid>`` — сам PDF документа (без captcha).
- ``POST /api/FrsnExport/ExportFrsnDocuments`` — bulk-экспорт, НО за captcha (Captcha/Get).

Т.е. официальная база достаётся ДВУМЯ путями, оба реализованы здесь:

1. **PDF** (``--from pdf``): pdfplumber извлекает таблицы расхода по геометрии слов
   (значение → колонка-норма по X-координате). Это «парсер официального PDF» из ТЗ.
2. **ФГИС ЦС JSON** (``--from fgis``, поиск по коду через VPS/прямой curl) — эталонно точный,
   совпадает с API smetnoedelo до знака; рекомендуемый для боевой заливки базы.

Структура таблицы в PDF ГЭСН
----------------------------
    Таблица ГЭСН 12-01-034 Устройство обрешетки
    Измеритель: 100 м2
    12-01-034-01 сплошной из досок
    12-01-034-02 Устройство обрешетки с прозорами из брусков
    Код ресурса  Наименование элемента затрат  Ед. изм.  | 034-01 | 034-02
    1  ЗАТРАТЫ ТРУДА РАБОЧИХ                               (категория → labor)
    1-100-25  Средний разряд работы 2,5     чел.-ч  19,14   12,94
    2  Затраты труда машинистов            чел.-ч   0,37    1,02   (категория-лист → machinist)
    3  МАШИНЫ И МЕХАНИЗМЫ                                  (категория → machine)
    91.05.01-017  Краны башенные …          маш.-ч   0,32    0,97
    4  МАТЕРИАЛЫ                                           (категория → material)
    01.7.15.06-0111  Гвозди строительные    т        0,0091  0,0015

Каждая колонка справа = отдельная норма (…-01, …-02). Значение привязывается к колонке
по X-координате (надёжнее наивного split — колонки бывают пустыми/разреженными). 0 LLM.

Запуск
------
    # из официального PDF (скачан в data/gesn_pdf/)
    uv run python -m tools.gesn_pdf_import data/gesn_pdf/gesn_12-01-034.pdf \
        --out data/gesn_base/gesn2022.parquet

    # из ФГИС ЦС по коду (через VPS-egress; см. --curl)
    uv run python -m tools.gesn_pdf_import --from fgis --code 12-01-034 \
        --curl 'ssh root@HOST curl -sS' --out data/gesn_base/gesn2022.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

# Та же нормализованная схема строки-ресурса, что у tools.gesn_import (общий контракт Parquet).
from tools.gesn_import import RESOURCE_FIELDS, _norm_code, _safe_float

DEFAULT_OUT = Path("data/gesn_base/gesn2022.parquet")

# ── категории расхода → kind ──────────────────────────────────────────
# Шапки категорий в PDF/JSON: «1 ЗАТРАТЫ ТРУДА РАБОЧИХ», «2 Затраты труда машинистов»,
# «3 МАШИНЫ И МЕХАНИЗМЫ», «4 МАТЕРИАЛЫ». «машинист» проверяем раньше «рабоч».
_CATEGORY_KIND: tuple[tuple[str, str], ...] = (
    ("труда машинист", "machinist"),
    ("затраты труда рабоч", "labor"),
    ("машины и механизм", "machine"),
    ("материал", "material"),
    ("оборудован", "material"),
)


def _kind_from_category(name: Any) -> Optional[str]:
    low = str(name or "").strip().casefold()
    for needle, kind in _CATEGORY_KIND:
        if needle in low:
            return kind
    return None


# Шифр нормы в PDF: «12-01-034» (таблица) и «12-01-034-02» (конкретная норма-колонка).
_TABLE_RE = re.compile(r"Таблица\s+ГЭСН\s+(\d{2}-\d{2}-\d{3})\b", re.IGNORECASE)
_FULL_NORM_RE = re.compile(r"^(\d{2}-\d{2}-\d{3}-\d{2})\b")
_COL_SUFFIX_RE = re.compile(r"^\d{3}-\d{2}$")           # «034-02» — короткая колонка
_MEASURE_RE = re.compile(r"Измеритель[:\s]+(.+?)(?:\s*$|\s*\()", re.IGNORECASE)
# Код ресурса ФГИС ЦС: «91.05.01-017», «01.7.15.06-0111», «1-100-25» (тариф ОЗП), «11.1.03.01-0063».
_RES_CODE_RE = re.compile(r"^(?:\d{2}\.[\d.]+(?:-\d+)?|\d-\d{3}-\d{2,3})$")
_NUM_RE = re.compile(r"^-?\d[\d.,]*$")
_CATEGORY_HEAD_RE = re.compile(r"^[1-9]$")              # «1»,«2»,«3»,«4» — номер категории

_UNITS = {"чел.-ч", "маш.-ч", "т", "м3", "м2", "м", "шт", "кг", "100", "1000",
          "кВт-ч", "ц", "км", "л", "пог.м"}


# ── PDF → нормы ───────────────────────────────────────────────────────

def _lines_with_words(page: Any) -> list[list[dict[str, Any]]]:
    """Слова страницы → строки (группировка по Y), внутри строки — по X."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    buckets: dict[int, list[dict[str, Any]]] = {}
    for w in words:
        buckets.setdefault(round(w["top"]), []).append(w)
    return [sorted(buckets[top], key=lambda w: w["x0"]) for top in sorted(buckets)]


def _line_text(line: list[dict[str, Any]]) -> str:
    return " ".join(w["text"] for w in line)


def _column_anchors(line: list[dict[str, Any]]) -> Optional[list[tuple[float, str]]]:
    """Строка-заголовок колонок («034-01 034-02 …») → [(x_center, суффикс)] или None."""
    pairs = [((w["x0"] + w["x1"]) / 2.0, w["text"]) for w in line if _COL_SUFFIX_RE.match(w["text"])]
    return pairs or None


def _values_by_column(
    line: list[dict[str, Any]], anchors: list[tuple[float, str]]
) -> dict[str, float]:
    """Числа строки-ресурса → {суффикс_колонки: значение} по ближайшей X-координате колонки."""
    out: dict[str, float] = {}
    for w in line:
        if not (_NUM_RE.match(w["text"]) and _safe_float(w["text"]) is not None):
            continue
        xc = (w["x0"] + w["x1"]) / 2.0
        col = min(anchors, key=lambda a: abs(a[0] - xc))
        val = _safe_float(w["text"])
        if val is not None:
            out[col[1]] = val
    return out


def _resource_row(line: list[dict[str, Any]]) -> Optional[tuple[str, str, str]]:
    """Строка-ресурс → (код_ресурса, наименование, ед.изм) или None (если не ресурс)."""
    if not line:
        return None
    first = line[0]["text"]
    if not _RES_CODE_RE.match(first):
        return None
    name_toks: list[str] = []
    unit = ""
    for w in line[1:]:
        tx = w["text"]
        is_num = _NUM_RE.match(tx) and _safe_float(tx) is not None
        if is_num and unit:
            break
        if tx in _UNITS or (tx.endswith("шт") and len(tx) < 7):
            unit = tx
            continue
        if not is_num:
            name_toks.append(tx)
    return first, " ".join(name_toks).strip(), unit


def parse_pdf(path: str | Path) -> list[dict[str, Any]]:
    """Официальный PDF ГЭСН-2022 → нормализованные строки-ресурсы (схема RESOURCE_FIELDS).

    Геометрический разбор: значение → колонка-норма по X. Категория («1 ЗАТРАТЫ…») задаёт kind.
    Возвращает по строке на (норма-колонка × ресурс).
    """
    import pdfplumber

    records: list[dict[str, Any]] = []
    cur_table = ""              # «12-01-034»
    cur_name = ""               # наименование таблицы
    cur_unit = ""               # «100 м2»
    cur_kind: Optional[str] = None
    anchors: list[tuple[float, str]] = []   # [(x, '034-02'), …]
    col_fullcode: dict[str, str] = {}       # '034-02' → '12-01-034-02'

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            for line in _lines_with_words(page):
                text = _line_text(line)

                m = _TABLE_RE.search(text)
                if m:
                    cur_table = m.group(1)
                    cur_name = text[m.end():].strip()
                    cur_unit, cur_kind = "", None
                    anchors, col_fullcode = [], {}
                    continue

                mu = _MEASURE_RE.search(text)
                if mu and cur_table:
                    cur_unit = mu.group(1).strip()
                    continue

                # строка варианта нормы: «12-01-034-02 имя»
                mf = _FULL_NORM_RE.match(text)
                if mf and cur_table and mf.group(1).startswith(cur_table):
                    full = mf.group(1)
                    suf = full[len(cur_table) + 1:]                 # «02»
                    col_key = f"{cur_table.split('-')[-1]}-{suf}"   # «034-02»
                    col_fullcode[col_key] = full
                    continue

                # заголовок колонок: «034-01 034-02 …»
                a = _column_anchors(line)
                if a and cur_table:
                    anchors = a
                    continue

                # категория: «1 ЗАТРАТЫ ТРУДА РАБОЧИХ» (машинисты — категория-ЛИСТ с расходом)
                if line and _CATEGORY_HEAD_RE.match(line[0]["text"]):
                    rest = _line_text(line[1:])
                    k = _kind_from_category(rest)
                    if k:
                        cur_kind = k
                        if anchors and k == "machinist":
                            for col_key, val in _values_by_column(line, anchors).items():
                                records.append(_mk(
                                    cur_table, cur_name, cur_unit, col_fullcode, col_key,
                                    kind="machinist", res_code="",
                                    res_name="Затраты труда машинистов",
                                    res_unit="чел.-ч", per_unit=val,
                                ))
                        continue

                # строка-ресурс
                if cur_table and cur_kind and anchors:
                    rr = _resource_row(line)
                    if rr:
                        rcode, rname, runit = rr
                        for col_key, val in _values_by_column(line, anchors).items():
                            records.append(_mk(
                                cur_table, cur_name, cur_unit, col_fullcode, col_key,
                                kind=cur_kind, res_code=rcode, res_name=rname,
                                res_unit=runit, per_unit=val,
                            ))
    return records


def _mk(table: str, name: str, unit: str, col_fullcode: dict[str, str], col_key: str,
        *, kind: str, res_code: str, res_name: str, res_unit: str,
        per_unit: float) -> dict[str, Any]:
    """Собрать нормализованную строку-ресурс. Тариф ОЗП/ОТм (1-…) → resource_code пустой."""
    full = col_fullcode.get(col_key) or f"{table}-{col_key.split('-')[-1]}"
    rec = {f: None for f in RESOURCE_FIELDS}
    rec["norm_code"] = _norm_code(full)
    rec["norm_name"] = name
    rec["norm_unit"] = unit
    rec["kind"] = kind
    rec["per_unit"] = per_unit
    # тарифные шифры рабочих/машинистов — НЕ код ресурса ФГИС ЦС (цена резолвится тарифом)
    rec["resource_code"] = "" if kind in ("labor", "machinist") else res_code
    rec["resource_name"] = res_name
    rec["resource_unit"] = res_unit
    rec["price"] = None
    return rec


# ── ФГИС ЦС JSON (структурированный официальный источник) ─────────────

_API = "https://fgiscs.minstroyrf.ru/api/FullTextSearch/SearchEstimatedRates?search="


def _strip_em(s: Any) -> str:
    return re.sub(r"</?em>", "", str(s or ""))


def parse_fgis_json(records_json: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ответ SearchEstimatedRates (список норм-таблиц) → строки-ресурсы (схема RESOURCE_FIELDS).

    ``normTableJson`` — колонки-нормы (number/name/meterName). ``normTableValueTableJson`` —
    строки расхода: категория-шапка (NormTablePartParentId=null, Cipher=«1»..«4») задаёт kind,
    дочерние строки — ресурсы (Cipher=код, NormTablePartNormValueList=[{NormNumber, Value}]).
    """
    out: list[dict[str, Any]] = []
    for rec in records_json:
        cols = rec.get("normTableJson")
        vals = rec.get("normTableValueTableJson")
        if isinstance(cols, str):
            cols = json.loads(cols)
        if isinstance(vals, str):
            vals = json.loads(vals)
        cols, vals = cols or [], vals or []
        col_meta: dict[str, tuple[str, str]] = {}
        for c in cols:
            col_meta[_strip_em(c.get("number"))] = (c.get("name") or "", c.get("meterName") or "")
        # дерево: parentId → kind (по шапке категории)
        kind_by_part: dict[Any, str] = {}
        for row in vals:
            if row.get("NormTablePartParentId") is None:
                k = _kind_from_category(row.get("Name"))
                if k:
                    kind_by_part[row.get("NormTablePartId")] = k
        for row in vals:
            value_list = row.get("NormTablePartNormValueList") or []
            if not value_list:
                continue                       # шапка категории — без расхода
            kind = kind_by_part.get(row.get("NormTablePartParentId"))
            if kind is None:                   # категория-лист (машинисты)
                kind = _kind_from_category(row.get("Name")) or "material"
            cipher = str(row.get("Cipher") or "")
            rname = row.get("Name") or ""
            runit = row.get("UnitName") or ""
            for v in value_list:
                num = _strip_em(v.get("NormNumber"))
                per_unit = _safe_float(v.get("Value"))
                if per_unit is None:
                    continue
                name, unit = col_meta.get(num, ("", ""))
                rec_out = {f: None for f in RESOURCE_FIELDS}
                rec_out["norm_code"] = _norm_code(num)
                rec_out["norm_name"] = name
                rec_out["norm_unit"] = unit
                rec_out["kind"] = kind
                rec_out["per_unit"] = per_unit
                rec_out["resource_code"] = "" if kind in ("labor", "machinist") else cipher
                rec_out["resource_name"] = rname
                rec_out["resource_unit"] = runit
                rec_out["price"] = None
                out.append(rec_out)
    return out


def fetch_fgis(code: str, curl_prefix: str) -> list[dict[str, Any]]:
    """Скачать норму(ы) из ФГИС ЦС по коду через произвольный curl-префикс (egress-VPS).

    ``curl_prefix`` — например ``"ssh root@HOST curl -sS"``; к нему добавляется URL.
    Возвращает сырой список записей SearchEstimatedRates.
    """
    import urllib.parse

    url = _API + urllib.parse.quote(code, safe="")
    cmd = curl_prefix.split() + [url]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"curl failed ({res.returncode}): {res.stderr[:200]}")
    return json.loads(res.stdout)


# ── сборка Parquet ────────────────────────────────────────────────────

def build_parquet(records: list[dict[str, Any]], out_path: str | Path = DEFAULT_OUT,
                  *, append: bool = False) -> dict[str, Any]:
    """Строки-ресурсы → нормализованный Parquet (схема gesn_import). append — дописать к базе."""
    import pandas as pd

    records = [r for r in records if r.get("per_unit") is not None or r.get("resource_name")]
    if not records:
        raise ValueError("Не распознано ни одной строки-ресурса")
    df = pd.DataFrame(records, columns=list(RESOURCE_FIELDS))

    out_path = Path(out_path)
    if append and out_path.exists():
        old = pd.read_parquet(out_path)
        df = pd.concat([old, df], ignore_index=True)
        df = df.drop_duplicates(subset=["norm_code", "kind", "resource_code", "resource_name"],
                                keep="last")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, compression="snappy", index=False)
    norm_codes = sorted({r["norm_code"] for r in records if r["norm_code"]})
    return {"parquet": str(out_path), "norms": len(norm_codes), "resources": len(df)}


def _main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Импорт официального ФСНБ-2022 (ГЭСН) → Parquet")
    ap.add_argument("src", nargs="?", help="PDF сборника ГЭСН (для --from pdf)")
    ap.add_argument("--from", dest="source", default="pdf", choices=("pdf", "fgis"),
                    help="источник: pdf (официальный PDF) | fgis (ФГИС ЦС JSON по коду)")
    ap.add_argument("--code", help="код нормы/таблицы для --from fgis (напр. 12-01-034)")
    ap.add_argument("--curl", default="curl -sS", help="curl-префикс для --from fgis (egress)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"Parquet (по умолч. {DEFAULT_OUT})")
    ap.add_argument("--append", action="store_true", help="дописать к существующей базе")
    args = ap.parse_args(list(argv) if argv is not None else None)

    try:
        if args.source == "pdf":
            if not args.src or not Path(args.src).is_file():
                print(f"PDF не найден: {args.src}", file=sys.stderr)
                return 2
            records = parse_pdf(args.src)
        else:
            if not args.code:
                print("--from fgis требует --code", file=sys.stderr)
                return 2
            records = parse_fgis_json(fetch_fgis(args.code, args.curl))
        summary = build_parquet(records, args.out, append=args.append)
    except (ValueError, RuntimeError) as e:
        print(f"Ошибка импорта: {e}", file=sys.stderr)
        return 1
    print(f"OK: {summary['norms']} норм / {summary['resources']} ресурсов → {summary['parquet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
