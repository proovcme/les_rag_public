"""LES Unified Construction Harness v0.3 — единый evidence-driven слой по строительным intent'ам.

НЕ Profile→Workflow→Runtime rewrite, НЕ свободный агент, НЕ публичный режим. Тонкий слой за
feature-flag (LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED, OFF дефолт): keyword-роутинг intent →
per-intent facade (переиспользуют существующие сервисы) → единый evidence-контракт.

Каждый intent отвечает в RETRIEVED/COMPUTED/ASSUMED/MISSING/BLOCKED. Нормативный ответ без
источника запрещён; проектное описание без source → MISSING; число только из tool-результата;
final_total только при complete; мусорные документы НЕ в реестр (помечаются, не удаляются).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proxy.services.construction_harness_service import (
    run_construction_harness,
    spec_to_bor,
    retrieve_project_doc,
)
from proxy.services.evidence_contract import (
    ConstructionHarnessResult,
    EvidenceItem,
    EvidenceType,
    block_of,
)

# ── feature flag ─────────────────────────────────────────────────────────────────────────

def unified_enabled() -> bool:
    return os.getenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "").strip().lower() in ("1", "true", "yes")


# ── intent routing (keyword → план, НЕ ответ) ────────────────────────────────────────────

_INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("estimate_from_bor", ("собери лср", "лср по", "смету по ф9", "смета по ф9", "по вор", "по ф9",
                           "рассчитай по гэсн", "предварительн", "из ведомости")),
    ("bor_extract", ("извлеки вор", "сформируй вор", "ведомость объ", "спецификаци работ", "список работ из")),
    ("project_document_registry", ("реестр документ", "список документ", "что есть по проекту", "какие файлы",
                                   "не мусорн", "перечень документ")),
    ("project_summary", ("опиши проект", "что за проект", "сводка по проекту", "краткое описание проект",
                         "паспорт проект")),
    ("mail_qa", ("почт", "в переписк", "кто согласов", "что писали про", "найди письмо", "из писем")),
    ("table_agg", ("посчитай сумму", "итого по", "сгруппируй", "агрегируй", "сумму по")),
    ("asbuilt_extract", ("исполнительн", "журнал работ", "кс-2", "что выполнено", "акт ")),
    ("norm_qa", ("по нормам", " сп ", " гост", " снип", "огнестойкост", "аупт", "по нормативу", "норматив")),
    ("document_qa", ("в документе", "найди пункт", "по какому пункту", "сошлись на источник", "что говорит",
                     "что написано")),
]

_SUPPORTED_INTENTS = {"estimate_from_bor", "bor_extract", "project_document_registry", "project_summary",
                      "mail_qa", "table_agg", "asbuilt_extract", "norm_qa", "document_qa"}


@dataclass
class RouteResult:
    intent: str
    confidence: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)
    requires_project_scope: bool = False
    route_source: str = "keyword"
    warnings: list[str] = field(default_factory=list)


def route_construction_intent(question: str) -> RouteResult:
    """Keyword → intent (детерминированно, не LLM). Первое совпадение по приоритету. low/none → none."""
    ql = f" {(question or '').lower()} "
    for intent, terms in _INTENT_RULES:
        matched = [t for t in terms if t in ql]
        if matched:
            return RouteResult(intent=intent, confidence=0.6 + 0.1 * min(len(matched), 3),
                               matched_terms=matched,
                               requires_project_scope=intent in ("project_summary", "project_document_registry",
                                                                  "estimate_from_bor", "bor_extract", "mail_qa",
                                                                  "table_agg", "asbuilt_extract"))
    return RouteResult(intent="none", confidence=0.0)


# ── doc registry: реестр НЕ мусорных документов проекта ──────────────────────────────────

_NOISE_NAME_RE = re.compile(r"(~\$|\btemp\b|\btmp\b|копи|\bcopy\b|\bold\b|backup|резерв|\.bak\b|черновик)", re.I)
_DOC_EXT = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".dwg", ".parquet"}


@dataclass
class DocumentRecord:
    dataset_id: str
    file_name: str
    rel_path: str
    size: int
    doc_type: str = ""
    noise_flags: list[str] = field(default_factory=list)
    source_ref: str = ""

    @property
    def is_noise(self) -> bool:
        return bool(self.noise_flags)


def _classify_doc(ds: str, root: Path, p: Path) -> DocumentRecord:
    rel = p.relative_to(root).as_posix()
    size = p.stat().st_size if p.exists() else 0
    flags = []
    if _NOISE_NAME_RE.search(p.name):
        flags.append("служебное/временное имя")
    if size < 64:
        flags.append("пустой/слишком маленький файл")
    if p.suffix.lower() not in _DOC_EXT:
        flags.append("не проектный тип файла")
    return DocumentRecord(dataset_id=ds, file_name=p.name, rel_path=rel, size=size,
                          doc_type=p.suffix.lower().lstrip("."), noise_flags=flags,
                          source_ref=f"{ds}/{rel}")


def doc_registry(dataset_ids: list[str], *, storage_root: Path | None = None) -> dict[str, Any]:
    """Обойти storage датасетов → реестр документов с пометкой мусора (НЕ удаляя). RETRIEVED/MISSING."""
    root = storage_root or Path("storage/datasets")
    included, excluded = [], []
    for ds in dataset_ids:
        ddir = root / ds
        if not ddir.exists():
            continue
        for p in sorted(ddir.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            rec = _classify_doc(ds, ddir, p)
            (excluded if rec.is_noise else included).append(rec)
    status = "found" if (included or excluded) else "not_found"
    return {"status": status, "included": included, "excluded": excluded}


# ── per-intent handlers → ConstructionHarnessResult (evidence) ───────────────────────────

def _missing_scope_result(intent: str) -> ConstructionHarnessResult:
    it = EvidenceItem(EvidenceType.MISSING, "Не задан проект/датасет",
                      blockers=["укажите project_id или dataset_ids — без scope искать негде"], status="missing")
    return ConstructionHarnessResult(answer_data={"intent": intent},
                                     evidence_blocks=[block_of(EvidenceType.MISSING, "Нет scope", [it])],
                                     total_status="no_data")


def _handle_project_registry(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    if not dataset_ids:
        return _missing_scope_result("project_document_registry")
    reg = doc_registry(dataset_ids, storage_root=storage_root)
    if reg["status"] != "found":
        return _missing_scope_result("project_document_registry")
    incl = [EvidenceItem(EvidenceType.RETRIEVED, r.file_name, source_refs=[r.source_ref],
                         status="supported") for r in reg["included"]]
    excl = [EvidenceItem(EvidenceType.BLOCKED, r.file_name, blockers=r.noise_flags,
                         status="blocked") for r in reg["excluded"]]
    blocks = [block_of(EvidenceType.RETRIEVED, "Реестр документов (не мусорные)", incl)]
    if excl:
        blocks.append(block_of(EvidenceType.BLOCKED, "Исключено как мусор", excl))
    return ConstructionHarnessResult(
        answer_data={"intent": "project_document_registry", "included": len(incl), "excluded": len(excl)},
        evidence_blocks=blocks, sources=[r.source_ref for r in reg["included"]],
        total_status="complete" if incl else "blocked")


_PROJECT_KEYWORDS = ("котельн", "тепломехан", "газоснаб", "автоматик", "дымоудал", "электроснаб",
                     "аупт", "вентиляц", "отоплен", "водоснаб", "канализац", "паркинг", "офис")


def _handle_project_summary(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    if not dataset_ids:
        return _missing_scope_result("project_summary")
    reg = doc_registry(dataset_ids, storage_root=storage_root)
    docs = reg.get("included", [])
    if not docs:
        return _missing_scope_result("project_summary")
    names = " ".join(d.file_name.lower() for d in docs)
    found_kw = sorted({k for k in _PROJECT_KEYWORDS if k in names})
    # описание ТОЛЬКО из найденного (имена документов) — без выдумки назначения/мощности/адреса
    items = [EvidenceItem(EvidenceType.RETRIEVED, d.file_name, source_refs=[d.source_ref]) for d in docs[:20]]
    summary = (f"По найденным документам видно разделы: {', '.join(found_kw)}. " if found_kw else
               "По именам документов разделы не распознаны. ")
    summary += ("Это предположение по составу файлов — полного паспорта проекта (назначение/мощность/"
                "адрес/стадия) в источниках не подтверждено.")
    blocks = [block_of(EvidenceType.RETRIEVED, "Документы проекта (основа описания)", items)]
    miss = EvidenceItem(EvidenceType.MISSING, "Паспорт проекта",
                        blockers=["назначение/мощность/адрес/стадия не подтверждены источником"], status="missing")
    blocks.append(block_of(EvidenceType.MISSING, "Не хватает для полного описания", [miss]))
    return ConstructionHarnessResult(answer_data={"intent": "project_summary", "summary": summary,
                                                  "sections": found_kw},
                                     evidence_blocks=blocks, sources=[d.source_ref for d in docs],
                                     total_status="partial")


def _handle_mail(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    # read-only; v0.3 — почта не интегрирована в этот контур → честный MISSING (НЕ свободный ответ).
    it = EvidenceItem(EvidenceType.MISSING, "Почтовый источник",
                      blockers=["почта не подключена к unified-контуру или не найдена в scope"], status="missing")
    return ConstructionHarnessResult(answer_data={"intent": "mail_qa"},
                                     evidence_blocks=[block_of(EvidenceType.MISSING, "Почта", [it])],
                                     total_status="no_data",
                                     warnings=["mail_qa v0.3: read-only, без отправки; источник не подключён"])


def _handle_asbuilt(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    it = EvidenceItem(EvidenceType.MISSING, "Исполнительная/журналы",
                      blockers=["as-built источник не подключён к unified-контуру в v0.3"], status="missing")
    return ConstructionHarnessResult(answer_data={"intent": "asbuilt_extract"},
                                     evidence_blocks=[block_of(EvidenceType.MISSING, "Исполнительная", [it])],
                                     total_status="no_data")


def _handle_norm_qa(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    """Нормативный ответ ТОЛЬКО из источника (lexical/FTS). Нет источника → MISSING, не выдумка."""
    try:
        from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled
        from backend.rag_config import rag_collection_name
        if not lexical_enabled():
            raise RuntimeError("lexical off")
        idx = LexicalIndex()
        chunks = idx.search(question, collection=rag_collection_name(), dataset_ids=dataset_ids or None, limit=5)
    except Exception:
        chunks = []
    if not chunks:
        it = EvidenceItem(EvidenceType.MISSING, "Нормативный источник",
                          blockers=["в выбранных документах нормы по запросу не найдены"], status="missing")
        return ConstructionHarnessResult(answer_data={"intent": "norm_qa"},
                                         evidence_blocks=[block_of(EvidenceType.MISSING, "Нормы", [it])],
                                         total_status="no_data")
    items = []
    for c in chunks:
        meta = getattr(c, "meta", {}) or {}
        doc = str(meta.get("file_name") or getattr(c, "doc_name", "") or "источник")
        ref = doc + (f"#{meta.get('chunk_ord')}" if meta.get("chunk_ord") is not None else "")
        items.append(EvidenceItem(EvidenceType.RETRIEVED, (getattr(c, "content", "") or "")[:200],
                                  source_refs=[ref], status="supported"))
    return ConstructionHarnessResult(answer_data={"intent": "norm_qa"},
                                     evidence_blocks=[block_of(EvidenceType.RETRIEVED, "Найдено в нормах", items)],
                                     sources=[i.source_refs[0] for i in items], total_status="complete")


def _handle_table_agg(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    # тонкий: суммирует qty из найденной проектной таблицы (RETRIEVED строки → COMPUTED сумма).
    if not dataset_ids:
        return _missing_scope_result("table_agg")
    doc = retrieve_project_doc(question, dataset_ids=dataset_ids, storage_root=storage_root)
    rows = doc.get("rows", [])
    qtys = [(r, _num(r.get("qty"))) for r in rows if _num(r.get("qty")) is not None]
    if not qtys:
        it = EvidenceItem(EvidenceType.MISSING, "Табличные данные",
                          blockers=["таблица с количествами не найдена"], status="missing")
        return ConstructionHarnessResult(answer_data={"intent": "table_agg"},
                                         evidence_blocks=[block_of(EvidenceType.MISSING, "Таблица", [it])],
                                         total_status="no_data")
    total = round(sum(v for _, v in qtys), 3)
    retr = [EvidenceItem(EvidenceType.RETRIEVED, str(r.get("name", ""))[:50], value=v, unit=str(r.get("unit", "")),
                         source_refs=[str(r.get("source_file", "doc"))]) for r, v in qtys[:20]]
    comp = EvidenceItem(EvidenceType.COMPUTED, "Итого (сумма qty)", value=total,
                        formula=f"sum(qty) по {len(qtys)} строкам", inputs=[{"rows": len(qtys)}],
                        source_refs=doc.get("sources", []), status="computed")
    return ConstructionHarnessResult(
        answer_data={"intent": "table_agg", "total": total},
        evidence_blocks=[block_of(EvidenceType.RETRIEVED, "Строки таблицы", retr),
                         block_of(EvidenceType.COMPUTED, "Агрегация", [comp])],
        sources=doc.get("sources", []), total_status="complete")


def _handle_bor_extract(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    if not dataset_ids:
        return _missing_scope_result("bor_extract")
    doc = retrieve_project_doc(question, dataset_ids=dataset_ids, storage_root=storage_root)
    if doc["status"] != "found":
        it = EvidenceItem(EvidenceType.MISSING, "Ф9/ВОР/спецификация",
                          blockers=["проектный табличный документ не найден"], status="missing")
        return ConstructionHarnessResult(answer_data={"intent": "bor_extract"},
                                         evidence_blocks=[block_of(EvidenceType.MISSING, "Источник", [it])],
                                         total_status="no_data")
    bor = spec_to_bor(doc["rows"])
    items = [EvidenceItem(EvidenceType.RETRIEVED, p["work"], value=p.get("qty"), unit=p.get("unit", ""),
                          source_refs=p["source_refs"] or doc["sources"], status="supported")
             for p in bor["positions"] if p.get("qty") is not None]
    return ConstructionHarnessResult(answer_data={"intent": "bor_extract", "positions": len(bor["positions"])},
                                     evidence_blocks=[block_of(EvidenceType.RETRIEVED, "Извлечённая ВОР", items)],
                                     sources=doc["sources"], total_status="complete" if items else "blocked")


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


_HANDLERS = {
    "estimate_from_bor": lambda q, **kw: run_construction_harness(
        q, project_id=kw.get("project_id", 0), dataset_ids=kw.get("dataset_ids"),
        storage_root=kw.get("storage_root")),
    "bor_extract": _handle_bor_extract,
    "project_document_registry": _handle_project_registry,
    "project_summary": _handle_project_summary,
    "mail_qa": _handle_mail,
    "asbuilt_extract": _handle_asbuilt,
    "norm_qa": _handle_norm_qa,
    "document_qa": _handle_norm_qa,        # тот же lexical-источник
    "table_agg": _handle_table_agg,
}


def run_unified_construction_harness(question: str, *, project_id: int = 0,
                                     dataset_ids: list[str] | None = None,
                                     storage_root: Path | None = None) -> ConstructionHarnessResult | None:
    """Роутинг intent → handler → evidence. none/unsupported → None (старый путь решает)."""
    route = route_construction_intent(question)
    if route.intent not in _SUPPORTED_INTENTS:
        return None
    handler = _HANDLERS.get(route.intent)
    if handler is None:
        return None
    res = handler(question, project_id=project_id, dataset_ids=dataset_ids, storage_root=storage_root)
    if isinstance(res, ConstructionHarnessResult):
        res.answer_data.setdefault("route", {"intent": route.intent, "confidence": route.confidence,
                                             "matched_terms": route.matched_terms})
        res.tool_trace.insert(0, {"tool": "route_construction_intent", "intent": route.intent})
    return res


def maybe_unified_construction_harness(question: str, *, project_id: int = 0,
                                       dataset_ids: list[str] | None = None,
                                       storage_root: Path | None = None) -> ConstructionHarnessResult | None:
    """Feature-flagged вход для chat. OFF → None (chat не меняется)."""
    if not unified_enabled():
        return None
    return run_unified_construction_harness(question, project_id=project_id, dataset_ids=dataset_ids,
                                            storage_root=storage_root)


# ── composer: human-readable из evidence (без фактов/чисел вне evidence) ─────────────────

_BLOCK_ORDER = [EvidenceType.RETRIEVED, EvidenceType.COMPUTED, EvidenceType.ASSUMED,
                EvidenceType.MISSING, EvidenceType.BLOCKED]
_BLOCK_HUMAN = {EvidenceType.RETRIEVED: "📑 Найдено в источниках", EvidenceType.COMPUTED: "🧮 Рассчитано",
                EvidenceType.ASSUMED: "≈ Приняты допущения", EvidenceType.MISSING: "❓ Не хватает данных",
                EvidenceType.BLOCKED: "⛔ Отклонено / не принято"}


def compose_unified_answer(result: ConstructionHarnessResult) -> str:
    """Markdown строго из evidence-блоков. Числа/факты — только из items, не из головы."""
    ad = result.answer_data or {}
    lines: list[str] = []
    if ad.get("summary"):
        lines += [ad["summary"], ""]
    by_type = {b.type: b for b in result.evidence_blocks}
    for et in _BLOCK_ORDER:
        b = by_type.get(et)
        if not b or not b.items:
            continue
        lines.append(f"**{_BLOCK_HUMAN[et]}:**")
        for it in b.items[:25]:
            num = f" — {it.value} {it.unit}".rstrip() if it.value is not None else ""
            src = f"  _[{', '.join(it.source_refs[:2])}]_" if it.source_refs else ""
            blk = f" ({'; '.join(it.blockers)})" if it.blockers else ""
            asm = f" ({'; '.join(it.assumptions)})" if it.assumptions else ""
            lines.append(f"- {it.title}{num}{blk}{asm}{src}")
        lines.append("")
    # итог сметы — только при complete; иначе partial как диагностика
    if result.total_status == "complete" and result.final_total is not None:
        lines.append(f"**ИТОГО: {result.final_total} ₽** (рассчитано, без блокеров)")
    elif result.partial_total is not None:
        lines.append(f"_Диагностическая сумма по рассчитанным позициям: ~{result.partial_total} ₽ — НЕ итоговая "
                     f"смета (есть блокеры/нехватка данных)._")
    return "\n".join(lines).strip() or "По запросу evidence не собрано."
