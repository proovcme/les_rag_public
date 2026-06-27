"""Дифф CAD/BIM-графов и текстовых документов — W12.1 (LES3_PLAN).

ADR-11: ядро без LLM. CAD-дифф — сравнение двух импортов graph-БД по
source_id (SQL + код); текстовый дифф — сопоставление по нумерованным
пунктам (ГОСТ/СП) + difflib для тел. LLM в модуле не используется.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from proxy.services.cad_bim_graph import CAD_BIM_DB_PATH

# Поля элемента, участвующие в сравнении (метаданные графа).
ELEMENT_FIELDS = ("object_type", "name", "layer", "category", "family", "level", "material")

# Максимум детализированных записей в отчёте (счётчики всегда полные).
MAX_DETAIL = 500

# Заголовок пункта/раздела: "5.2.1 Текст", "п. 7.3", "## Заголовок", "Раздел 4".
_CLAUSE_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|(?:Пункт|Раздел|Статья|Приложение|п\.)\s*)?"
    r"(?P<num>\d+(?:\.\d+)+|[А-ЯA-Z](?=\)|\.)|\d+(?=[.)]\s))",
)


# ── CAD/BIM-граф ──


def _load_elements(conn: sqlite3.Connection, import_id: str) -> dict[str, dict]:
    rows = conn.execute(
        f"SELECT source_id, {', '.join(ELEMENT_FIELDS)}, attributes_json "
        "FROM cad_bim_elements WHERE import_id = ?",
        (import_id,),
    ).fetchall()
    elements: dict[str, dict] = {}
    for row in rows:
        source_id = row[0]
        item = {fname: row[i + 1] or "" for i, fname in enumerate(ELEMENT_FIELDS)}
        try:
            item["attributes"] = json.loads(row[-1] or "{}")
        except (TypeError, ValueError):
            item["attributes"] = {}
        elements[source_id] = item
    return elements


def _load_properties(conn: sqlite3.Connection, import_id: str) -> dict[str, dict[str, str]]:
    rows = conn.execute(
        "SELECT source_id, name, value FROM cad_bim_properties WHERE import_id = ?",
        (import_id,),
    ).fetchall()
    props: dict[str, dict[str, str]] = {}
    for source_id, name, value in rows:
        props.setdefault(source_id, {})[name] = value
    return props


@dataclass
class CadDiff:
    import_a: str
    import_b: str
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)
    unchanged_count: int = 0
    added_count: int = 0
    removed_count: int = 0
    changed_count: int = 0

    def payload(self) -> dict:
        return {
            "import_a": self.import_a,
            "import_b": self.import_b,
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "changed_count": self.changed_count,
            "unchanged_count": self.unchanged_count,
            "added": self.added[:MAX_DETAIL],
            "removed": self.removed[:MAX_DETAIL],
            "changed": self.changed[:MAX_DETAIL],
            "detail_truncated": max(len(self.added), len(self.removed), len(self.changed)) > MAX_DETAIL,
        }


def diff_cad_imports(
    import_a: str,
    import_b: str,
    db_path: Path = CAD_BIM_DB_PATH,
) -> CadDiff:
    """Сравнение двух импортов одной модели: добавлено/удалено/изменено по source_id."""
    diff = CadDiff(import_a=import_a, import_b=import_b)
    with sqlite3.connect(db_path) as conn:
        elements_a = _load_elements(conn, import_a)
        elements_b = _load_elements(conn, import_b)
        props_a = _load_properties(conn, import_a)
        props_b = _load_properties(conn, import_b)

    def _brief(source_id: str, item: dict) -> dict:
        return {
            "source_id": source_id,
            "object_type": item.get("object_type", ""),
            "name": item.get("name", ""),
            "level": item.get("level", ""),
            "category": item.get("category", ""),
        }

    for source_id in sorted(set(elements_b) - set(elements_a)):
        diff.added.append(_brief(source_id, elements_b[source_id]))
    for source_id in sorted(set(elements_a) - set(elements_b)):
        diff.removed.append(_brief(source_id, elements_a[source_id]))

    for source_id in sorted(set(elements_a) & set(elements_b)):
        a, b = elements_a[source_id], elements_b[source_id]
        changes: dict[str, dict] = {}
        for fname in ELEMENT_FIELDS:
            if a.get(fname, "") != b.get(fname, ""):
                changes[fname] = {"old": a.get(fname, ""), "new": b.get(fname, "")}

        pa, pb = props_a.get(source_id, {}), props_b.get(source_id, {})
        for prop in sorted(set(pa) | set(pb)):
            old_v, new_v = pa.get(prop), pb.get(prop)
            if old_v != new_v:
                changes[f"prop:{prop}"] = {"old": old_v, "new": new_v}

        if changes:
            entry = _brief(source_id, b)
            entry["changes"] = changes
            diff.changed.append(entry)
        else:
            diff.unchanged_count += 1

    diff.added_count = len(diff.added)
    diff.removed_count = len(diff.removed)
    diff.changed_count = len(diff.changed)
    return diff


# ── Текстовые документы ──


def split_clauses(text: str) -> list[tuple[str, str]]:
    """Разбивка документа на блоки (ключ-пункта, тело). Блоки без номера — ключ ''. """
    blocks: list[tuple[str, list[str]]] = []
    current_key = ""
    current: list[str] = []
    for line in text.splitlines():
        match = _CLAUSE_RE.match(line) if line.strip() else None
        if match and re.search(r"\d", match.group("num") or ""):
            if current and any(s.strip() for s in current):
                blocks.append((current_key, current))
            current_key = match.group("num")
            current = [line]
        else:
            current.append(line)
    if current and any(s.strip() for s in current):
        blocks.append((current_key, current))
    return [(key, "\n".join(lines).strip()) for key, lines in blocks]


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class TextDiff:
    label_a: str
    label_b: str
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)
    unchanged_count: int = 0

    def payload(self) -> dict:
        return {
            "label_a": self.label_a,
            "label_b": self.label_b,
            "added_count": len(self.added),
            "removed_count": len(self.removed),
            "changed_count": len(self.changed),
            "unchanged_count": self.unchanged_count,
            "added": self.added[:MAX_DETAIL],
            "removed": self.removed[:MAX_DETAIL],
            "changed": self.changed[:MAX_DETAIL],
        }


def _unified_snippet(old: str, new: str, context: int = 1, max_lines: int = 40) -> str:
    lines = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), lineterm="", n=context,
        )
    )[2:]  # без заголовков ---/+++
    return "\n".join(lines[:max_lines])


def diff_texts(
    text_a: str,
    text_b: str,
    label_a: str = "A",
    label_b: str = "B",
) -> TextDiff:
    """Структурный дифф двух ревизий: сопоставление по номерам пунктов, difflib для тел."""
    diff = TextDiff(label_a=label_a, label_b=label_b)
    blocks_a = split_clauses(text_a)
    blocks_b = split_clauses(text_b)

    keyed_a = {key: body for key, body in blocks_a if key}
    keyed_b = {key: body for key, body in blocks_b if key}

    for key in sorted(set(keyed_b) - set(keyed_a), key=_clause_sort_key):
        diff.added.append({"clause": key, "text": keyed_b[key][:600]})
    for key in sorted(set(keyed_a) - set(keyed_b), key=_clause_sort_key):
        diff.removed.append({"clause": key, "text": keyed_a[key][:600]})
    for key in sorted(set(keyed_a) & set(keyed_b), key=_clause_sort_key):
        body_a, body_b = keyed_a[key], keyed_b[key]
        if _normalized(body_a) == _normalized(body_b):
            diff.unchanged_count += 1
            continue
        ratio = difflib.SequenceMatcher(None, _normalized(body_a), _normalized(body_b)).ratio()
        diff.changed.append({
            "clause": key,
            "similarity": round(ratio, 3),
            "diff": _unified_snippet(body_a, body_b),
        })

    # Ненумерованные блоки (преамбулы, таблицы без пунктов) — грубое сравнение множествами.
    plain_a = {_normalized(body) for key, body in blocks_a if not key}
    plain_b = {_normalized(body) for key, body in blocks_b if not key}
    plain_bodies_b = {_normalized(body): body for key, body in blocks_b if not key}
    plain_bodies_a = {_normalized(body): body for key, body in blocks_a if not key}
    for norm in plain_b - plain_a:
        diff.added.append({"clause": "", "text": plain_bodies_b[norm][:600]})
    for norm in plain_a - plain_b:
        diff.removed.append({"clause": "", "text": plain_bodies_a[norm][:600]})
    diff.unchanged_count += len(plain_a & plain_b)

    return diff


def _clause_sort_key(clause: str) -> tuple:
    parts = []
    for piece in clause.split("."):
        parts.append(int(piece) if piece.isdigit() else 0)
    return tuple(parts)
