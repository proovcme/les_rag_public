"""Notebook-guided project study layer.

This is a navigation layer, not evidence. It uses dataset notebooks to build a
reading plan, then retrieves evidence for each section before the normal LLM
synthesis step.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from proxy.services.notebook_service import build_dataset_notebook
from proxy.services.saferag_service import concentrate_sources, rank_chunks_for_question

logger = logging.getLogger(__name__)

RetrieveFn = Callable[[str], Awaitable[list[Any]]]


@dataclass(frozen=True)
class StudySection:
    id: str
    title: str
    query: str
    reason: str
    hints: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "query": self.query,
            "reason": self.reason,
            "hints": self.hints,
        }


@dataclass
class StudyPack:
    notebooks: list[dict[str, Any]]
    plan: list[StudySection]
    chunks_by_section: dict[str, list[Any]]
    gaps: list[str]

    @property
    def chunks(self) -> list[Any]:
        out: list[Any] = []
        seen: set[tuple[str, str]] = set()
        for section in self.plan:
            for chunk in self.chunks_by_section.get(section.id, []):
                key = (str(getattr(chunk, "doc_name", "")), str(getattr(chunk, "content", ""))[:240])
                if key in seen:
                    continue
                seen.add(key)
                out.append(chunk)
        return out

    def payload(self) -> dict[str, Any]:
        quality = []
        for section in self.plan:
            chunks = self.chunks_by_section.get(section.id, [])
            quality.append({
                "section_id": section.id,
                "title": section.title,
                "hits": len(chunks),
                "docs": sorted({str(getattr(chunk, "doc_name", "")) for chunk in chunks if getattr(chunk, "doc_name", "")})[:6],
            })
        return {
            "schema": "notebook_study_v1",
            "context_role": "navigation",
            "is_evidence": False,
            "notebooks": [
                {
                    "dataset_id": nb.get("dataset_id"),
                    "name": nb.get("name"),
                    "quality": ((nb.get("profile") or {}).get("quality") or {}).get("status"),
                    "chunk_count": nb.get("chunk_count"),
                    "document_count": nb.get("document_count"),
                }
                for nb in self.notebooks
            ],
            "reading_plan": [section.payload() for section in self.plan],
            "retrieval_by_section": quality,
            "gaps": self.gaps,
        }


_BROAD_STUDY_RE = re.compile(
    r"\b("
    r"расскажи|рассказать|разбери|разобрать|обзор|сводк[ауи]|"
    r"что\s+внутри|что\s+есть|что\s+по\s+проект|"
    r"изучи|проанализируй|дай\s+картину|инженерн\w*\s+сводк"
    r")\b",
    re.IGNORECASE,
)
_AREA_RE = re.compile(r"\b(проект|датасет|блокнот|документац|комплект|том|объект)\w*\b", re.IGNORECASE)
_DIRECT_RE = re.compile(r"\b(блокнот|notebook|нблм|инженерн\w*\s+сводк)\b", re.IGNORECASE)

_DENY_RE = re.compile(
    r"\b("
    r"смет|стоимост|сколько\s+стоит|посчитай|рассчитай|"
    r"нормоконтроль|проверь|замечан|"
    r"найди|где\s+лежит|какой\s+файл|источник"
    r")\b",
    re.IGNORECASE,
)


def is_notebook_study_query(question: str) -> bool:
    """True only for explicit broad study requests, not every generic chat turn."""
    q = (question or "").strip()
    if not q:
        return False
    if _DENY_RE.search(q) and not _DIRECT_RE.search(q):
        return False
    return bool(_DIRECT_RE.search(q) or (_BROAD_STUDY_RE.search(q) and _AREA_RE.search(q)))


def _profile_terms(notebook: dict[str, Any]) -> list[str]:
    summary = notebook.get("notebook_summary") if isinstance(notebook.get("notebook_summary"), dict) else {}
    profile = notebook.get("profile") if isinstance(notebook.get("profile"), dict) else {}
    quality = profile.get("quality") if isinstance(profile.get("quality"), dict) else {}
    signals = quality.get("signals") if isinstance(quality.get("signals"), dict) else {}
    terms: list[str] = []
    for key in ("subject_areas", "document_types", "key_terms", "norm_refs"):
        values = summary.get(key) or []
        if isinstance(values, list):
            terms.extend(str(value) for value in values if value)
    for key in ("keywords", "domains", "routes", "document_types"):
        values = profile.get(key) or []
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    terms.append(str(value.get("value") or ""))
                else:
                    terms.append(str(value))
    if signals.get("table_signal_chunks"):
        terms.append("таблицы ведомости спецификации")
    return [term for term in terms if term.strip()]


def _score_section(question: str, terms: Iterable[str], hints: Iterable[str]) -> int:
    haystack = " ".join([question, *terms]).casefold()
    score = 0
    for hint in hints:
        h = hint.casefold()
        if h and h in haystack:
            score += 4
    return score


def build_reading_plan(question: str, notebooks: list[dict[str, Any]], *, max_sections: int = 6) -> list[StudySection]:
    """Build a compact plan from notebook maps.

    The plan is navigation: it says where to read first, then retrieval must bring
    real sources for the answer.
    """
    terms: list[str] = []
    for notebook in notebooks:
        terms.extend(_profile_terms(notebook))
    term_text = " ".join(dict.fromkeys(terms))[:1600]
    sections = [
        (
            "composition",
            "Состав комплекта и стадия",
            ["состав", "ведомость", "том", "раздел", "пояснительная", "стадия", "шифр", "ТЭП"],
            "понять, что за корпус документов и какие разделы представлены",
        ),
        (
            "architecture_structural",
            "Архитектура, конструктив и объёмно-планировочные решения",
            ["архитектур", "конструктив", "КР", "АР", "фундамент", "каркас", "плита", "стены", "кровля"],
            "вытащить строительную основу проекта",
        ),
        (
            "engineering_systems",
            "Инженерные системы",
            ["ИОС", "ОВ", "ВК", "ЭОМ", "СС", "АПС", "СОУЭ", "теплоснабжение", "водоснабжение", "канализация", "вентиляция"],
            "разнести инженерку по системам, а не смешивать с отделкой",
        ),
        (
            "specs_tables",
            "Ведомости, спецификации и таблицы",
            ["ведомость", "спецификация", "ВОР", "таблица", "оборудование", "материалы", "объёмы"],
            "найти табличные данные, которые должны попасть в артефакт",
        ),
        (
            "normative_refs",
            "Нормативные ссылки и требования",
            ["ГОСТ", "СП", "СНиП", "ПП 87", "норматив", "требования"],
            "собрать проверяемые нормативные якоря",
        ),
        (
            "gaps",
            "Пробелы и что проверить руками",
            ["отсутствует", "не представлен", "замечания", "уточнить", "нет данных", "не найден"],
            "показать оператору, чего не хватает для уверенного вывода",
        ),
    ]
    ranked = []
    by_id: dict[str, StudySection] = {}
    for order, (section_id, title, hints, reason) in enumerate(sections):
        score = _score_section(question, terms, hints)
        if section_id in {"composition", "engineering_systems", "specs_tables", "gaps"}:
            score += 2
        query = " ".join([question, title, *hints[:8], term_text[:600]]).strip()
        section = StudySection(section_id, title, query, reason, hints[:8])
        by_id[section_id] = section
        ranked.append((score, order, section_id))
    selected = {section_id for _score, _order, section_id in sorted(ranked, key=lambda item: (-item[0], item[1]))[:max_sections]}
    return [by_id[section_id] for _score, _order, section_id in sorted(ranked, key=lambda item: item[1]) if section_id in selected]


def build_dataset_notebooks(dataset_ids: list[str], *, storage_root: Path = Path("storage/datasets")) -> list[dict[str, Any]]:
    notebooks: list[dict[str, Any]] = []
    for dataset_id in dataset_ids[:5]:
        try:
            notebooks.append(build_dataset_notebook(str(dataset_id), storage_root=storage_root, depth="deep"))
        except Exception as error:  # noqa: BLE001
            logger.warning("[NOTEBOOK_STUDY] notebook skipped %s: %s", dataset_id, error)
    return notebooks


async def build_notebook_study_pack(
    *,
    question: str,
    dataset_ids: list[str],
    retrieve: RetrieveFn,
    storage_root: Path = Path("storage/datasets"),
    max_sections: int = 6,
) -> StudyPack:
    notebooks = build_dataset_notebooks(dataset_ids, storage_root=storage_root)
    plan = build_reading_plan(question, notebooks, max_sections=max_sections)
    chunks_by_section: dict[str, list[Any]] = {}
    gaps: list[str] = []
    for section in plan:
        try:
            retrieved = await retrieve(section.query)
        except Exception as error:  # noqa: BLE001
            logger.warning("[NOTEBOOK_STUDY] section retrieve failed %s: %s", section.id, error)
            retrieved = []
        ranked = rank_chunks_for_question(section.query, list(retrieved or []))
        focused = concentrate_sources(ranked, max_docs=2, min_score=0.0, max_chunks=4)
        chunks_by_section[section.id] = focused
        if not focused:
            gaps.append(f"{section.title}: не найдено уверенных источников")
    if not notebooks:
        gaps.append("Блокнот области не построен: нет доступного deep-паспорта датасета")
    return StudyPack(notebooks=notebooks, plan=plan, chunks_by_section=chunks_by_section, gaps=gaps)


def prompt_block(pack: StudyPack) -> str:
    lines = [
        "Режим инженерного чтения блокнота.",
        "Сначала держи в голове план чтения, затем синтезируй ответ только по найденным источникам.",
        "Блокнот и план — navigation, не evidence.",
        "",
        "План чтения:",
    ]
    for idx, section in enumerate(pack.plan, 1):
        hits = len(pack.chunks_by_section.get(section.id, []))
        lines.append(f"{idx}. {section.title}: {section.reason}; найдено фрагментов: {hits}.")
    if pack.gaps:
        lines.append("")
        lines.append("Пробелы чтения: " + "; ".join(pack.gaps[:6]))
    lines.append("")
    lines.append(
        "Ответ в чате сделай краткой инженерной сводкой: 5-8 строк или короткий список, "
        "без большой таблицы. Подробности, таблицы и источники будут в артефакте."
    )
    return "\n".join(lines)


def _snippet(text: str, limit: int = 360) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip() + " ..."


def format_study_artifact(question: str, pack: StudyPack) -> str:
    lines = [
        "# Инженерный блокнот",
        "",
        f"**Запрос:** {question}",
        "",
        "## План чтения",
        "",
        "| Раздел | Зачем читаем | Найдено |",
        "|---|---|---:|",
    ]
    for section in pack.plan:
        hits = len(pack.chunks_by_section.get(section.id, []))
        lines.append(f"| {section.title} | {section.reason} | {hits} |")

    lines.extend(["", "## Источники по разделам"])
    for section in pack.plan:
        lines.extend(["", f"### {section.title}", ""])
        chunks = pack.chunks_by_section.get(section.id, [])
        if not chunks:
            lines.append("Источник не найден в выбранной области.")
            continue
        lines.extend(["| Документ | Score | Фрагмент |", "|---|---:|---|"])
        for chunk in chunks:
            doc = str(getattr(chunk, "doc_name", "") or "источник").replace("|", "/")
            try:
                score = f"{float(getattr(chunk, 'score', 0.0) or 0.0):.3f}"
            except (TypeError, ValueError):
                score = "—"
            text = _snippet(getattr(chunk, "content", "")).replace("|", "/")
            lines.append(f"| {doc} | {score} | {text} |")

    lines.extend(["", "## Пробелы"])
    if pack.gaps:
        for gap in pack.gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- Явных пробелов на этапе чтения не найдено; это не заменяет проверку полноты исходного комплекта.")
    lines.extend([
        "",
        "## Граница",
        "",
        "Этот артефакт показывает маршрут чтения и найденные фрагменты. Итоговые утверждения должны ссылаться на источники из ответа; числа считаются отдельными инструментами, не этим блокнотом.",
    ])
    return "\n".join(lines)
