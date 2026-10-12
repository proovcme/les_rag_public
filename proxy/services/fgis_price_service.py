"""ФГИС ЦС — ценовая база из «Сплит-формы» (сметные цены + индексы по коду ресурса).

Назначение
==========
«Сплит-форма» ФГИС ЦС — это справочник сметных цен и индексов на 161k–281k строк
(регион × квартал). Доступ к ней — **точечный lookup по точному коду ресурса**
(напр. ``91.05.01-017`` краны, ``01.7.15.06-0111`` гвозди), а НЕ нечёткая агрегация.
Поэтому это отдельный сервис, а не путь row-normalizer/Qdrant: 281k строк в векторный
индекс — мусор, а нужен O(1) поиск по ключу (ADR-11: числа считает код, не LLM).

Это закрывает узкое место ``table_query top-k не SQL`` для автоценообразования ЛСР:
здесь — детерминированный exact-match по коду из in-memory индекса поверх Parquet.

Структура «Сплит-формы» (вскрыта на реальных файлах СПб 2 кв. 2025/2026)
-----------------------------------------------------------------------
Шапка таблицы — строка с ячейкой «Код ресурса, услуги» (обычно ~18-я), ниже строка
нумерации колонок «1 2 … 9», затем данные. 9 колонок:

1. Код ресурса, услуги                  → ``code``           (ключ)
2. Наименование строительного ресурса   → ``name``
3. Единица измерения                    → ``unit``
4. Отпускная цена (базовый уровень)      → ``price_release``
5. Сметная цена (базовый уровень)        → ``price_base``
6. Номер группы однородных ресурсов      → ``group_no``
7. Наименование группы                  → ``group_name``
8. Сметная цена в текущем уровне, руб.   → ``price_current``  (часто «-»)
9. Индекс изменения к группе            → ``index``

Текущая цена: ``price_current`` если число, иначе ``price_base × index`` (ресурсно-
индексный механизм). Считается на этапе конвертации и кладётся в ``price_current_eff``.
"""

from __future__ import annotations

import bisect
import heapq
import math
import re
import os
import json
import threading
import hashlib
from io import BytesIO
from copy import deepcopy
from collections import defaultdict, OrderedDict
from functools import lru_cache
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any, Iterable, Mapping, Optional
from proxy.smeta_core.norm_revision import revision_fingerprint, NormRevisionConflict

PRICEBOOK_IDENTITY_SCHEMA = 'les.pricebook-revision.v1'
PRICEBOOK_IDENTITY_FIELDS = ('schema', 'sha256', 'pricebook_id', 'region', 'period', 'version')


class PriceBookRevisionConflict(ValueError):
    def __init__(self, expected: Mapping[str, Any] | None, actual: Mapping[str, Any] | None, reason: str):
        self.expected = deepcopy(dict(expected or {}))
        self.actual = deepcopy(dict(actual or {}))
        self.reason = reason
        super().__init__(reason)

# Нормализованная схема одной строки ценовой базы.
PRICE_FIELDS = (
    "code",
    "name",
    "unit",
    "price_release",
    "price_base",
    "group_no",
    "group_name",
    "price_current",
    "index",
    "price_current_eff",
)

# Сопоставление «подстрока заголовка → поле». Порядок важен: «текущем» проверяем
# раньше «сметная цена», иначе колонка 8 перехватит базовую (колонку 5).
_HEADER_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("code", ("код ресурс", "код ресурса")),
    ("name", ("наименование строительного ресурс", "наименование ресурс")),
    ("unit", ("единица измер", "ед. измер", "ед.изм")),
    ("price_release", ("отпускная цена",)),
    ("price_current", ("сметная цена в текущем", "текущем уровне")),
    ("price_base", ("сметная цена",)),  # базовая — после «текущей»
    ("group_no", ("номер группы",)),
    ("group_name", ("наименование группы",)),
    ("index", ("индекс изменения", "индекс")),
)

# Код ресурса: «01.1.01.01-0002», «91.05.01-017», возможно с буквенным префиксом базы
# («ФСБЦ-…», «ФССЦ-…», «ФСЭМ-…»). Для матча префикс снимаем.
_CODE_RE = re.compile(r"\d{2}[.\d-]{4,}")
_PREFIX_RE = re.compile(r"^[А-ЯA-Zа-яa-z]{2,6}[-_]")


def _safe_float(value: Any) -> Optional[float]:
    """'34 458,33' / '1.25' / '-' / None → float | None (как в parquet_writer)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—", "–", "x", "х", "X", "Х"}:
        return None
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def normalize_code(code: Any) -> str:
    """Канонический ключ кода: trim, снять буквенный префикс базы (ФСБЦ-/ФССЦ-…)."""
    text = re.sub(r"\s+", "", str(code or "")).strip()
    if not text:
        return ""
    stripped = _PREFIX_RE.sub("", text)
    return stripped or text


def _search_text(value: Any) -> str:
    """Canonical lexical form for model-visible price browsing, never a selector."""
    text = str(value or "").casefold().replace("ё", "е")
    return " ".join(re.findall(r"[0-9a-zа-я]+", text))


def _search_tokens(value: Any) -> list[str]:
    return [token for token in _search_text(value).split() if len(token) >= 2]


# Грубая основа слова для поиска карточек цен. Живая проверка 17.09: запрос «ковровая
# плитка» не совпадал с «Покрытие ковровое», и модель не увидела ковровое покрытие вовсе.
# Это порядок свидетельств, а не выбор: код ФССЦ по-прежнему выбирает модель.
_RU_ENDINGS = tuple(sorted(
    "ами ями ого его ому ему ыми ими ых их ая яя ое ее ые ие ый ий ой ей ую юю ов ев ом ем ах ях "
    "ам ям ия ии ью ы и а я о е у ю ь й".split(), key=len, reverse=True))
_CYRILLIC_WORD = re.compile(r"[а-я]+")


def _search_stem(token: str) -> str:
    if not _CYRILLIC_WORD.fullmatch(token):
        return token
    for ending in _RU_ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 4:
            return token[: -len(ending)]
    return token


def _stem_variants(stem: str, index: Mapping[str, list[int]], keys: list[str]) -> dict[str, float]:
    """Основы справочника, совпадающие с основой запроса: точно — 1.0, по началу слова — 0.7."""
    out: dict[str, float] = {}
    if stem in index:
        out[stem] = 1.0
    if len(stem) >= 4 and _CYRILLIC_WORD.fullmatch(stem):
        start = bisect.bisect_left(keys, stem)
        while start < len(keys) and keys[start].startswith(stem):
            if len(keys[start]) - len(stem) <= 3:
                out.setdefault(keys[start], 0.7)
            start += 1
        for size in range(max(4, len(stem) - 3), len(stem)):
            if stem[:size] in index:
                out.setdefault(stem[:size], 0.7)
    return out


HEAD_WORD_BOOST = 1.6


def _name_family(name: Any) -> str:
    """Первые два слова наименования: семейство однотипных строк справочника."""
    words = [_search_stem(token) for token in _search_tokens(name) if _CYRILLIC_WORD.fullmatch(token)]
    return " ".join(words[:2])


def _is_transport_row(rec: dict[str, Any]) -> bool:
    code = normalize_code(rec.get("code"))
    name = _search_text(rec.get("name"))
    return bool(re.fullmatch(r"\d{6}-\d{2}-\d{4}-\d{4}", code)) or name.startswith("перевозка ")


def _is_resource_code(code: str) -> bool:
    return bool(re.fullmatch(r"\d{2}(?:\.\d+)+-\d+", normalize_code(code)))


def _looks_like_code(value: Any) -> bool:
    return bool(_CODE_RE.search(str(value or "")))


# ─────────────────────────────────────────
# ПАРСИНГ «СПЛИТ-ФОРМЫ»
# ─────────────────────────────────────────

def parse_split_form(xlsx_path: str | Path, *, max_header_scan: int = 60) -> dict[str, Any]:
    """Читает «Сплит-форму» → {'meta': {...}, 'rows': [ {PRICE_FIELDS...}, ... ]}.

    0 LLM: шапка ищется по ячейке «Код ресурса», колонки — по подстрокам заголовка.
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    meta: dict[str, Any] = {}
    header_idx = 0
    col_map: dict[int, str] = {}

    # 1) Найти строку-шапку (содержит «код ресурс») и собрать meta из строк выше.
    for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_header_scan, values_only=True), 1):
        cells = [("" if c is None else str(c)).strip() for c in row]
        low0 = cells[0].casefold() if cells else ""
        # Мета берём только из «label | значение»-строк (метка в кол.0, короткое значение
        # в кол.1) — иначе абзацы-примечания со словом «субъект» попадают как регион.
        val1 = cells[1] if len(cells) > 1 else ""
        if "наименование субъект" in low0 and 0 < len(val1) < 80:
            meta.setdefault("subject", val1)
        if "наименование зоны" in low0 and 0 < len(val1) < 80:
            meta.setdefault("zone", val1)
        if any("код ресурс" in c.casefold() for c in cells):
            header_idx = r_idx
            for col_pos, cell in enumerate(cells):
                low = cell.casefold()
                for field, needles in _HEADER_MATCHERS:
                    if field in col_map.values():
                        continue
                    if any(n in low for n in needles):
                        col_map[col_pos] = field
                        break
            break

    if not header_idx or "code" not in col_map.values():
        wb.close()
        raise ValueError(f"Шапка «Сплит-формы» не найдена в {Path(xlsx_path).name}")

    # 2) Данные: пропускаем строку нумерации колонок, читаем строки с валидным кодом.
    code_col = next(pos for pos, f in col_map.items() if f == "code")
    rows: list[dict[str, Any]] = []
    num_fields = {"price_release", "price_base", "price_current", "index"}

    for row in ws.iter_rows(min_row=header_idx + 1, values_only=True):
        if code_col >= len(row):
            continue
        code_cell = row[code_col]
        if not _looks_like_code(code_cell):
            continue
        rec: dict[str, Any] = {f: None for f in PRICE_FIELDS}
        for pos, field in col_map.items():
            val = row[pos] if pos < len(row) else None
            if field in num_fields:
                rec[field] = _safe_float(val)
            elif field == "group_no":
                rec[field] = ("" if val is None else str(val).strip())
            else:
                rec[field] = ("" if val is None else str(val).strip())
        # Эффективная текущая цена: прямая (кол.8) или база×индекс (ресурсно-индексный).
        eff = rec["price_current"]
        if eff is None and rec["price_base"] is not None and rec["index"] is not None:
            eff = round(rec["price_base"] * rec["index"], 2)
        rec["price_current_eff"] = eff
        rows.append(rec)

    wb.close()
    return {"meta": meta, "rows": rows}


def build_price_parquet(
    xlsx_path: str | Path,
    out_path: str | Path,
    *,
    region: str | None = None,
    quarter: str | None = None,
) -> dict[str, Any]:
    """«Сплит-форма» xlsx → Parquet (нормализованный, с region/quarter). Возвращает сводку."""
    import pandas as pd

    parsed = parse_split_form(xlsx_path)
    rows = parsed["rows"]
    region = region or parsed["meta"].get("subject") or ""
    quarter = quarter or ""

    df = pd.DataFrame(rows, columns=list(PRICE_FIELDS))
    df["region"] = region
    df["quarter"] = quarter

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, compression="snappy", index=False)

    return {
        "parquet": str(out_path),
        "rows": len(rows),
        "region": region,
        "quarter": quarter,
        "meta": parsed["meta"],
    }


# ─────────────────────────────────────────
# КНИГА ЦЕН (lookup)
# ─────────────────────────────────────────

class PriceBook:
    """Индекс ценовой базы для exact-match по коду + поиск по наименованию.

    Грузится один раз из Parquet, держит ``{нормализованный_код: строка}``.
    """

    def __init__(self, rows: list[dict[str, Any]], *, region: str = "", quarter: str = ""):
        self._identity = dict(schema=PRICEBOOK_IDENTITY_SCHEMA, sha256=None, pricebook_id=None,
            region=region, period=quarter, version=None)
        self._rows = [deepcopy(rec) for rec in rows]
        self._row_ordinals = {id(rec): number for number, rec in enumerate(self._rows, 1)}
        self._candidates: dict[str, list[dict[str, Any]]] = {}
        self._by_code: dict[str, dict[str, Any]] = {}
        for rec in self._rows:
            key = normalize_code(rec.get("code"))
            if key:
                candidates = self._candidates.setdefault(key, [])
                if not any(rec == candidate for candidate in candidates):
                    candidates.append(rec)
        self._by_code = {key: candidates[0] for key, candidates in self._candidates.items() if len(candidates) == 1}
        self._lexicon: tuple[dict[str, list[int]], list[str], dict[str, int], frozenset[int]] | None = None
        self._lexicon_lock = threading.Lock()
        self._heads: dict[str, frozenset[int]] = {}

    @classmethod
    def from_parquet(cls, parquet_path: str | Path) -> "PriceBook":
        return get_pricebook(str(parquet_path))

    @property
    def identity(self) -> dict[str, Any]:
        return deepcopy(self._identity)

    @property
    def region(self) -> str:
        return self._identity['region']

    @property
    def quarter(self) -> str:
        return self._identity['period']

    def _record_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(record)
        ordinal = self._row_ordinals[id(record)]
        result['price_record_identity'] = dict(schema='les.price-record.v1',
            pricebook_identity=self.identity, source_row=ordinal, record_id=f'row:{ordinal}')
        return result

    def __len__(self) -> int:
        return len(self._candidates)

    def lookup(self, code: str) -> Optional[dict[str, Any]]:
        """Точная цена по коду (с учётом снятия префикса базы). None если нет."""
        record = self._by_code.get(normalize_code(code))
        return self._record_payload(record) if record is not None else None

    def lookup_diagnostic(self, code: str) -> dict[str, Any]:
        key = normalize_code(code)
        candidates = self._candidates.get(key, [])
        return dict(status='missing' if not candidates else 'resolved' if len(candidates) == 1 else 'ambiguous',
            code=key, candidates=[self._record_payload(record) for record in candidates])

    def price(self, code: str, *, method: str = "index") -> Optional[float]:
        """Цена по коду: method='index' → текущая (база×индекс/прямая), 'base' → базовая."""
        rec = self.lookup(code)
        if rec is None:
            return None
        return rec.get("price_current_eff") if method == "index" else rec.get("price_base")

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Поиск по подстроке наименования/кода — когда точный код неизвестен."""
        q = (query or "").strip().casefold()
        if not q:
            return []
        out: list[dict[str, Any]] = []
        for rec in self._rows:
            hay = f"{rec.get('code','')} {rec.get('name','')}".casefold()
            if q in hay:
                out.append(self._record_payload(rec))
                if len(out) >= limit:
                    break
        return out

    def browse(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Ranked lexical candidates for a model/user to inspect.

        This is deliberately not fuzzy auto-binding. The method returns multiple
        FGIS rows with an explicit lexical trace; only a model or user may bind a
        project material to one exact resource code afterwards.
        """
        phrase = _search_text(query)
        tokens = _search_tokens(query)
        exact_code = normalize_code(query)
        if not phrase and not exact_code:
            return []
        limit = max(1, int(limit))
        asks_transport = any(token in {"перевозка", "доставка", "транспорт", "транспортировка"} for token in tokens)
        index, keys, position_by_code, transport_rows = self._lexical_index()
        total = max(len(self._rows), 1)
        stem_tokens: dict[str, str] = {}
        for token in tokens:
            stem_tokens.setdefault(_search_stem(token), token)
        # Вес слова — его редкость в справочнике: «ковровое» или «оповещатель» говорят об
        # изделии больше, чем «мм», «серая» или «500х500». Ранние слова запроса называют
        # изделие, поздние — его признаки; размеры и марки весят меньше слов.
        weight: dict[int, float] = defaultdict(float)
        matched: dict[int, list[str]] = defaultdict(list)
        for order, (stem, token) in enumerate(stem_tokens.items()):
            best: dict[int, float] = {}
            for key, factor in _stem_variants(stem, index, keys).items():
                value = math.log(1.0 + total / len(index[key])) * factor / (1.0 + 0.25 * order)
                if any(char.isdigit() for char in stem):
                    value *= 0.3
                heads = self._heads.get(key, frozenset())
                for position in index[key]:
                    # В наименовании ФССЦ изделие названо первыми словами: «Покрытие
                    # ковровое» — это ковровое покрытие, а «Антисептик для ковровых
                    # покрытий» — нет (живая проверка 17.09, проход 4).
                    scored = value * HEAD_WORD_BOOST if position in heads else value
                    if scored > best.get(position, 0.0):
                        best[position] = scored
            for position, value in best.items():
                weight[position] += value
                matched[position].append(token)
        exact_position = position_by_code.get(exact_code) if exact_code else None
        if exact_position is not None:
            weight.setdefault(exact_position, 0.0)
        candidates: list[tuple[tuple[int, int, int, float], int]] = []
        for position, value in weight.items():
            code_match = int(position == exact_position)
            # A material browser must not rank haulage tariffs as material prices.
            # They stay available for an explicit transport query or exact code.
            if position in transport_rows and not (asks_transport or code_match):
                continue
            rec = self._rows[position]
            code = normalize_code(rec.get("code"))
            phrase_match = 0
            if phrase and len(matched[position]) == len(stem_tokens):
                phrase_match = int(phrase in f"{code.casefold()} {_search_text(rec.get('name'))}")
            candidates.append(((code_match, int(_is_resource_code(code)), phrase_match, value), position))
        pool = heapq.nlargest(max(limit * 8, 64), candidates, key=lambda item: item[0])
        pool.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], -item[0][3],
                                    _search_text(self._rows[item[1]].get("name")),
                                    normalize_code(self._rows[item[1]].get("code"))))
        # Одно семейство однотипных строк (шесть размеров стеклянной мозаики) не должно
        # закрывать остальные изделия: каждая следующая строка семейства весит меньше, но не
        # ниже половины своего веса — иначе хорошо совпавшие варианты (витая пара 1х2, 2х2,
        # 4х2) уступали бы случайным строкам с одним общим словом.
        chosen: list[tuple[tuple[int, int, int, float], int]] = []
        family_of = [_name_family(self._rows[position].get("name")) for _, position in pool]
        families: dict[str, int] = defaultdict(int)
        while pool and len(chosen) < limit:
            best_index = max(range(len(pool)), key=lambda i: (
                pool[i][0][0], pool[i][0][1], pool[i][0][2],
                pool[i][0][3] * max(0.7 ** families[family_of[i]], 0.5), -i))
            families[family_of.pop(best_index)] += 1
            chosen.append(pool.pop(best_index))
        out: list[dict[str, Any]] = []
        for (code_match, resource_code, phrase_match, value), position in chosen:
            payload = self._record_payload(self._rows[position])
            # Sort keys are evidence only: exact code, resource-code family, full phrase,
            # weighted token coverage. No applicability lives here.
            payload["match"] = {
                "schema": "fgis_price_lexical_match_v1",
                "query": str(query or ""),
                "exact_code": bool(code_match),
                "phrase_match": bool(phrase_match),
                "all_tokens": bool(stem_tokens) and len(matched[position]) == len(stem_tokens),
                "matched_tokens": list(matched[position]),
                "query_tokens": tokens,
                "score": round(value, 4),
                "resource_code": bool(resource_code),
                "transport_row": position in transport_rows,
            }
            out.append(payload)
        return out

    def _lexical_index(self) -> tuple[dict[str, list[int]], list[str], dict[str, int], frozenset[int]]:
        """Основы слов → строки справочника; строится один раз на книгу при первом поиске."""
        if self._lexicon is None:
            with self._lexicon_lock:
                if self._lexicon is None:
                    stems: dict[str, str] = {}
                    index: dict[str, list[int]] = defaultdict(list)
                    position_by_code: dict[str, int] = {}
                    transport: set[int] = set()
                    heads: dict[str, set[int]] = defaultdict(set)
                    for position, rec in enumerate(self._rows):
                        code = normalize_code(rec.get("code"))
                        position_by_code.setdefault(code, position)
                        if _is_transport_row(rec):
                            transport.add(position)
                        name_words = _search_tokens(rec.get("name"))
                        words = set(_search_tokens(code)) | set(name_words)
                        for stem in {stems.get(word) or stems.setdefault(word, _search_stem(word)) for word in words}:
                            index[stem].append(position)
                        # Голова наименования — те же два первых русских слова, что и у
                        # _name_family, без повторного разбора строки.
                        head = [stems[word] for word in name_words if _CYRILLIC_WORD.fullmatch(word)][:2]
                        for stem in head:
                            heads[stem].add(position)
                    self._heads = {stem: frozenset(positions) for stem, positions in heads.items()}
                    self._lexicon = (dict(index), sorted(index), position_by_code, frozenset(transport))
        return self._lexicon

    def lookup_many(self, codes: Iterable[str]) -> dict[str, Optional[dict[str, Any]]]:
        return {c: self.lookup(c) for c in codes}


DEFAULT_PRICE_ROOT = mutable_path("data/price_base")
PRICEBOOK_MANIFEST_PATH = Path("config/domain/pricebook_manifest.json")
_SCRATCH_PRICEBOOK_STEMS = {"spb_refresh"}
_DEFAULT_PRICEBOOK_STEMS = (
    "sankt-peterburg_2kv2026",
    "spb_2kv2026",
    "spb_2kv2025",
    "sankt-peterburg_2kv2025",
)


_retained_pricebooks: OrderedDict[tuple[str, str], PriceBook] = OrderedDict()
_pricebook_cache_lock = threading.RLock()


def _price_stamp(path: Path):
    try:
        return revision_fingerprint(path)
    except (OSError, NormRevisionConflict) as error:
        raise PriceBookRevisionConflict(None, None, 'pricebook_source_unreadable') from error


def _file_metadata(rows: list[dict[str, Any]], identity: dict[str, Any]) -> tuple[str, str, Any]:
    result = []
    for field, aliases in (('region', ('region',)), ('period', ('quarter', 'period')), ('version', ('version', 'source_version'))):
        values = set()
        present = any(any(alias in row for alias in aliases) for row in rows)
        if present:
            for row in rows:
                available = {str(row[alias]).strip() if row.get(alias) not in (None, '') else None for alias in aliases if alias in row}
                values.update(available)
        if len(values) > 1:
            raise PriceBookRevisionConflict(None, dict(identity, metadata_conflict=dict(field=field, values=sorted(values, key=lambda value: str(value)))), 'pricebook_metadata_mixed:' + field)
        value = next(iter(values)) if values else None
        result.append(value if field == 'version' else value or '')
    return tuple(result)


@lru_cache(maxsize=8)
def _load_pricebook_revision(path: str, sha256: str) -> PriceBook:
    import pandas as pd
    from pyarrow import ArrowInvalid, ArrowNotImplementedError

    source = Path(path)
    stamp = _price_stamp(source)
    try:
        payload = source.read_bytes()
    except OSError as error:
        raise PriceBookRevisionConflict(None, None, 'pricebook_source_unreadable') from error
    identity = dict(schema=PRICEBOOK_IDENTITY_SCHEMA, sha256=hashlib.sha256(payload).hexdigest(), pricebook_id=source.stem)
    if identity['sha256'] != sha256:
        raise PriceBookRevisionConflict(None, identity, 'pricebook_revision_changed_before_decode')
    try:
        frame = pd.read_parquet(BytesIO(payload))
    except (ArrowInvalid, ArrowNotImplementedError) as error:
        raise PriceBookRevisionConflict(None, identity, 'pricebook_source_invalid') from error
    except OSError as error:
        raise PriceBookRevisionConflict(None, identity, 'pricebook_source_unreadable') from error
    if _price_stamp(source) != stamp:
        raise PriceBookRevisionConflict(None, identity, 'pricebook_revision_changed_during_read')
    frame = frame.astype(object).where(pd.notnull(frame), None)
    rows = frame.to_dict(orient='records')
    region, period, version = _file_metadata(rows, identity)
    book = PriceBook(rows, region=region, quarter=period)
    book._identity = dict(identity, region=region, period=period, version=version)
    return book


def get_pricebook(parquet_path: str, *, expected_identity: Mapping[str, Any] | None = None) -> PriceBook:
    path = Path(parquet_path).resolve()
    expected = dict(expected_identity) if expected_identity is not None else None
    if expected is not None:
        with _pricebook_cache_lock:
            retained = _retained_pricebooks.get((str(path), str(expected.get('sha256') or '')))
        if retained is not None:
            if retained.identity != expected:
                raise PriceBookRevisionConflict(expected, retained.identity, 'pricebook_identity_mismatch')
            return retained
    try:
        stamp = _price_stamp(path)
        # New unpinned boundaries verify actual bytes: filesystem timestamps can collide.
        # Pinned document reads return the retained book above; row lookups never hash files.
        try:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise PriceBookRevisionConflict(None, None, 'pricebook_source_unreadable') from error
        if _price_stamp(path) != stamp:
            raise PriceBookRevisionConflict(expected, {'sha256': sha256}, 'pricebook_revision_changed_during_read')
        book = _load_pricebook_revision(str(path), sha256)
        # A same-size rewrite during decoding can retain the same filesystem
        # fingerprint. Validate bytes again at this unpinned read boundary;
        # retained pinned snapshots above still avoid repeated file reads.
        try:
            after_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise PriceBookRevisionConflict(expected, None, 'pricebook_source_unreadable') from error
        if after_sha256 != sha256 or _price_stamp(path) != stamp:
            raise PriceBookRevisionConflict(expected, {'sha256': after_sha256}, 'pricebook_revision_changed_after_cache_read')
    except PriceBookRevisionConflict as error:
        if expected is not None and not error.expected:
            raise PriceBookRevisionConflict(expected, error.actual, error.reason) from error
        raise
    if expected is not None and book.identity != expected:
        raise PriceBookRevisionConflict(expected, book.identity, 'pricebook_identity_mismatch')
    key = (str(path), str(book.identity['sha256']))
    with _pricebook_cache_lock:
        _retained_pricebooks[key] = book
        _retained_pricebooks.move_to_end(key)
        while len(_retained_pricebooks) > 8:
            _retained_pricebooks.popitem(last=False)
    return book


def _clear_pricebook_cache() -> None:
    with _pricebook_cache_lock:
        _load_pricebook_revision.cache_clear()
        _retained_pricebooks.clear()


get_pricebook.cache_clear = _clear_pricebook_cache
get_pricebook.cache_info = _load_pricebook_revision.cache_info


def capture_price_basis(requested_pricebook: str | None = None) -> dict[str, Any]:
    explicit = Path(requested_pricebook) if requested_pricebook else None
    path = str(explicit.resolve()) if explicit is not None and explicit.is_absolute() else resolve_pricebook_path(requested_pricebook)
    if not path:
        if requested_pricebook:
            raise PriceBookRevisionConflict(None, None, 'pricebook_requested_unavailable')
        return dict(schema='les.document-price-basis.v1', status='not_configured', path=None, identity=None)
    resolved = str(Path(path).resolve())
    return dict(schema='les.document-price-basis.v1', status='pinned', path=resolved, identity=get_pricebook(resolved).identity)


def pricebook_for_basis(basis: Mapping[str, Any]) -> PriceBook | None:
    if basis.get('status') in {'not_configured', 'legacy_unpinned'}:
        return None
    if basis.get('schema') != 'les.document-price-basis.v1' or basis.get('status') != 'pinned' or not basis.get('path') or not isinstance(basis.get('identity'), Mapping):
        raise PriceBookRevisionConflict(None, None, 'document_price_basis_invalid')
    return get_pricebook(str(basis['path']), expected_identity=basis['identity'])


def _is_scratch_pricebook(path: str | Path) -> bool:
    return Path(path).stem in _SCRATCH_PRICEBOOK_STEMS or Path(path).stem.endswith("_refresh")


@lru_cache(maxsize=1)
def pricebook_manifest() -> dict[str, Any]:
    """Operator-maintained visibility/alias manifest for local pricebooks."""
    try:
        if PRICEBOOK_MANIFEST_PATH.exists():
            data = json.loads(PRICEBOOK_MANIFEST_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        return {}
    return {}


def _manifest_aliases() -> dict[str, str]:
    raw = pricebook_manifest().get("aliases")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        src = str(key or "").strip()
        dst = str(val or "").strip()
        if src and dst and src != dst:
            out[src] = dst
    return out


def _manifest_hidden_stems() -> set[str]:
    raw = pricebook_manifest().get("hidden_stems")
    hidden = {str(item or "").strip() for item in raw if str(item or "").strip()} if isinstance(raw, list) else set()
    quarantined = pricebook_manifest().get("quarantined_stems")
    if isinstance(quarantined, dict):
        hidden.update(str(item or "").strip() for item in quarantined if str(item or "").strip())
    return hidden


def _canonical_stem(stem: str, stems: set[str]) -> str:
    aliases = _manifest_aliases()
    seen: set[str] = set()
    current = str(stem or "").strip()
    while current and current in aliases and current not in seen:
        seen.add(current)
        candidate = aliases[current]
        if candidate not in stems:
            break
        current = candidate
    return current or stem


def _is_hidden_pricebook(path: str | Path, stems: set[str]) -> bool:
    stem = Path(path).stem
    if _is_scratch_pricebook(path):
        return False
    manifest = pricebook_manifest()
    quarantined = manifest.get("quarantined_stems")
    if isinstance(quarantined, dict) and stem in quarantined:
        # A quarantined regional identity is unsafe even when there is no
        # canonical alias in this particular directory.
        return True
    if stem not in _manifest_hidden_stems():
        return False
    canonical = _canonical_stem(stem, stems)
    # Do not hide a legacy alias in isolated test/dev roots unless its canonical
    # replacement is physically present in the same root.
    return canonical != stem and canonical in stems


def available_pricebooks(
    root: str | Path = DEFAULT_PRICE_ROOT,
    *,
    include_scratch: bool = False,
    include_hidden: bool = False,
) -> list[str]:
    root = Path(root)
    if not root.exists():
        return []
    paths = sorted(root.glob("*.parquet"))
    stems = {p.stem for p in paths}
    if not include_scratch:
        paths = [p for p in paths if not _is_scratch_pricebook(p)]
    if not include_hidden:
        paths = [p for p in paths if not _is_hidden_pricebook(p, stems)]
    return [str(p) for p in paths]


def resolve_pricebook_path(
    book: str | None = None,
    *,
    root: str | Path = DEFAULT_PRICE_ROOT,
    allow_scratch: bool = False,
) -> Optional[str]:
    """Resolve a pricebook stem/path to a local Parquet path.

    With no explicit book use the deterministic system default. This keeps
    chat, LSR traces and price lookup on the same region/period instead of
    accidentally using the first alphabetic Parquet file.
    """
    try:
        books = available_pricebooks(
            root,
            include_scratch=allow_scratch or bool(book),
            include_hidden=bool(book),
        )
    except TypeError:
        # Backward-compatible with old tests/plugins that monkeypatch the
        # function before the include_scratch keyword existed.
        books = available_pricebooks(root)
    if not books:
        return None
    stems = {Path(path).stem: path for path in books}
    if book:
        stem = _canonical_stem(Path(book).stem, set(stems))
        return stems.get(stem)

    preferred: list[str] = []
    configured = os.getenv("LES_DEFAULT_PRICEBOOK", "").strip()
    if configured:
        preferred.append(Path(configured).stem)
    manifest_default = str(pricebook_manifest().get("default_book") or "").strip()
    if manifest_default:
        preferred.append(Path(manifest_default).stem)
    preferred.extend(_DEFAULT_PRICEBOOK_STEMS)
    preferred.extend(stem for stem in sorted(stems) if "2026" in stem)
    preferred.extend(sorted(stems))

    seen: set[str] = set()
    for stem in preferred:
        if stem in seen:
            continue
        seen.add(stem)
        path = stems.get(stem)
        if path:
            return path
    return books[0]
