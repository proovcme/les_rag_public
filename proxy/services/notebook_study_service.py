"""Notebook-guided project study layer.

This is a navigation layer, not evidence. It uses dataset notebooks to build a
reading plan, then retrieves evidence for each section before the normal LLM
synthesis step.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from proxy.services.notebook_service import build_dataset_notebook
from proxy.services.saferag_service import concentrate_sources, rank_chunks_for_question

logger = logging.getLogger(__name__)

RetrieveFn = Callable[[str], Awaitable[list[Any]]]
RetrieveFileFn = Callable[[str, str], Awaitable[list[Any]]]


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
    targeted_files: list[dict[str, Any]] = field(default_factory=list)
    chunks_by_file: dict[str, list[Any]] = field(default_factory=dict)

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
        for file_name in [str(item.get("file_name") or "") for item in self.targeted_files]:
            for chunk in self.chunks_by_file.get(file_name, []):
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
            "targeted_files": [
                {
                    "file_name": item.get("file_name"),
                    "reason": item.get("reason"),
                    "score": item.get("score"),
                    "hits": len(self.chunks_by_file.get(str(item.get("file_name") or ""), [])),
                }
                for item in self.targeted_files
            ],
            "gaps": self.gaps,
        }


_BROAD_STUDY_RE = re.compile(
    r"\b("
    r"расскажи|рассказать|разбери|разобрать|обзор|сводк[ауи]|"
    r"что\s+внутри|что\s+есть|что\s+(?:это\s+)?за|что\s+по\s+проект|"
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


def _score_hints(text: str, hints: Iterable[str]) -> int:
    haystack = text.casefold()
    score = 0
    for hint in hints:
        h = hint.casefold()
        if h and h in haystack:
            score += 4
    return score


def _read_parallelism() -> int:
    try:
        return max(1, min(8, int(os.getenv("LES_NOTEBOOK_STUDY_PARALLELISM", "3"))))
    except ValueError:
        return 3


def build_reading_plan(question: str, notebooks: list[dict[str, Any]], *, max_sections: int = 4) -> list[StudySection]:
    """Build a compact plan from notebook maps.

    The plan is navigation: it says where to read first, then retrieval must bring
    real sources for the answer.
    """
    terms: list[str] = []
    for notebook in notebooks:
        terms.extend(_profile_terms(notebook))
    term_text = " ".join(dict.fromkeys(terms))[:1600]
    q = (question or "").strip()
    is_general = bool(_DIRECT_RE.search(q) or (_BROAD_STUDY_RE.search(q) and _AREA_RE.search(q)))
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
        question_score = _score_hints(q, hints)
        profile_score = min(4, _score_hints(" ".join(terms), hints))
        score = question_score + profile_score
        if is_general and section_id in {"composition", "engineering_systems", "specs_tables", "gaps"}:
            score += 3
        elif not is_general and section_id == "gaps":
            score += 1
        query = " ".join([question, title, *hints[:8], term_text[:600]]).strip()
        section = StudySection(section_id, title, query, reason, hints[:8])
        by_id[section_id] = section
        ranked.append((score, question_score, order, section_id))

    max_sections = max(1, min(max_sections, len(sections)))
    minimum = min(max_sections, 3 if is_general else 2)
    sorted_ranked = sorted(ranked, key=lambda item: (-item[0], item[2]))
    selected = {
        section_id
        for score, question_score, _order, section_id in sorted_ranked
        if score > 0 and (is_general or question_score > 0 or section_id == "gaps")
    }
    if len(selected) < minimum:
        selected.update(section_id for _score, _question_score, _order, section_id in sorted_ranked[:minimum])
    if len(selected) > max_sections:
        selected = {section_id for _score, _question_score, _order, section_id in sorted_ranked[:max_sections]}
    return [
        by_id[section_id]
        for _score, _question_score, _order, section_id in sorted(ranked, key=lambda item: item[2])
        if section_id in selected
    ]


def build_dataset_notebooks(dataset_ids: list[str], *, storage_root: Path = Path("storage/datasets")) -> list[dict[str, Any]]:
    notebooks: list[dict[str, Any]] = []
    for dataset_id in dataset_ids[:5]:
        try:
            notebooks.append(build_dataset_notebook(str(dataset_id), storage_root=storage_root, depth="deep"))
        except Exception as error:  # noqa: BLE001
            logger.warning("[NOTEBOOK_STUDY] notebook skipped %s: %s", dataset_id, error)
    return notebooks


_PASSPORT_TERMS = (
    ("состав проекта", 170),
    ("состав разделов", 160),
    ("пояснительная записка", 150),
    ("03_пз", 106),
    ("_пз", 96),
    ("содержание тома", 88),
    ("содержание", 30),
    ("задание на проектирование", 96),
    ("техническое задание", 88),
    ("технико-эконом", 84),
    ("тэп", 84),
    ("основные показатели", 80),
    ("общие данные", 76),
    ("сту", 68),
    ("технические условия", 42),
    ("обложка", 18),
)
_TARGETABLE_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|xlsm|csv|txt|md)$", re.IGNORECASE)


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("ё", "е").replace("\\", "/")).strip()


def _targetable_file(file_name: str, chunk_count: int | None = None) -> bool:
    if not file_name or not _TARGETABLE_EXT_RE.search(file_name):
        return False
    if chunk_count is not None and chunk_count <= 0:
        return False
    return True


def _iter_memory_cards(notebooks: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    for notebook in notebooks:
        memory = notebook.get("typed_memory") if isinstance(notebook.get("typed_memory"), dict) else {}
        for item in memory.get("file_cards") or []:
            file_name = str(item.get("file_name") or "")
            if file_name and file_name not in seen:
                seen.add(file_name)
                yield dict(item)
        for item in memory.get("important_files") or []:
            file_name = str(item.get("file_name") or "")
            if file_name and file_name not in seen:
                seen.add(file_name)
                yield dict(item)
        reader = memory.get("reader_output") if memory.get("reader_status") == "model" else None
        if not isinstance(reader, dict):
            continue
        for item in reader.get("file_roles") or []:
            file_name = str(item.get("file_name") or "")
            if file_name and file_name not in seen:
                seen.add(file_name)
                yield {
                    "file_name": file_name,
                    "document_role": item.get("role") or "",
                    "summary": item.get("what_inside") or "",
                    "confidence": item.get("confidence") or 0,
                }
        for where in reader.get("where_to_look") or []:
            for file_name in where.get("target_files") or []:
                file_name = str(file_name or "")
                if file_name and file_name not in seen:
                    seen.add(file_name)
                    yield {
                        "file_name": file_name,
                        "document_role": where.get("question_type") or "",
                        "summary": where.get("reason") or "",
                        "confidence": 0.7,
                    }


def _iter_inventory_cards(project_inventory: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
    inv = (project_inventory or {}).get("inventory") if isinstance(project_inventory, dict) else {}
    if not isinstance(inv, dict):
        return
    for item in inv.get("files") or []:
        if isinstance(item, dict):
            yield dict(item)


def _passport_file_score(card: dict[str, Any]) -> tuple[int, str]:
    file_name = str(card.get("file_name") or "")
    try:
        chunk_count = int(card.get("chunk_count")) if card.get("chunk_count") is not None else None
    except (TypeError, ValueError):
        chunk_count = None
    if not _targetable_file(file_name, chunk_count):
        return 0, ""
    blob = _norm_text(
        " ".join(
            str(x or "")
            for x in (
                file_name,
                card.get("name"),
                card.get("document_role"),
                card.get("role"),
                card.get("summary"),
                card.get("what_inside"),
                " ".join(str(v) for v in (card.get("content_layers") or [])),
            )
        )
    )
    score = 0
    reasons: list[str] = []
    for term, weight in _PASSPORT_TERMS:
        if _norm_text(term) in blob:
            score += weight
            reasons.append(term)
    if "technical_docs" in blob or "технич" in blob:
        score += 8
    if "estimate" in blob or "смет" in blob:
        score -= 18
    if chunk_count:
        score += min(10, max(1, chunk_count // 80))
    try:
        confidence = float(card.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    score += int(max(0.0, min(1.0, confidence)) * 6)
    return score, ", ".join(dict.fromkeys(reasons[:4]))


def build_target_file_plan(
    notebooks: list[dict[str, Any]],
    *,
    project_inventory: dict[str, Any] | None = None,
    max_files: int = 10,
) -> list[dict[str, Any]]:
    """Choose concrete files worth opening for broad project answers.

    This is a generic navigation heuristic over typed memory/inventory. It does
    not assert facts and does not encode object-specific templates: it only
    asks retrieval to read files whose role/name usually carries passport data.
    """
    by_file: dict[str, dict[str, Any]] = {}
    for card in [*_iter_memory_cards(notebooks), *_iter_inventory_cards(project_inventory)]:
        file_name = str(card.get("file_name") or "")
        if not file_name:
            continue
        score, reason = _passport_file_score(card)
        if score <= 0:
            continue
        prev = by_file.get(file_name)
        if prev and int(prev.get("score") or 0) >= score:
            continue
        by_file[file_name] = {
            "file_name": file_name,
            "reason": reason or str(card.get("document_role") or card.get("role") or "паспортный документ"),
            "score": score,
        }
    ranked = sorted(by_file.values(), key=lambda item: (-int(item.get("score") or 0), str(item.get("file_name") or "")))
    return ranked[: max(0, max_files)]


async def build_notebook_study_pack(
    *,
    question: str,
    dataset_ids: list[str],
    retrieve: RetrieveFn,
    retrieve_file: RetrieveFileFn | None = None,
    project_inventory: dict[str, Any] | None = None,
    storage_root: Path = Path("storage/datasets"),
    max_sections: int = 4,
) -> StudyPack:
    notebooks = build_dataset_notebooks(dataset_ids, storage_root=storage_root)
    plan = build_reading_plan(question, notebooks, max_sections=max_sections)
    targeted_files = build_target_file_plan(notebooks, project_inventory=project_inventory)
    chunks_by_section: dict[str, list[Any]] = {}
    chunks_by_file: dict[str, list[Any]] = {}
    gaps: list[str] = []
    semaphore = asyncio.Semaphore(_read_parallelism())

    async def retrieve_section(section: StudySection) -> tuple[str, list[Any], str | None]:
        async with semaphore:
            try:
                retrieved = await retrieve(section.query)
            except Exception as error:  # noqa: BLE001
                logger.warning("[NOTEBOOK_STUDY] section retrieve failed %s: %s", section.id, error)
                retrieved = []
        ranked = rank_chunks_for_question(section.query, list(retrieved or []))
        focused = concentrate_sources(ranked, max_docs=2, min_score=0.0, max_chunks=4)
        gap = None if focused else f"{section.title}: не найдено уверенных источников"
        return section.id, focused, gap

    async def retrieve_target_file(item: dict[str, Any]) -> tuple[str, list[Any], str | None]:
        file_name = str(item.get("file_name") or "")
        if not file_name or retrieve_file is None:
            return file_name, [], None
        query = (
            f"{question}\n"
            f"Прочитай паспортный/навигационный файл: {file_name}. "
            "Ищи: наименование объекта, адрес, стадия, состав проекта, разделы, ТЭП, исходные данные."
        )
        async with semaphore:
            try:
                retrieved = await retrieve_file(query, file_name)
            except Exception as error:  # noqa: BLE001
                logger.warning("[NOTEBOOK_STUDY] target file retrieve failed %s: %s", file_name, error)
                retrieved = []
        ranked = rank_chunks_for_question(query, list(retrieved or []))
        focused = concentrate_sources(ranked, max_docs=1, min_score=0.0, max_chunks=3)
        gap = None if focused else f"{file_name}: файл найден в карте, но фрагменты не добрались"
        return file_name, focused, gap

    results = await asyncio.gather(*(retrieve_section(section) for section in plan))
    by_section = {section_id: (focused, gap) for section_id, focused, gap in results}
    for section in plan:
        try:
            focused, gap = by_section[section.id]
        except KeyError:
            focused, gap = [], f"{section.title}: не найдено уверенных источников"
        chunks_by_section[section.id] = focused
        if gap:
            gaps.append(gap)
    if retrieve_file is not None and targeted_files:
        file_results = await asyncio.gather(*(retrieve_target_file(item) for item in targeted_files))
        for file_name, focused, gap in file_results:
            if file_name:
                chunks_by_file[file_name] = focused
            if gap:
                gaps.append(gap)
    if not notebooks:
        gaps.append("Блокнот области не построен: нет доступного deep-паспорта датасета")
    return StudyPack(
        notebooks=notebooks,
        plan=plan,
        chunks_by_section=chunks_by_section,
        gaps=gaps,
        targeted_files=targeted_files,
        chunks_by_file=chunks_by_file,
    )


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
    if pack.targeted_files:
        lines.append("")
        lines.append("Точечно добранные файлы:")
        for item in pack.targeted_files[:8]:
            hits = len(pack.chunks_by_file.get(str(item.get("file_name") or ""), []))
            lines.append(f"- {item.get('file_name')} — {item.get('reason')}; фрагментов: {hits}.")
    lines.append("")
    lines.append(
        "Ответ в чате сделай полноценной инженерной сводкой по широте запроса: для общего вопроса "
        "дай широкий структурированный обзор с подзаголовками и списками, для точного вопроса отвечай "
        "узко. Таблицы и длинные фрагменты не дублируй из артефакта, но не режь смысл ради краткости."
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
        "## Найденные материалы по разделам",
    ]
    for section in pack.plan:
        lines.extend(["", f"### {section.title}", ""])
        chunks = pack.chunks_by_section.get(section.id, [])
        if not chunks:
            lines.append("Источник не найден в выбранной области.")
            continue
        lines.extend(["| Документ | Релевантность | Фрагмент |", "|---|---:|---|"])
        for chunk in chunks:
            doc = str(getattr(chunk, "doc_name", "") or "источник").replace("|", "/")
            try:
                score = f"{float(getattr(chunk, 'score', 0.0) or 0.0):.3f}"
            except (TypeError, ValueError):
                score = "—"
            text = _snippet(getattr(chunk, "content", "")).replace("|", "/")
            lines.append(f"| {doc} | {score} | {text} |")

    if pack.targeted_files:
        lines.extend(["", "## Точечно открытые файлы"])
        for item in pack.targeted_files:
            file_name = str(item.get("file_name") or "файл")
            lines.extend(["", f"### {file_name}", ""])
            chunks = pack.chunks_by_file.get(file_name, [])
            if not chunks:
                lines.append("Файл найден в карте, но фрагменты не добрались в этом чтении.")
                continue
            lines.extend(["| Релевантность | Фрагмент |", "|---:|---|"])
            for chunk in chunks:
                try:
                    score = f"{float(getattr(chunk, 'score', 0.0) or 0.0):.3f}"
                except (TypeError, ValueError):
                    score = "—"
                text = _snippet(getattr(chunk, "content", "")).replace("|", "/")
                lines.append(f"| {score} | {text} |")

    lines.extend(["", "## Пробелы"])
    if pack.gaps:
        for gap in pack.gaps:
            lines.append(f"- {gap}")
    else:
        lines.append("- Явных пробелов на этапе чтения не найдено; это не заменяет проверку полноты исходного комплекта.")

    lines.extend([
        "",
        "## Как читалось",
        "",
        "| Раздел | Зачем читаем | Найдено |",
        "|---|---|---:|",
    ])
    for section in pack.plan:
        hits = len(pack.chunks_by_section.get(section.id, []))
        lines.append(f"| {section.title} | {section.reason} | {hits} |")
    lines.extend([
        "",
        "## Граница",
        "",
        "Этот артефакт показывает маршрут чтения и найденные фрагменты. Итоговые утверждения должны ссылаться на источники из ответа; числа считаются отдельными инструментами, не этим блокнотом.",
    ])
    return "\n".join(lines)
