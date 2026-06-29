"""SQLite-light norm index for smeta harness candidate search.

This is a typed search projection over the existing GESN/FSM/TER norm sources.
It is not a second source of truth: norms still come from ``gesn_service``.
The store gives the model-first harness a cleaner candidate pool with explicit
base type, collection, unit, resources and model-readable norm cards.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from threading import RLock
from typing import Any, Iterable


_BARE_CODE_RE = re.compile(r"(?<!\d)(\d{2}-\d{2}-\d{3}-\d{2})")

_COLLECTION_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "01": ("earthworks",),
    "05": ("foundation",),
    "06": ("concrete_monolithic", "foundation"),
    "07": ("concrete_precast",),
    "08": ("masonry", "waterproofing"),
    "09": ("metal",),
    "10": ("wood",),
    "11": ("floors",),
    "12": ("roofing", "waterproofing"),
    "15": ("finishes",),
    "16": ("mep",),
    "17": ("mep",),
    "18": ("mep",),
    "20": ("mep",),
    "21": ("mep",),
    "22": ("mep",),
    "ГЭСНм38": ("metal",),
}

_FAMILY_TITLE_HINTS: dict[str, tuple[str, ...]] = {
    "earthworks": ("грунт", "котлован", "транше", "выемк", "насып", "землян", "разработ"),
    "foundation": ("фундамент", "основан", "сва", "ростверк", "плит"),
    "concrete_monolithic": ("бетон", "монолит", "железобетон", "плит", "стен", "перекрыт", "колонн"),
    "concrete_precast": ("сборн", "панел", "блок", "плит"),
    "masonry": ("кладк", "кирпич", "блок", "перегород"),
    "metal": ("металл", "сталь", "конструкц", "листов", "балк", "ферм", "свар"),
    "wood": ("дерев", "брус", "бревн", "каркас", "стропил"),
    "floors": ("пол", "стяжк", "покрыт"),
    "roofing": ("кровл", "рулон", "мембран", "покрыт"),
    "waterproofing": ("гидроизол", "изоляц", "оклеечн", "обмазочн", "мастичн"),
    "finishes": ("отделк", "штукатур", "окрас", "облицов"),
    "mep": ("трубопровод", "водопровод", "канализац", "отоплен", "вентиляц", "кабел", "электр", "сеть"),
}

_ELEMENT_TITLE_HINTS: dict[str, tuple[str, ...]] = {
    "excavation": ("разработ", "грунт", "котлован", "транше", "выемк", "землян"),
    "concrete_preparation": ("подготовк", "бетонн", "щебен", "основан"),
    "foundation_slab": ("плит", "фундамент", "бетон", "железобетон", "монолит"),
    "foundation": ("фундамент", "основан", "бетон"),
    "wood_wall": ("дерев", "брус", "бревн", "стен", "каркас"),
    "metal_assembly": ("монтаж", "установ", "металл", "сталь", "конструкц", "листов", "балк", "ферм"),
    "pile": ("сва", "оголов", "ростверк"),
    "monolithic_wall": ("стен", "бетонирован", "бетон", "монолит", "железобетон"),
    "monolithic_slab": ("перекрыт", "плит", "бетонирован", "бетон", "монолит"),
    "column": ("колонн", "бетон", "монолит"),
    "waterproofing": ("гидроизол", "изоляц", "оклеечн", "обмазочн", "мастичн"),
    "roofing": ("кровл", "покрыт", "рулон", "мембран"),
    "engineering_networks": ("трубопровод", "водопровод", "канализац", "отоплен", "вентиляц", "кабел", "электр", "сеть"),
    "floors": ("пол", "стяжк", "покрыт"),
    "finishes": ("отделк", "штукатур", "окрас", "облицов"),
}

_ACTION_TITLE_HINTS: dict[str, tuple[str, ...]] = {
    "разработка": ("разработ", "выемк"),
    "монтаж": ("монтаж", "установ", "сборк"),
    "устройство": ("устройств", "покрыт", "укладк"),
    "бетонирование": ("бетонирован", "бетон"),
    "изоляция": ("изоляц", "гидроизол"),
    "окраска": ("окрас", "окраш"),
}

_NEGATIVE_TITLE_HINTS = (
    "реактор", "оболочк", "защитн", "шахт", "тоннел", "метрополит", "спецсооруж", "башенн",
    "копр", "резервуар", "силос", "градирн", "доменн", "плотин", "судов", "вагон", "мост",
)

_RESOURCE_KIND_LABELS: dict[str, str] = {
    "labor": "труд рабочих",
    "machinist": "труд машинистов",
    "machine": "машины и механизмы",
    "material": "материалы",
}

_FAMILY_LABELS: dict[str, str] = {
    "earthworks": "земляные работы",
    "foundation": "основания и фундаменты",
    "concrete_monolithic": "монолитный бетон/железобетон",
    "concrete_precast": "сборный железобетон",
    "masonry": "каменные конструкции",
    "metal": "металлоконструкции",
    "wood": "деревянные конструкции",
    "floors": "полы",
    "roofing": "кровля",
    "waterproofing": "изоляция",
    "finishes": "отделка",
    "mep": "инженерные сети",
}

_ELEMENT_LABELS: dict[str, str] = {
    "excavation": "разработка грунта",
    "concrete_preparation": "бетонная подготовка",
    "foundation_slab": "фундаментная плита",
    "foundation": "фундамент",
    "wood_wall": "деревянные стены/каркас",
    "metal_assembly": "монтаж металлоконструкций",
    "pile": "сваи",
    "monolithic_wall": "монолитные стены",
    "monolithic_slab": "монолитные плиты/перекрытия",
    "column": "колонны",
    "waterproofing": "гидроизоляция",
    "roofing": "кровля",
    "engineering_networks": "инженерные сети",
    "floors": "полы",
    "finishes": "отделка",
}

_COLLECTION_LABELS: dict[str, str] = {
    "01": "ГЭСН 01. Земляные работы",
    "05": "ГЭСН 05. Свайные работы, закрепление грунтов, опускные колодцы",
    "06": "ГЭСН 06. Бетонные и железобетонные конструкции монолитные",
    "07": "ГЭСН 07. Бетонные и железобетонные конструкции сборные",
    "08": "ГЭСН 08. Конструкции из кирпича и блоков",
    "09": "ГЭСН 09. Строительные металлические конструкции",
    "10": "ГЭСН 10. Деревянные конструкции",
    "11": "ГЭСН 11. Полы",
    "12": "ГЭСН 12. Кровли",
    "15": "ГЭСН 15. Отделочные работы",
    "16": "ГЭСН 16. Трубопроводы внутренние",
    "17": "ГЭСН 17. Водопровод и канализация внутренние",
    "18": "ГЭСН 18. Отопление, вентиляция и кондиционирование",
    "20": "ГЭСН 20. Вентиляция и кондиционирование воздуха",
    "21": "ГЭСН 21. Электроосвещение зданий",
    "22": "ГЭСН 22. Водопровод наружный",
    "ГЭСНм38": "ГЭСНм 38. Монтаж металлических конструкций и оборудования",
}

_CONDITION_TITLE_HINTS: dict[str, tuple[str, ...]] = {
    "группа грунта": ("группа грунт", "групп грунт"),
    "глубина": ("глубин",),
    "крепления": ("креплен",),
    "геометрия сечения/ширина": ("ширин", "площадью сечения", "сечени"),
    "масса элемента": ("массой", "масс", "свыше", "до 0,", "до 0."),
    "способ производства работ": ("механизирован", "вручную", "кран", "автомобильн", "способ"),
    "материал/основание": ("материал", "основан", "каркас", "рулонн", "мембран"),
    "условия применения": ("при ", "если ", "без ", "с помощью"),
}

_CONDITION_QUESTIONS: dict[str, str] = {
    "группа грунта": "уточнить группу грунта",
    "глубина": "уточнить глубину разработки/заложения",
    "крепления": "уточнить, с креплениями или без креплений",
    "геометрия сечения/ширина": "уточнить ширину или площадь сечения",
    "масса элемента": "уточнить массу элемента",
    "способ производства работ": "уточнить способ производства работ",
    "материал/основание": "уточнить материал или основание",
    "условия применения": "проверить условия применения по названию нормы",
}


def _canon_unit(unit: Any) -> str:
    s = str(unit or "").strip().lower().replace("³", "3").replace("²", "2")
    s = s.replace("куб.м", "м3").replace("кв.м", "м2").replace("куб м", "м3").replace("кв м", "м2")
    return re.sub(r"\s+", "", s)


def _norm_unit_factor(unit: Any) -> tuple[float, str]:
    m = re.match(r"\s*(\d+)?\s*(.+)", str(unit or "").strip())
    if not m:
        return 1.0, _canon_unit(unit)
    factor = float(m.group(1)) if m.group(1) else 1.0
    return factor, _canon_unit(m.group(2))


def _base_type_from_code(code: Any, norm: dict[str, Any] | None = None) -> str:
    if norm and norm.get("base_type"):
        return str(norm.get("base_type") or "ГЭСН")
    text = str(code or "").strip()
    if text.startswith("ГЭСНм"):
        return "ГЭСНм"
    if text.startswith("ГЭСНр"):
        return "ГЭСНр"
    if text.startswith("ГЭСНп"):
        return "ГЭСНп"
    if text.startswith("ФЕРм"):
        return "ФЕРм"
    if text.startswith("ФЕР"):
        return "ФЕР"
    if text.startswith("ТЕРм"):
        return "ТЕРм"
    if text.startswith("ТЕР"):
        return "ТЕР"
    return "ГЭСН"


def _bare_code(code: Any) -> str:
    m = _BARE_CODE_RE.search(str(code or ""))
    return m.group(1) if m else ""


def _collection_key(code: Any, base_type: Any) -> str:
    bare = _bare_code(code)
    collection = bare[:2] if bare else ""
    bt = str(base_type or "ГЭСН")
    return collection if bt == "ГЭСН" else f"{bt}{collection}"


def _tokens(text: Any) -> str:
    return " ".join(re.findall(r"[а-яёa-z0-9]{3,}", str(text or "").lower()))


def _csv(values: Iterable[str]) -> str:
    return ",".join(sorted({str(v).strip() for v in values if str(v).strip()}))


def _csv_has(csv_text: Any, value: str) -> bool:
    needle = str(value or "").strip()
    return bool(needle and needle in set(str(csv_text or "").split(",")))


def _csv_list(csv_text: Any) -> list[str]:
    return [x for x in str(csv_text or "").split(",") if x]


def _labels(values: Iterable[str], labels: dict[str, str]) -> list[str]:
    return [labels.get(v, v) for v in values if v]


def _collection_label(collection_key: str) -> str:
    return _COLLECTION_LABELS.get(collection_key, f"сборник {collection_key}" if collection_key else "сборник не определён")


def _condition_questions(condition_hints: Iterable[str]) -> list[str]:
    return [_CONDITION_QUESTIONS.get(c, c) for c in condition_hints if c]


def _fts_query(words: Iterable[str]) -> str:
    clean = []
    for word in words:
        w = re.sub(r"[^а-яёa-z0-9]", "", str(word or "").lower())
        if len(w) >= 3:
            clean.append(f"{w}*")
    return " OR ".join(clean[:12])


@dataclass(frozen=True)
class SmetaNormRow:
    code: str
    title: str
    measure_unit: str
    base_unit: str
    base_type: str
    collection: str
    collection_key: str
    subsection: str
    source_kind: str
    provenance: str
    resource_count: int
    resource_kinds: str
    family_hints: str
    element_hints: str
    action_hints: str
    negative_hints: str
    condition_hints: str
    token_text: str

    def profile(self) -> dict[str, Any]:
        resource_kinds = _csv_list(self.resource_kinds)
        family_hints = _csv_list(self.family_hints)
        element_hints = _csv_list(self.element_hints)
        action_hints = _csv_list(self.action_hints)
        negative_hints = _csv_list(self.negative_hints)
        condition_hints = _csv_list(self.condition_hints)
        return {
            "base_type": self.base_type,
            "collection_key": self.collection_key,
            "subsection": self.subsection,
            "source_kind": self.source_kind,
            "provenance": self.provenance,
            "resource_count": self.resource_count,
            "resource_kinds": resource_kinds,
            "family_hints": family_hints,
            "element_hints": element_hints,
            "action_hints": action_hints,
            "negative_hints": negative_hints,
            "condition_hints": condition_hints,
            "model_card": {
                "title": self.title,
                "measure": f"измеритель нормы: {self.measure_unit}; базовая единица: {self.base_unit or '—'}",
                "domain": {
                    "families": _labels(family_hints, _FAMILY_LABELS),
                    "elements": _labels(element_hints, _ELEMENT_LABELS),
                    "actions": action_hints,
                },
                "conditions_to_check": condition_hints,
                "resources": {
                    "count": self.resource_count,
                    "kinds": _labels(resource_kinds, _RESOURCE_KIND_LABELS),
                },
                "warnings": [
                    "это навигационная карточка нормы, не расчёт стоимости",
                    *([f"проверить признаки ограничения: {', '.join(negative_hints)}"] if negative_hints else []),
                ],
            },
            "navigation": {
                "collection": {
                    "key": self.collection_key,
                    "label": _collection_label(self.collection_key),
                    "subsection": self.subsection,
                    "base_type": self.base_type,
                },
                "questions_to_ask": _condition_questions(condition_hints),
                "rim_use": [
                    "норма задаёт ресурсный состав и измеритель",
                    "физический объём, перевод в измеритель нормы, НР/СП и итог считает код",
                    "если условия нормы не подтверждены, спросить пользователя или оставить partial",
                ],
            },
        }


class SmetaNormStore:
    schema = "smeta_norm_store_v4"
    backend = "sqlite_light"

    def __init__(self, rows: list[SmetaNormRow]) -> None:
        self.rows = rows
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = RLock()
        self._has_fts = False
        self._build()

    def _build(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE norms (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                measure_unit TEXT NOT NULL,
                base_unit TEXT NOT NULL,
                base_type TEXT NOT NULL,
                collection TEXT NOT NULL,
                collection_key TEXT NOT NULL,
                subsection TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                provenance TEXT NOT NULL,
                resource_count INTEGER NOT NULL,
                resource_kinds TEXT NOT NULL,
                family_hints TEXT NOT NULL,
                element_hints TEXT NOT NULL,
                action_hints TEXT NOT NULL,
                negative_hints TEXT NOT NULL,
                condition_hints TEXT NOT NULL,
                token_text TEXT NOT NULL
            )
            """
        )
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO norms
            (
                code, title, measure_unit, base_unit, base_type, collection, collection_key, subsection,
                source_kind, provenance, resource_count, resource_kinds, family_hints, element_hints,
                action_hints, negative_hints, condition_hints, token_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r.code,
                    r.title,
                    r.measure_unit,
                    r.base_unit,
                    r.base_type,
                    r.collection,
                    r.collection_key,
                    r.subsection,
                    r.source_kind,
                    r.provenance,
                    r.resource_count,
                    r.resource_kinds,
                    r.family_hints,
                    r.element_hints,
                    r.action_hints,
                    r.negative_hints,
                    r.condition_hints,
                    r.token_text,
                )
                for r in self.rows
            ],
        )
        try:
            self.conn.execute("CREATE VIRTUAL TABLE norms_fts USING fts5(code, title, token_text)")
            self.conn.execute(
                "INSERT INTO norms_fts(rowid, code, title, token_text) "
                "SELECT rowid, code, title, token_text FROM norms"
            )
            self._has_fts = True
        except sqlite3.Error:
            self._has_fts = False
        self.conn.commit()

    def search_rows(self, words: list[str], *, limit: int | None = None) -> list[SmetaNormRow]:
        """Return a lexical candidate pool. Applicability is handled by the harness."""
        if not words:
            return []
        row_limit = len(self.rows) if limit is None else max(1, int(limit))
        if self._has_fts:
            query = _fts_query(words)
            if query:
                try:
                    with self._lock:
                        found = self.conn.execute(
                            """
                            SELECT n.* FROM norms_fts f
                            JOIN norms n ON n.rowid = f.rowid
                            WHERE norms_fts MATCH ?
                            LIMIT ?
                            """,
                            (query, row_limit),
                        ).fetchall()
                    if found:
                        return [_row_from_sql(r) for r in found]
                except sqlite3.Error:
                    pass
        clauses = " OR ".join(["token_text LIKE ?" for _ in words[:12]])
        params = [f"%{w.lower()}%" for w in words[:12]]
        with self._lock:
            found = self.conn.execute(
                f"SELECT * FROM norms WHERE {clauses} LIMIT ?",
                (*params, row_limit),
            ).fetchall()
        return [_row_from_sql(r) for r in found]

    def by_code(self, code: str) -> SmetaNormRow | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM norms WHERE code = ? LIMIT 1",
                (str(code or "").strip(),),
            ).fetchone()
        return _row_from_sql(row) if row else None

    def norm_profile(self, code: str) -> dict[str, Any]:
        row = self.by_code(code)
        if row is None:
            return {}
        return row.profile()

    def nearby_rows(self, row: SmetaNormRow, *, family_hint: str = "", element_hint: str = "",
                    limit: int = 3) -> list[SmetaNormRow]:
        """Small local map around a norm: same collection/subsection first, then same collection.

        This is navigation for the model. It does not select a norm and does not calculate money.
        """
        params: list[Any] = [row.code, row.collection_key]
        where = ["code <> ?", "collection_key = ?"]
        if element_hint:
            where.append("(',' || element_hints || ',') LIKE ?")
            params.append(f"%,{element_hint},%")
        elif family_hint:
            where.append("(',' || family_hints || ',') LIKE ?")
            params.append(f"%,{family_hint},%")
        with self._lock:
            found = self.conn.execute(
                f"""
                SELECT * FROM norms
                WHERE {' AND '.join(where)}
                ORDER BY CASE WHEN subsection = ? THEN 0 ELSE 1 END, code
                LIMIT ?
                """,
                (*params, row.subsection, max(1, int(limit))),
            ).fetchall()
        peers = [_row_from_sql(r) for r in found]
        if len(peers) >= limit:
            return peers[:limit]
        with self._lock:
            fallback = self.conn.execute(
                """
                SELECT * FROM norms
                WHERE code <> ? AND collection_key = ?
                ORDER BY CASE WHEN subsection = ? THEN 0 ELSE 1 END, code
                LIMIT ?
                """,
                (row.code, row.collection_key, row.subsection, max(1, int(limit))),
            ).fetchall()
        seen = {p.code for p in peers}
        for candidate in (_row_from_sql(r) for r in fallback):
            if candidate.code not in seen:
                peers.append(candidate)
                seen.add(candidate.code)
            if len(peers) >= limit:
                break
        return peers[:limit]

    def navigation_for(self, row: SmetaNormRow, *, family_hint: str = "", element_hint: str = "",
                       limit: int = 3) -> dict[str, Any]:
        profile = row.profile()
        navigation = dict(profile.get("navigation") or {})
        peers = self.nearby_rows(row, family_hint=family_hint, element_hint=element_hint, limit=limit)
        navigation["nearby_norms"] = [
            {
                "code": peer.code,
                "title": peer.title[:160],
                "measure_unit": peer.measure_unit,
                "conditions": _csv_list(peer.condition_hints)[:6],
            }
            for peer in peers
        ]
        navigation["selection_hint"] = (
            "сравнить первую найденную норму с соседними нормами по названию, единице и условиям; "
            "если условия не совпадают с исходными, не принимать молча, а спросить"
        )
        return navigation

    def payload(self) -> dict[str, Any]:
        by_base: dict[str, int] = {}
        by_collection: dict[str, int] = {}
        for row in self.rows:
            by_base[row.base_type] = by_base.get(row.base_type, 0) + 1
            by_collection[row.collection_key] = by_collection.get(row.collection_key, 0) + 1
        return {
            "schema": self.schema,
            "backend": self.backend,
            "norm_count": len(self.rows),
            "fts": self._has_fts,
            "by_base_type": by_base,
            "collections": len(by_collection),
            "profile_fields": [
                "resource_kinds", "family_hints", "element_hints", "action_hints",
                "condition_hints", "provenance", "model_card", "navigation",
            ],
        }


def _row_from_sql(row: sqlite3.Row) -> SmetaNormRow:
    return SmetaNormRow(
        code=str(row["code"]),
        title=str(row["title"]),
        measure_unit=str(row["measure_unit"]),
        base_unit=str(row["base_unit"]),
        base_type=str(row["base_type"]),
        collection=str(row["collection"]),
        collection_key=str(row["collection_key"]),
        subsection=str(row["subsection"]),
        source_kind=str(row["source_kind"]),
        provenance=str(row["provenance"]),
        resource_count=int(row["resource_count"] or 0),
        resource_kinds=str(row["resource_kinds"]),
        family_hints=str(row["family_hints"]),
        element_hints=str(row["element_hints"]),
        action_hints=str(row["action_hints"]),
        negative_hints=str(row["negative_hints"]),
        condition_hints=str(row["condition_hints"]),
        token_text=str(row["token_text"]),
    )


def _infer_hints(title: str, collection_key: str) -> tuple[str, str, str, str]:
    text = title.lower()
    family = set(_COLLECTION_FAMILY_HINTS.get(collection_key, ()))
    for key, anchors in _FAMILY_TITLE_HINTS.items():
        if any(anchor in text for anchor in anchors):
            family.add(key)
    elements = {
        key for key, anchors in _ELEMENT_TITLE_HINTS.items()
        if any(anchor in text for anchor in anchors)
    }
    actions = {
        key for key, anchors in _ACTION_TITLE_HINTS.items()
        if any(anchor in text for anchor in anchors)
    }
    negative = {anchor for anchor in _NEGATIVE_TITLE_HINTS if anchor in text}
    return _csv(family), _csv(elements), _csv(actions), _csv(negative)


def _infer_condition_hints(title: str) -> str:
    text = title.lower()
    conditions = {
        label for label, anchors in _CONDITION_TITLE_HINTS.items()
        if any(anchor in text for anchor in anchors)
    }
    return _csv(conditions)


def _resource_projection(norm: dict[str, Any]) -> tuple[int, str, str]:
    resources = [r for r in (norm.get("resources") or []) if isinstance(r, dict)]
    kinds = _csv(str(r.get("kind") or "") for r in resources)
    text = " ".join(
        f"{r.get('kind', '')} {r.get('name', '')} {r.get('unit', '')} {r.get('code', '')}"
        for r in resources[:40]
    )
    return len(resources), kinds, _tokens(text)


def _build_rows() -> list[SmetaNormRow]:
    from proxy.services.gesn_service import load_base_norms, load_norms

    base_norms = dict(load_base_norms() or {})
    seed_norms = dict(load_norms() or {})
    norm_sources: dict[str, str] = {key: "base_parquet" for key in base_norms}
    norms = dict(base_norms)
    for key, norm in seed_norms.items():
        norms[key] = norm
        norm_sources[key] = "seed_yaml"
    rows: list[SmetaNormRow] = []
    for key, norm in norms.items():
        code = str(key or norm.get("code") or "").strip()
        title = str(norm.get("name") or "").strip()
        unit = str(norm.get("unit") or "").strip()
        _factor, base_unit = _norm_unit_factor(unit)
        base_type = _base_type_from_code(code or norm.get("code"), norm)
        bare = _bare_code(code or norm.get("code"))
        collection = bare[:2] if bare else ""
        collection_key = _collection_key(code or norm.get("code"), base_type)
        family_hints, element_hints, action_hints, negative_hints = _infer_hints(title, collection_key)
        condition_hints = _infer_condition_hints(title)
        resource_count, resource_kinds, resource_text = _resource_projection(norm)
        source_kind = norm_sources.get(key, "unknown")
        provenance = "config/domain/gesn_seed.yaml" if source_kind == "seed_yaml" else "data/gesn_base/*.parquet"
        rows.append(
            SmetaNormRow(
                code=code,
                title=title.lower(),
                measure_unit=unit,
                base_unit=base_unit,
                base_type=base_type,
                collection=collection,
                collection_key=collection_key,
                subsection="-".join(bare.split("-")[:2]) if bare else "",
                source_kind=source_kind,
                provenance=provenance,
                resource_count=resource_count,
                resource_kinds=resource_kinds,
                family_hints=family_hints,
                element_hints=element_hints,
                action_hints=action_hints,
                negative_hints=negative_hints,
                condition_hints=condition_hints,
                token_text=_tokens(
                    f"{title} {unit} {base_type} {bare} {family_hints} {element_hints} "
                    f"{action_hints} {condition_hints} {resource_kinds} {resource_text}"
                ),
            )
        )
    return rows


@lru_cache(maxsize=1)
def get_smeta_norm_store() -> SmetaNormStore:
    return SmetaNormStore(_build_rows())


def norm_store_payload() -> dict[str, Any]:
    return get_smeta_norm_store().payload()
