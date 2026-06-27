"""Deterministic lookup for numbered normative clauses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from proxy.services.kot_service import extract_norm_refs
from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled


CLAUSE_RE = re.compile(
    r"(?:пункт(?:а|е|ом)?|п\.|подпункт(?:а|е)?|пп\.)\s*(\d+(?:[.,]\d+){1,4})",
    re.IGNORECASE,
)
# W2.6: раздел/глава/статья/параграф — одиночный номер ("раздел 6"), дробный и римский.
SECTION_RE = re.compile(
    r"(?:раздел(?:а|е|ом)?|глав(?:а|е|ы)|стать(?:я|и|е)|параграф(?:а|е)?|§)\s*"
    r"(?:(\d+(?:[.,]\d+)*)|([IVXLC]{1,7})\b)",
    re.IGNORECASE,
)
# W2.6: «приложение Б» — буквенные приложения по ГОСТ (кириллица/латиница).
APPENDIX_RE = re.compile(r"приложени[еяию]\w*\s+([А-ЯЁA-Z])\b", re.IGNORECASE)
LEADING_CLAUSE_RE = re.compile(r"^\s*(?:найди|покажи|дай|открой)?\s*(\d+(?:[.,]\d+){1,4})(?:\s|$)", re.IGNORECASE)
HEADING_RE = re.compile(r"(?m)(?:^|\n{2,})(\d+(?:\.\d+){1,4})(?:\.|\s)")
# Для одиночных целей («раздел 6») — отдельный шаблон с заглавной буквой после номера:
# «6 Вентиляция» — заголовок, «6 шт.» в списке — нет. Снижает ложные границы.
SECTION_HEADING_RE = re.compile(r"(?m)(?:^|\n{2,})#{0,6}\s*(\d+(?:\.\d+){0,4})[.\s]+(?=[А-ЯЁA-Z])")
APPENDIX_HEADING_RE = re.compile(r"(?m)(?:^|\n)\s*#{0,6}\s*Приложени[ея]\s+([А-ЯЁA-Z])\b")

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman_to_int(value: str) -> int:
    total = 0
    prev = 0
    for char in reversed(value.upper()):
        current = _ROMAN_VALUES.get(char, 0)
        total = total - current if current < prev else total + current
        prev = max(prev, current)
    return total


@dataclass(frozen=True)
class ClauseLookupResult:
    answer: str
    sources: list[str]
    dataset_id: str
    doc_name: str
    clause: str
    norm_ref: str
    start_ord: int | None = None
    end_ord: int | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "operation": "clause_lookup",
            "clause": self.clause,
            "norm_ref": self.norm_ref,
            "doc_name": self.doc_name,
            "dataset_id": self.dataset_id,
            "start_ord": self.start_ord,
            "end_ord": self.end_ord,
        }


def maybe_answer_clause_lookup(
    question: str,
    *,
    collection: str,
    dataset_ids: list[str] | None = None,
    max_chars: int = 8000,
) -> ClauseLookupResult | None:
    if not collection or not lexical_enabled():
        return None
    kind, clause = _extract_clause(question)
    implied_smoke_clause = _implied_smoke_control_exception(question)
    if not clause and implied_smoke_clause:
        kind, clause = "clause", implied_smoke_clause
    if not clause:
        return None
    norm_refs = list(extract_norm_refs(question))
    if not norm_refs and implied_smoke_clause:
        norm_refs = ["сп 7.13130"]
    if not norm_refs:
        return None

    index = LexicalIndex()
    with index.connect() as conn:
        for norm_ref in norm_refs:
            ref_number = _ref_number(norm_ref)
            if not ref_number:
                continue
            docs = _candidate_docs(conn, collection, ref_number, dataset_ids or [])
            for doc in docs:
                rows = conn.execute(
                    """
                    SELECT dataset_id, doc_name, text, chunk_ord
                    FROM lexical_chunks
                    WHERE collection=? AND dataset_id=? AND doc_name=?
                    ORDER BY COALESCE(chunk_ord, id) ASC
                    """,
                    (collection, doc["dataset_id"], doc["doc_name"]),
                ).fetchall()
                if kind == "appendix":
                    extracted = _extract_appendix_text(rows, clause, max_chars=max_chars)
                else:
                    extracted = _extract_clause_text(rows, clause, max_chars=max_chars)
                if extracted:
                    text, start_ord, end_ord = extracted
                    doc_name = str(doc["doc_name"])
                    label = f"Приложение {clause.upper()}" if kind == "appendix" else f"Пункт {clause}"
                    answer = f"{label} {norm_ref.upper()}:\n\n{text}"
                    return ClauseLookupResult(
                        answer=answer,
                        sources=[doc_name],
                        dataset_id=str(doc["dataset_id"]),
                        doc_name=doc_name,
                        clause=clause,
                        norm_ref=norm_ref,
                        start_ord=start_ord,
                        end_ord=end_ord,
                    )
    return None


def _candidate_docs(conn: Any, collection: str, ref_number: str, dataset_ids: list[str]) -> list[Any]:
    params: list[Any] = [collection, f"%{ref_number}%"]
    dataset_clause = ""
    if dataset_ids:
        placeholders = ",".join("?" for _ in dataset_ids)
        dataset_clause = f" AND dataset_id IN ({placeholders})"
        params.extend(dataset_ids)
    return conn.execute(
        f"""
        SELECT dataset_id, doc_name, COUNT(*) AS rows_count
        FROM lexical_chunks
        WHERE collection=? AND doc_name LIKE ? {dataset_clause}
        GROUP BY dataset_id, doc_name
        ORDER BY rows_count DESC
        LIMIT 8
        """,
        params,
    ).fetchall()


def _extract_clause(question: str) -> tuple[str, str]:
    """Возвращает (kind, value): ('clause', '7.2') / ('appendix', 'Б') / ('', '')."""
    match = CLAUSE_RE.search(question) or LEADING_CLAUSE_RE.search(question)
    if match:
        return "clause", match.group(1).replace(",", ".")
    section = SECTION_RE.search(question)
    if section:
        if section.group(1):
            return "clause", section.group(1).replace(",", ".")
        return "clause", str(_roman_to_int(section.group(2)))
    appendix = APPENDIX_RE.search(question)
    if appendix:
        return "appendix", appendix.group(1).upper()
    return "", ""


def _ref_number(norm_ref: str) -> str:
    match = re.search(r"\d+(?:\.\d+)+", norm_ref)
    return match.group(0) if match else ""


def _implied_smoke_control_exception(question: str) -> str:
    q = question.casefold().replace("ё", "е")
    has_smoke_subject = any(token in q for token in ("дымоудал", "противодым"))
    asks_exception = any(
        token in q
        for token in (
            "не выполнять",
            "не предусматривать",
            "не оборудовать",
            "допускается не",
            "допускаются не",
            "можно не",
            "исключени",
        )
    )
    return "7.3" if has_smoke_subject and asks_exception else ""


def _extract_clause_text(rows: list[Any], clause: str, *, max_chars: int) -> tuple[str, int | None, int | None] | None:
    if not rows:
        return None
    parts: list[str] = []
    offsets: list[tuple[int, int | None]] = []
    cursor = 0
    for row in rows:
        text = _clean_text(str(row["text"] or ""))
        if not text:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        offsets.append((cursor, row["chunk_ord"]))
        parts.append(text)
        cursor += len(text)
    merged = "".join(parts)
    if not merged:
        return None

    target = tuple(int(part) for part in clause.split("."))
    start = None
    end = len(merged)
    # W2.6: для одиночной цели («раздел 6») заголовки ищем шаблоном с одиночными номерами.
    heading_re = SECTION_HEADING_RE if len(target) == 1 else HEADING_RE
    for match in heading_re.finditer(merged):
        number = match.group(1)
        number_parts = tuple(int(part) for part in number.split("."))
        number_start = match.start(1)
        if start is None:
            if number_parts == target:
                start = number_start
            continue
        if number_start <= start:
            continue
        if len(number_parts) <= len(target) and number_parts != target:
            end = number_start
            break

    if start is None:
        return None

    extracted = merged[start:end].strip()
    if not extracted:
        return None
    if max_chars and len(extracted) > max_chars:
        extracted = extracted[: max_chars - 1].rstrip() + "…"
    return extracted, _ord_at(offsets, start), _ord_at(offsets, max(start, end - 1))


def _extract_appendix_text(rows: list[Any], letter: str, *, max_chars: int) -> tuple[str, int | None, int | None] | None:
    """W2.6: «Приложение Б» — от его заголовка до следующего приложения/конца документа."""
    if not rows:
        return None
    parts: list[str] = []
    offsets: list[tuple[int, int | None]] = []
    cursor = 0
    for row in rows:
        text = _clean_text(str(row["text"] or ""))
        if not text:
            continue
        if parts:
            parts.append("\n\n")
            cursor += 2
        offsets.append((cursor, row["chunk_ord"]))
        parts.append(text)
        cursor += len(text)
    merged = "".join(parts)
    if not merged:
        return None

    start = None
    end = len(merged)
    target = letter.upper()
    for match in APPENDIX_HEADING_RE.finditer(merged):
        if start is None:
            if match.group(1).upper() == target:
                start = match.start()
            continue
        if match.start() > start:
            end = match.start()
            break
    if start is None:
        return None
    extracted = merged[start:end].strip()
    if not extracted:
        return None
    if max_chars and len(extracted) > max_chars:
        extracted = extracted[: max_chars - 1].rstrip() + "…"
    return extracted, _ord_at(offsets, start), _ord_at(offsets, max(start, end - 1))


def _clean_text(text: str) -> str:
    text = re.sub(r"!\[\]\(data:image/[^)]*\)", "", text)
    text = re.sub(r"<a\s+id=\"[^\"]+\"></a>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\\([.()\\\-\[\]])", r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _ord_at(offsets: list[tuple[int, int | None]], position: int) -> int | None:
    current: int | None = None
    for start, chunk_ord in offsets:
        if start > position:
            break
        current = chunk_ord
    return current
