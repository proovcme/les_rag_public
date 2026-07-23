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
RESEARCH_GUIDE_SCHEMA = "notebook_research_guide_v1"


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
                    "coverage_group": item.get("coverage_group"),
                    "hits": len(self.chunks_by_file.get(str(item.get("file_name") or ""), [])),
                    "retrieval_candidates": int(item.get("retrieval_candidates") or 0),
                    "discarded_mismatched_chunks": int(item.get("discarded_mismatched_chunks") or 0),
                }
                for item in self.targeted_files
            ],
            "research_guide": self.research_guide(),
            "gaps": self.gaps,
        }

    def research_guide(self) -> dict[str, Any]:
        """A NotebookLM-like study guide derived only from navigation and reads.

        The guide names where the system looked and what to investigate next.
        It deliberately contains no conclusions from source text; chunks remain
        the only evidence passed to the answer model.
        """
        section_total = len(self.plan)
        section_hits = sum(1 for section in self.plan if self.chunks_by_section.get(section.id))
        target_total = len(self.targeted_files)
        target_hits = sum(
            1
            for item in self.targeted_files
            if self.chunks_by_file.get(str(item.get("file_name") or ""))
        )
        target_groups = {str(item.get("coverage_group") or "") for item in self.targeted_files}
        target_hit_groups = {
            str(item.get("coverage_group") or "")
            for item in self.targeted_files
            if self.chunks_by_file.get(str(item.get("file_name") or ""))
        }
        mismatched_chunks = sum(int(item.get("discarded_mismatched_chunks") or 0) for item in self.targeted_files)
        route_total = section_total + target_total
        route_hits = section_hits + target_hits
        if not self.notebooks:
            status = "no_notebook"
        elif route_total == 0 or route_hits == 0:
            status = "needs_attention"
        elif route_hits < route_total:
            status = "partial"
        else:
            status = "ready"

        source_maps = []
        for notebook in self.notebooks:
            memory = notebook.get("typed_memory") if isinstance(notebook.get("typed_memory"), dict) else {}
            reader_status = str(memory.get("reader_status") or "unknown")
            source_maps.append({
                "dataset_id": notebook.get("dataset_id"),
                "revision_id": memory.get("revision_id") or "",
                "revision_available": bool(memory.get("revision_id")),
                "topic_map": bool(memory.get("topic_map")),
                "section_map": bool(memory.get("section_map")),
                "reader_status": reader_status,
                "reader_pass": reader_status == "model",
                "file_cards": len(memory.get("file_cards") or []),
            })

        start_sources = [
            {
                "file_name": item.get("file_name"),
                "reason": item.get("reason"),
                "retrieved": bool(self.chunks_by_file.get(str(item.get("file_name") or ""))),
            }
            for item in self.targeted_files[:6]
        ]
        if not start_sources:
            for notebook in self.notebooks:
                summary = notebook.get("notebook_summary") if isinstance(notebook.get("notebook_summary"), dict) else {}
                for item in (summary.get("priority_files") or [])[:6 - len(start_sources)]:
                    if not isinstance(item, dict) or not item.get("file_name"):
                        continue
                    start_sources.append({
                        "file_name": item.get("file_name"),
                        "reason": item.get("role_hint") or "приоритетный файл карты",
                        "retrieved": False,
                    })
                    if len(start_sources) >= 6:
                        break
                if len(start_sources) >= 6:
                    break

        prompts: list[dict[str, str]] = []
        seen_questions: set[str] = set()
        for section in self.plan[:4]:
            question = f"Какие фрагменты выбранного корпуса подтверждают раздел «{section.title}»?"
            if question in seen_questions:
                continue
            seen_questions.add(question)
            prompts.append({
                "kind": "corpus_section",
                "question": question,
                "anchor": section.title,
            })
        for source in start_sources:
            file_name = str(source.get("file_name") or "").strip()
            if not file_name:
                continue
            question = f"Что в документе «{file_name}» отвечает на текущий вопрос?"
            if question in seen_questions:
                continue
            seen_questions.add(question)
            prompts.append({"kind": "source", "question": question, "anchor": file_name})
            if len(prompts) >= 6:
                break
        if self.gaps:
            prompts.append({
                "kind": "gap",
                "question": "Какие документы или разделы нужно добавить, чтобы закрыть пробелы чтения?",
                "anchor": "gaps",
            })

        return {
            "schema": RESEARCH_GUIDE_SCHEMA,
            "context_role": "navigation",
            "is_evidence": False,
            "status": status,
            "source_maps": source_maps,
            "coverage": {
                "planned_sections": section_total,
                "sections_with_hits": section_hits,
                "targeted_files": target_total,
                "targeted_files_with_hits": target_hits,
                "targeted_file_groups": len(target_groups),
                "targeted_file_groups_with_hits": len(target_hit_groups),
                "targeted_chunks_discarded_as_mismatch": mismatched_chunks,
                "route_steps": route_total,
                "route_steps_with_hits": route_hits,
                "ratio": round(route_hits / route_total, 3) if route_total else 0.0,
            },
            "start_sources": start_sources,
            "suggested_questions": prompts[:6],
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


def _plan_id(prefix: str, *parts: str) -> str:
    raw = "-".join(str(part or "") for part in parts)
    return prefix + ":" + re.sub(r"[^a-z0-9а-яё]+", "-", raw.casefold()).strip("-")[:120]


def _file_group(file_name: str, role: str = "") -> str:
    """Return a corpus-derived grouping key without assuming a document taxonomy."""
    parent = Path(str(file_name or "").replace("\\", "/")).parent
    if str(parent) not in {"", "."}:
        return str(parent)
    return str(role or "документы без папки")


def build_reading_plan(question: str, notebooks: list[dict[str, Any]], *, max_sections: int = 4) -> list[StudySection]:
    """Build a bounded reading plan from the selected corpus itself.

    No project/domain section is injected here.  Topics, headings, file groups and
    roles must exist in the dataset navigation before they can become a read step.
    The resulting plan is still navigation; retrieval supplies the evidence.
    """
    q = (question or "").strip()
    is_general = bool(_DIRECT_RE.search(q) or (_BROAD_STUDY_RE.search(q) and _AREA_RE.search(q)))
    candidates: list[tuple[int, int, int, StudySection]] = []
    seen_ids: set[str] = set()
    order = 0

    def add(*, section_id: str, title: str, hints: list[str], reason: str, base_score: int) -> None:
        nonlocal order
        if not title or section_id in seen_ids:
            return
        seen_ids.add(section_id)
        clean_hints = [str(item).strip() for item in hints if str(item).strip()][:10]
        question_score = _score_hints(q, clean_hints)
        query = " ".join([q, title, *clean_hints]).strip()
        candidates.append((base_score + question_score, question_score, order, StudySection(section_id, title, query, reason, clean_hints)))
        order += 1

    for notebook in notebooks:
        dataset_id = str(notebook.get("dataset_id") or "dataset")
        memory = notebook.get("typed_memory") if isinstance(notebook.get("typed_memory"), dict) else {}
        section_map = memory.get("section_map") if isinstance(memory.get("section_map"), dict) else {}
        for file_item in section_map.get("files") or []:
            if not isinstance(file_item, dict):
                continue
            file_name = str(file_item.get("file_name") or "").strip()
            for item in (file_item.get("sections") or [])[:2]:
                if not isinstance(item, dict):
                    continue
                heading = str(item.get("heading") or "").strip()
                if not file_name or not heading:
                    continue
                add(
                    section_id=_plan_id("section", dataset_id, file_name, heading),
                    title=heading[:180],
                    hints=[file_name, heading],
                    reason="заголовок реально найден в документе выбранного корпуса",
                    base_score=20 + min(10, int(item.get("chunk_count") or 0)),
                )

        groups: dict[str, list[dict[str, Any]]] = {}
        for card in memory.get("file_cards") or []:
            if not isinstance(card, dict):
                continue
            file_name = str(card.get("file_name") or "").strip()
            if not file_name or int(card.get("chunk_count") or 0) <= 0:
                continue
            groups.setdefault(_file_group(file_name, str(card.get("document_role") or "")), []).append(card)
        for group, cards in groups.items():
            cards.sort(key=lambda item: (-int(item.get("chunk_count") or 0), str(item.get("file_name") or "")))
            names = [str(item.get("file_name") or "") for item in cards[:4]]
            roles = [str(item.get("document_role") or "") for item in cards[:2]]
            add(
                section_id=_plan_id("files", dataset_id, group),
                title=f"Файлы: {group}"[:180],
                hints=[group, *names, *roles],
                reason="группа индексированных файлов из реестра",
                base_score=10 + min(12, sum(int(item.get("chunk_count") or 0) for item in cards) // 80),
            )
        # A corpus may have only one folder or no trustworthy role.  Individual
        # readable files are still a data-derived fallback; never invent a domain
        # section just to make a broad plan look complete.
        for cards in groups.values():
            for card in cards[:4]:
                file_name = str(card.get("file_name") or "").strip()
                if not file_name:
                    continue
                add(
                    section_id=_plan_id("file", dataset_id, file_name),
                    title=file_name[:180],
                    hints=[file_name, str(card.get("document_role") or ""), str(card.get("summary") or "")],
                    reason="индексированный файл выбранного корпуса",
                    base_score=6 + min(10, int(card.get("chunk_count") or 0) // 20),
                )

    if not candidates:
        return [StudySection(
            "corpus-overview",
            "Доступные документы выбранного корпуса",
            q,
            "карта корпуса не дала тем или файлов; нужен широкий retrieval без подстановки доменных разделов",
            [],
        )]

    max_sections = max(1, min(max_sections, len(candidates)))
    minimum = min(max_sections, 3 if is_general else 1)
    ranked = sorted(candidates, key=lambda item: (-item[0], -item[1], item[2], item[3].id))
    selected = [item[3] for item in ranked[:max(minimum, min(max_sections, len(ranked)))]]
    return selected[:max_sections]


def build_dataset_notebooks(dataset_ids: list[str], *, storage_root: Path = Path("storage/datasets")) -> list[dict[str, Any]]:
    notebooks: list[dict[str, Any]] = []
    for dataset_id in dataset_ids[:5]:
        try:
            notebooks.append(build_dataset_notebook(str(dataset_id), storage_root=storage_root, depth="deep"))
        except Exception as error:  # noqa: BLE001
            logger.warning("[NOTEBOOK_STUDY] notebook skipped %s: %s", dataset_id, error)
    return notebooks


_TARGETABLE_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|xlsm|csv|txt|md)$", re.IGNORECASE)


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold().replace("ё", "е").replace("\\", "/")).strip()


def _targetable_file(file_name: str, chunk_count: int | None = None) -> bool:
    if not file_name or not _TARGETABLE_EXT_RE.search(file_name):
        return False
    if chunk_count is not None and chunk_count <= 0:
        return False
    return True


def _normal_file_ref(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip("/ ").casefold()


def _chunk_matches_target_file(chunk: Any, target_file: str) -> bool:
    """Require target-file evidence to identify the selected source, never a basename guess."""
    target = _normal_file_ref(target_file)
    if not target:
        return False
    candidates = [str(getattr(chunk, "doc_name", "") or "")]
    meta = getattr(chunk, "meta", None) or getattr(chunk, "metadata", None) or {}
    if isinstance(meta, dict):
        candidates.extend(str(meta.get(key) or "") for key in ("file_name", "source_file", "doc_name"))
    for candidate in candidates:
        source = _normal_file_ref(candidate)
        if not source:
            continue
        if source == target or source.endswith(f"/{target}") or target.endswith(f"/{source}"):
            return True
    return False


def _iter_memory_cards(notebooks: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    for notebook in notebooks:
        memory = notebook.get("typed_memory") if isinstance(notebook.get("typed_memory"), dict) else {}
        file_cards = [dict(item) for item in (memory.get("file_cards") or []) if isinstance(item, dict)]
        known_files = {str(item.get("file_name") or "") for item in file_cards if str(item.get("file_name") or "")}
        for item in file_cards:
            file_name = str(item.get("file_name") or "")
            if file_name and file_name not in seen:
                seen.add(file_name)
                yield item
        for item in memory.get("important_files") or []:
            file_name = str(item.get("file_name") or "")
            if file_name and file_name in known_files and file_name not in seen:
                seen.add(file_name)
                yield dict(item)
        reader = memory.get("reader_output") if memory.get("reader_status") == "model" else None
        if not isinstance(reader, dict):
            continue
        for item in reader.get("file_roles") or []:
            file_name = str(item.get("file_name") or "")
            if file_name and file_name in known_files and file_name not in seen:
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
                if file_name and file_name in known_files and file_name not in seen:
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


def _broad_file_score(card: dict[str, Any], question: str = "") -> tuple[int, str]:
    """Score readable files without preferring a construction-specific document type."""
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
    score = 1
    reasons: list[str] = []
    question_terms = [term for term in re.findall(r"[\wа-яё-]{4,}", _norm_text(question)) if len(term) >= 4]
    matched_question_terms = [term for term in question_terms if term in blob]
    if matched_question_terms:
        score += min(24, len(set(matched_question_terms)) * 6)
        reasons.extend(matched_question_terms[:4])
    if chunk_count:
        score += min(18, max(1, chunk_count // 40))
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
    question: str = "",
    max_files: int = 10,
) -> list[dict[str, Any]]:
    """Choose a bounded, corpus-derived spread of files for broad reading.

    The plan does not assume that a dataset contains a project passport, an AR
    volume register, a specification, or any other fixed kind of document.  It
    first takes one readable representative from each actual folder/role group,
    then fills remaining capacity by relevance and available chunk coverage.
    """
    by_file: dict[str, dict[str, Any]] = {}
    for card in [*_iter_memory_cards(notebooks), *_iter_inventory_cards(project_inventory)]:
        file_name = str(card.get("file_name") or "")
        if not file_name:
            continue
        score, reason = _broad_file_score(card, question)
        if score <= 0:
            continue
        prev = by_file.get(file_name)
        if prev and int(prev.get("score") or 0) >= score:
            continue
        by_file[file_name] = {
            "file_name": file_name,
            "reason": reason or str(card.get("document_role") or card.get("role") or "индексированный файл"),
            "score": score,
            "coverage_group": _file_group(file_name, str(card.get("document_role") or card.get("role") or "")),
        }
    ranked = sorted(by_file.values(), key=lambda item: (-int(item.get("score") or 0), str(item.get("file_name") or "")))
    selected: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for item in ranked:
        group = str(item.get("coverage_group") or "")
        if group and group in seen_groups:
            continue
        selected.append(item)
        seen_groups.add(group)
        if len(selected) >= max(0, max_files):
            return selected
    for item in ranked:
        if item in selected:
            continue
        selected.append(item)
        if len(selected) >= max(0, max_files):
            break
    return selected


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
    targeted_files = build_target_file_plan(notebooks, project_inventory=project_inventory, question=question)
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
            f"Прочитай выбранный файл: {file_name}. "
            "Извлеки только фрагменты, релевантные вопросу. Файл выбран для покрытия реального корпуса, "
            "а не как доказательство заранее заданного типа документа."
        )
        async with semaphore:
            try:
                retrieved = await retrieve_file(query, file_name)
            except Exception as error:  # noqa: BLE001
                logger.warning("[NOTEBOOK_STUDY] target file retrieve failed %s: %s", file_name, error)
                retrieved = []
        candidates = list(retrieved or [])
        matched = [chunk for chunk in candidates if _chunk_matches_target_file(chunk, file_name)]
        item["retrieval_candidates"] = len(candidates)
        item["discarded_mismatched_chunks"] = len(candidates) - len(matched)
        ranked = rank_chunks_for_question(query, matched)
        focused = concentrate_sources(ranked, max_docs=1, min_score=0.0, max_chunks=3)
        if focused:
            gap = None
        elif candidates and not matched:
            gap = f"{file_name}: retrieval вернул фрагменты другого файла; они исключены из evidence"
        else:
            gap = f"{file_name}: файл найден в карте, но фрагменты не добрались"
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
        gaps.append("Блокнот области не построен: нет доступной глубокой карты датасета")
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
        "План выбирается из реальных тем, заголовков и групп файлов корпуса; его покрытие ограничено и не доказывает полноту всего архива.",
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
        "Для общего вопроса «что есть в датасете» дай понятный обзор только по найденным фрагментам: "
        "что реально представлено, о чём эти материалы, какие файлы/таблицы важны и что осталось вне "
        "текущего чтения. Не подставляй заранее заданные типы документов. Для точного вопроса отвечай узко. "
        "Таблицы и длинные фрагменты не дублируй из артефакта, но не режь смысл ради краткости."
    )
    return "\n".join(lines)


def _snippet(text: str, limit: int = 360) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip() + " ..."


def format_study_artifact(question: str, pack: StudyPack) -> str:
    guide = pack.research_guide()
    coverage = guide.get("coverage") if isinstance(guide.get("coverage"), dict) else {}
    lines = [
        "# Инженерный блокнот",
        "",
        f"**Запрос:** {question}",
        "",
        "## Карта исследования",
        "",
        f"- Состояние маршрута: **{guide.get('status') or 'unknown'}**.",
        f"- План чтения: {coverage.get('sections_with_hits', 0)}/{coverage.get('planned_sections', 0)} разделов с фрагментами.",
        f"- Точечные источники: {coverage.get('targeted_files_with_hits', 0)}/{coverage.get('targeted_files', 0)} открыты с фрагментами.",
        f"- Группы файлов с фрагментами: {coverage.get('targeted_file_groups_with_hits', 0)}/{coverage.get('targeted_file_groups', 0)}.",
        "- Карта и вопросы ниже направляют чтение; выводы делаются только по найденным фрагментам.",
    ]
    start_sources = guide.get("start_sources") if isinstance(guide.get("start_sources"), list) else []
    if start_sources:
        lines.extend(["", "## С чего начать", ""])
        for source in start_sources:
            if not isinstance(source, dict):
                continue
            file_name = str(source.get("file_name") or "файл")
            reason = str(source.get("reason") or "приоритетный источник")
            state = "фрагменты найдены" if source.get("retrieved") else "ещё не прочитан точечно"
            lines.append(f"- **{file_name}** — {reason}; {state}.")
    suggested_questions = guide.get("suggested_questions") if isinstance(guide.get("suggested_questions"), list) else []
    if suggested_questions:
        lines.extend(["", "## Вопросы для продолжения", ""])
        for item in suggested_questions:
            if isinstance(item, dict) and item.get("question"):
                lines.append(f"- {item['question']}")
    lines.extend([
        "",
        "## Найденные материалы по разделам",
    ])
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
