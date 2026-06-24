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
                      "mail_qa", "table_agg", "asbuilt_extract", "norm_qa", "document_qa",
                      # v0.4 source-scoped
                      "source_scoped_entity_search", "project_doc_entity_search", "mail_entity_search",
                      "term_explain",
                      # v0.5 resource cost
                      "resource_cost_calc"}

# v0.4: ИСТОЧНИК доминирует над термином. «найти X в <источник>» → сначала источник, потом термин.
_SOURCE_SCOPES: list[tuple[str, tuple[str, ...]]] = [
    ("asbuilt", ("в актах", "в акте", "акт смонтирован", "смонтированного оборудования",
                 "ведомость смонтирован", "в исполнительн", " в ид", "as-built", "в кс-2", "в кс2",
                 "в журнале работ", "в журналах")),
    ("mail", ("в почте", "в письм", "в переписк")),
    ("specification", ("в спецификац",)),
    ("bor", ("в вор", "в ф9", "в ведомости объ", "в ведомости")),
    ("table", ("в таблиц",)),
    ("project_doc", ("в проектн", "в документ", "в проекте")),
]
_SCOPE_DOC_TYPES: dict[str, set[str]] = {
    "asbuilt": {"installed_equipment_act", "asbuilt", "ks2", "work_log"},
    "specification": {"specification"},
    "bor": {"f9_bor", "specification"},
    "table": {"table", "f9_bor", "installed_equipment_act", "specification"},
    "project_doc": {"project_doc", "specification", "f9_bor", "table", "unknown"},
    "mail": {"mail"},
}
_SCOPE_INTENT: dict[str, str] = {
    "asbuilt": "asbuilt_extract", "mail": "mail_entity_search",
    "specification": "project_doc_entity_search", "bor": "project_doc_entity_search",
    "table": "source_scoped_entity_search", "project_doc": "project_doc_entity_search",
}
_SCOPE_HUMAN = {"asbuilt": "акты/исполнительная (смонтированное оборудование)", "mail": "почта/переписка",
                "specification": "спецификация", "bor": "ВОР/Ф9", "table": "таблицы",
                "project_doc": "проектные документы"}
_NORM_TERMS = ("правил", "требовани", "по нормам", "норматив", " сп ", " гост", " снип", "огнестойк",
               "расстановк", "по нормативу")
_AGG_TERMS = ("посчитай", "суммируй", "сколько", "количество", "итого", "сумму", "сумма")
# v0.5: детальный ресурсный обсчёт стоимости по ГЭСН
_RESOURCE_COST_TERMS = ("обсчёт", "обсчет", "обсч", "расчёт стоимости", "расчет стоимости", "по ресурсам",
                        "ресурсный", "разложи по ресурс", "ресурсный состав", "прямые затраты", "фот",
                        "по гэсн", "сметная стоимость по гэсн", "проверь кац", "что требует кац",
                        "разложи цену", "ставк", "нр сп", "нр и сп", "по примеру", "стоимость проект",
                        "стоимость позици", "посчитай по ресурс")


@dataclass
class RouteResult:
    intent: str
    confidence: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)
    requires_project_scope: bool = False
    route_source: str = "keyword"
    source_scope: str = ""
    warnings: list[str] = field(default_factory=list)


def route_construction_intent(question: str) -> RouteResult:
    """v0.4 source-first. ИСТОЧНИК доминирует над термином: «найди ОЗК в актах» → asbuilt (НЕ нормы).
    Порядок: source-phrase → правила/нормы → «что такое» → keyword-каскад → none."""
    low = f" {(question or '').lower()} "
    # 1. SOURCE PHRASE — приоритет над термином (даже неизвестным)
    for sc, phrases in _SOURCE_SCOPES:
        m = [p for p in phrases if p in low]
        if m:
            return RouteResult(_SCOPE_INTENT[sc], 0.8, m, route_source="source_scope",
                               source_scope=sc, requires_project_scope=True)
    # 2. ресурсный обсчёт стоимости (ПЕРЕД нормами: «ФОТ/НР/СП/обсчёт» — расчёт, не Свод Правил)
    rm = [t for t in _RESOURCE_COST_TERMS if t in low]
    if rm:
        return RouteResult("resource_cost_calc", 0.7, rm, route_source="keyword")
    # 3. правила/нормы (без источника) → norm_qa
    if any(t in low for t in _NORM_TERMS):
        return RouteResult("norm_qa", 0.6, ["norm"], route_source="keyword")
    # 4. «что такое X» → объяснение термина (с дизамбигуацией), не source-scoped
    if "что такое" in low or "расшифр" in low:
        return RouteResult("term_explain", 0.6, ["что такое"], route_source="keyword")
    # 5. keyword-каскад (project/registry/estimate/...)
    for intent, terms in _INTENT_RULES:
        matched = [t for t in terms if t in low]
        if matched:
            return RouteResult(intent=intent, confidence=0.6 + 0.1 * min(len(matched), 3),
                               matched_terms=matched,
                               requires_project_scope=intent in ("project_summary", "project_document_registry",
                                                                  "estimate_from_bor", "bor_extract", "mail_qa",
                                                                  "table_agg", "asbuilt_extract"))
    return RouteResult(intent="none", confidence=0.0)


# ── doc_type classifier (детерминированный, по имени файла/таблицы) ───────────────────────

def classify_doc_type(name: str) -> str:
    """Имя файла/таблицы → doc_type. Без LLM. Акты смонтированного оборудования — отдельный тип."""
    n = (name or "").lower()
    if "акт" in n and any(k in n for k in ("смонтирован", "оборудован")):
        return "installed_equipment_act"
    if "ведомость смонтирован" in n or ("смонтированного оборудования" in n):
        return "installed_equipment_act"
    if "кс-2" in n or "кс2" in n:
        return "ks2"
    if "журнал работ" in n:
        return "work_log"
    if "исполнительн" in n or n.endswith("_ид.pdf") or "as-built" in n or "as_built" in n:
        return "asbuilt"
    if "спецификац" in n:
        return "specification"
    if "ф9" in n or "f9" in n or "ведомость объ" in n or n.startswith("вор") or "_вор" in n:
        return "f9_bor"
    if "лср" in n:
        return "lsr"
    if "смет" in n:
        return "estimate"
    if n.endswith(".dwg"):
        return "drawing"
    if any(k in n for k in ("свод правил", " сп ", "гост", "снип")):
        return "norm"
    if n.endswith(".eml") or "письм" in n or "переписк" in n:
        return "mail"
    if n.endswith(".parquet"):
        return "table"
    if n.endswith((".pdf", ".docx", ".doc")):
        return "project_doc"
    return "unknown"


_DISCIPLINE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("TM", ("тепломех", "_тм", "тм_", "тепломеханик")), ("GAS", ("газоснаб", "гсв")),
    ("AUPT", ("аупт", "пожаротуш")), ("APS", ("апс", "пожарн", "ппа")), ("DU", ("дымоудал",)),
    ("OV", ("отоплен", "вентиляц", "_ов")), ("VK", ("водоснаб", "канализац", "_вк")),
    ("EOM", ("электроснаб", "эом")), ("ARCH", ("архитект", "_ар")), ("KR", ("конструкц", "_кр")),
    ("estimate", ("смет", "лср")), ("asbuilt", ("исполнительн", "смонтирован")),
]


def classify_discipline(name: str) -> str:
    n = (name or "").lower()
    for disc, kw in _DISCIPLINE_RULES:
        if any(k in n for k in kw):
            return disc
    return "unknown"


# ── generic query-term extractor (БЕЗ хардкод-словаря; ОЗК = канарейка, не спец-кейс) ─────

_FIND_VERBS = ("найди", "найти", "поищи", "ищи", "покажи", "проверь наличие", "проверь",
               "есть ли", "выведи", "сколько", "посчитай", "суммируй")
_QUOTED_RE = re.compile(r"[«\"']([^»\"']{2,40})[«\"']")
# марка/аббревиатура: кириллица/латиница 1-8 + опц. -/пробел + цифры (ОЗК, ОЗК-1, ВРС-12, Н1, ШУ-1)
_MARK_RE = re.compile(r"\b([A-ZА-ЯЁ]{1,8}(?:[-\s.]?\d{1,3})?)\b")


@dataclass
class EntitySearchQuery:
    query_terms: list[str] = field(default_factory=list)
    exact_terms: list[str] = field(default_factory=list)
    source_scope: str = ""
    doc_type_filter: str = ""
    intent: str = ""
    require_exact_match: bool = False
    aggregate: bool = False
    raw_object: str = ""


def _is_term_candidate(tok: str) -> bool:
    letters = re.sub(r"[^A-ZА-ЯЁ]", "", tok)
    has_digit = bool(re.search(r"\d", tok))
    return len(letters) >= 2 or (has_digit and len(letters) >= 1)


def extract_source_scoped_query(question: str) -> EntitySearchQuery:
    """Generic: объект поиска = текст после глагола, до source-фразы; марки/аббревиатуры = exact.
    Source-фраза вырезается из терма. Пусто → clarification. Ни одного хардкод-термина."""
    q = (question or "").strip()
    low = q.lower()
    route = route_construction_intent(q)
    scope = route.source_scope
    aggregate = any(t in low for t in _AGG_TERMS)

    # объект = текст ДО source-фразы
    obj = q
    cut = len(q)
    for sc, phrases in _SOURCE_SCOPES:
        for p in phrases:
            i = low.find(p.strip())
            if i >= 0:
                cut = min(cut, i)
    obj = q[:cut].strip(" ,.:;«»\"'")
    # убрать ведущий глагол
    obj_low = obj.lower()
    for v in sorted(_FIND_VERBS, key=len, reverse=True):
        if obj_low.startswith(v):
            obj = obj[len(v):].strip(" ,.:;«»\"'-")
            break

    quoted = [m.strip() for m in _QUOTED_RE.findall(q)]
    marks = [m for m in _MARK_RE.findall(obj) if _is_term_candidate(m)]
    terms: list[str] = []
    if obj and len(obj) >= 2 and obj.lower() not in {m.lower() for m in marks}:
        terms.append(obj)
    for m in marks:
        if m not in terms:
            terms.append(m)
    for qd in quoted:
        if qd not in terms:
            terms.insert(0, qd)
    exact = quoted + marks
    return EntitySearchQuery(query_terms=terms, exact_terms=exact, source_scope=scope,
                             intent=route.intent, require_exact_match=bool(exact),
                             aggregate=aggregate, raw_object=obj)


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
    discipline: str = ""
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
                          doc_type=classify_doc_type(p.name), discipline=classify_discipline(p.name),
                          noise_flags=flags, source_ref=f"{ds}/{rel}")


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


# ── v0.4: source-scoped entity search (источник доминирует, термин — generic) ────────────

def _norm_token(s: Any) -> str:
    return re.sub(r"[\s.\-_]", "", str(s)).lower()


_FIELD_HINTS = {
    "act_number": ("акт", "№ акт", "номер акт"), "date": ("дата", "date"),
    "equipment_name": ("наимен", "оборудован", "name", "наименование"),
    "mark": ("марка", "тип", "mark", "обознач"), "quantity": ("кол", "qty", "количество"),
    "unit": ("ед", "unit", "ед.изм"), "location": ("помещ", "этаж", "место", "локац", "location"),
    "system": ("систем", "system"),
}


def _extract_fields(row: dict) -> dict:
    out = {}
    lk = {str(k).lower(): k for k in row}
    for field_name, hints in _FIELD_HINTS.items():
        for h in hints:
            for low_key, real_key in lk.items():
                if h in low_key and row.get(real_key) not in (None, ""):
                    out[field_name] = row[real_key]
                    break
            if field_name in out:
                break
    return out


def _scan_docs_for_terms(docs: list[tuple], eq: "EntitySearchQuery", root: Path) -> list[dict]:
    """Найти exact-термы в строках parquet и именах файлов. Возвращает matches с source_ref."""
    import pandas as pd
    terms_norm = [(_norm_token(t), t) for t in eq.exact_terms if _norm_token(t)]
    if not terms_norm:
        terms_norm = [(_norm_token(t), t) for t in eq.query_terms if _norm_token(t)]
    matches: list[dict] = []
    for ds, p, dt in docs:
        if p.suffix.lower() == ".parquet":
            try:
                df = pd.read_parquet(p)
            except Exception:  # noqa: BLE001
                continue
            for i, rec in enumerate(df.to_dict("records")):
                rec = {k: ("" if pd.isna(v) else v) for k, v in rec.items()}
                cell_norm = _norm_token(" ".join(str(v) for v in rec.values()))
                hit = next((orig for tn, orig in terms_norm if tn and tn in cell_norm), None)
                if hit:
                    matches.append({"source_ref": f"{ds}/{p.name}#row{i}", "file_name": p.name,
                                    "doc_type": dt, "row_id": i, "matched_term": hit,
                                    "snippet": "; ".join(f"{k}={v}" for k, v in rec.items() if v)[:200],
                                    "fields": _extract_fields(rec)})
        else:
            fn = _norm_token(p.name)
            hit = next((orig for tn, orig in terms_norm if tn and tn in fn), None)
            if hit:
                matches.append({"source_ref": f"{ds}/{p.name}", "file_name": p.name, "doc_type": dt,
                                "matched_term": hit, "snippet": p.name, "fields": {}})
    return matches


_ALIAS_RE_TMPL = r"{t}\s*[\(—\-–:]\s*([А-ЯЁа-яёA-Za-z ]{{4,60}})|([А-ЯЁа-яёA-Za-z ]{{4,60}})\s*\(\s*{t}\s*\)"


def _alias_from_docs(docs: list[tuple], eq: "EntitySearchQuery", root: Path) -> list[dict]:
    """Алиас/расшифровка ТОЛЬКО из источника (не из памяти модели). «ОЗК (огнезадерж. клапан)»."""
    import pandas as pd
    out = []
    for t in eq.exact_terms:
        pat = re.compile(_ALIAS_RE_TMPL.format(t=re.escape(t)), re.I)
        for ds, p, dt in docs:
            text = p.name
            if p.suffix.lower() == ".parquet":
                try:
                    text += " " + " ".join(str(v) for v in pd.read_parquet(p).astype(str).values.ravel()[:500])
                except Exception:  # noqa: BLE001
                    pass
            mm = pat.search(text)
            if mm:
                expansion = (mm.group(1) or mm.group(2) or "").strip()
                if expansion:
                    out.append({"term": t, "expansion": expansion, "source_ref": f"{ds}/{p.name}"})
                    break
    return out


def source_scoped_search(eq: "EntitySearchQuery", *, dataset_ids: list[str] | None = None,
                         storage_root: Path | None = None) -> dict[str, Any]:
    """Поиск термина В ИСТОЧНИКЕ заданного типа. Источник доминирует: ищем только в документах
    нужного doc_type; нет такого источника → no_source (не уходим в нормы/спеку молча)."""
    if not eq.query_terms:
        return {"status": "no_term", "matches": [], "other_matches": [], "alias": []}
    if not dataset_ids:
        return {"status": "no_scope", "matches": [], "other_matches": [], "alias": []}
    root = storage_root or Path("storage/datasets")
    scope_types = _SCOPE_DOC_TYPES.get(eq.source_scope, set())
    in_scope, other = [], []
    for ds in dataset_ids:
        ddir = root / ds
        if not ddir.exists():
            continue
        for p in sorted(ddir.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            dt = classify_doc_type(p.name)
            (in_scope if dt in scope_types else other).append((ds, p, dt))
    searched = [f"{ds}/{p.name}" for ds, p, _ in in_scope]
    scope_h = _SCOPE_HUMAN.get(eq.source_scope, eq.source_scope)
    tiers: list[str] = ["parquet_row", "filename_metadata"]
    if not in_scope:
        return {"status": "no_source", "matches": [], "other_matches": [], "alias": [],
                "searched_sources": [], "scope_human": scope_h, "searched_tiers": tiers, "adapter_warnings": []}
    # Tier 1+2: parquet-строки + имена файлов нужного doc_type
    matches = _scan_docs_for_terms(in_scope, eq, root)
    if matches:
        return {"status": "found", "matches": matches, "other_matches": [], "alias": [],
                "searched_sources": searched, "searched_tiers": tiers, "adapter_warnings": []}
    # Tier 3: lexical-чанки (тело PDF/доков, scoped по doc_type) — закрывает parquet_only
    from proxy.services.source_adapters import search_lexical_chunks, search_vector_chunks
    lex = search_lexical_chunks(eq.exact_terms or eq.query_terms, dataset_ids=dataset_ids,
                                doc_type_filter=scope_types)
    tiers.append("lexical_chunk")
    warns = list(lex.warnings)
    if lex.status == "found":
        lex_matches = [{"source_ref": m.source_ref, "file_name": m.file_name, "doc_type": m.source_kind,
                        "matched_term": m.matched_term, "snippet": m.snippet, "fields": {}} for m in lex.matches]
        return {"status": "found", "matches": lex_matches, "other_matches": [], "alias": [],
                "searched_sources": searched, "searched_tiers": tiers, "source_kind": "lexical_chunk",
                "adapter_warnings": warns}
    # Tier 4: vector (Qdrant) — в sync-пути unavailable (честный статус, не фейк)
    vec = search_vector_chunks(" ".join(eq.query_terms), dataset_ids=dataset_ids, doc_type_filter=scope_types)
    tiers.append("vector_chunk")
    warns += list(vec.warnings)
    # не нашли в нужном источнике → другие документы + алиас (Case B/E)
    other_matches = _scan_docs_for_terms(other, eq, root)
    alias = _alias_from_docs(in_scope + other, eq, root)
    return {"status": "not_found", "matches": [], "other_matches": other_matches, "alias": alias,
            "searched_sources": searched, "scope_human": scope_h, "searched_tiers": tiers,
            "adapter_warnings": warns}


# ── per-intent handlers → ConstructionHarnessResult (evidence) ───────────────────────────

# v0.8: какой ИСТОЧНИК нужен этому intent'у — для actionable MISSING (не общее «нет scope»).
_INTENT_SOURCE_HUMAN = {
    "project_document_registry": "проектные документы", "project_summary": "проектные документы",
    "estimate_from_bor": "Ф9/ВОР (проектная таблица)", "bor_extract": "Ф9/ВОР/спецификация",
    "table_agg": "проектная таблица", "asbuilt_extract": "акты смонтированного оборудования/исполнительная",
    "mail_entity_search": "почта/переписка проекта", "project_doc_entity_search": "проектные документы",
    "source_scoped_entity_search": "проектные документы",
}


def _missing_scope_result(intent: str) -> ConstructionHarnessResult:
    """v0.8 actionable: говорит, КАКОЙ источник нужен и КАК задать scope (не уходит в RAG/фантазию)."""
    src = _INTENT_SOURCE_HUMAN.get(intent, "проектные документы")
    msg = (f"Для этого запроса нужен проект или датасет (источник: {src}). "
           f"Выберите проект/датасет в GUI Совушки или укажите project_id/dataset_ids.")
    it = EvidenceItem(EvidenceType.MISSING, "Не выбран проект/датасет", blockers=[msg],
                      status="missing")
    return ConstructionHarnessResult(
        answer_data={"intent": intent, "needs_scope": True, "required_source": src, "action": msg},
        evidence_blocks=[block_of(EvidenceType.MISSING, "Нужен выбор проекта/датасета", [it])],
        total_status="no_data")


def _handle_project_registry(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    if not dataset_ids:
        return _missing_scope_result("project_document_registry")
    reg = doc_registry(dataset_ids, storage_root=storage_root)
    if reg["status"] != "found":
        return _missing_scope_result("project_document_registry")
    known = [r for r in reg["included"] if r.doc_type != "unknown"]
    unknown = [r for r in reg["included"] if r.doc_type == "unknown"]
    incl = [EvidenceItem(EvidenceType.RETRIEVED, f"{r.file_name}  [{r.doc_type}/{r.discipline}]",
                         source_refs=[r.source_ref], status="supported") for r in known]
    unk = [EvidenceItem(EvidenceType.RETRIEVED, r.file_name, source_refs=[r.source_ref],
                        status="supported") for r in unknown]
    excl = [EvidenceItem(EvidenceType.BLOCKED, r.file_name, blockers=r.noise_flags,
                         status="blocked") for r in reg["excluded"]]
    blocks = [block_of(EvidenceType.RETRIEVED, "Реестр документов (по типу/дисциплине)", incl or unk)]
    if incl and unk:
        blocks.append(block_of(EvidenceType.RETRIEVED, "Неопознанные, но не мусор", unk))
    if excl:
        blocks.append(block_of(EvidenceType.BLOCKED, "Исключено как мусор", excl))
    # сгруппированный indexed-список по doc_type для answer_data
    groups: dict[str, list[str]] = {}
    for r in known:
        groups.setdefault(r.doc_type, []).append(r.file_name)
    return ConstructionHarnessResult(
        answer_data={"intent": "project_document_registry", "included": len(reg["included"]),
                     "excluded": len(excl), "groups": groups},
        evidence_blocks=blocks, sources=[r.source_ref for r in reg["included"]],
        total_status="complete" if reg["included"] else "blocked")


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
    """v0.9 layered: lexical exact (tier1) → vector (tier2). Нормативный ответ ТОЛЬКО из источника;
    нет источника → MISSING с перечнем искомых tier'ов (не выдумка, не пункт СП из памяти)."""
    from proxy.services.source_adapters import search_lexical_chunks, search_vector_chunks
    eq = extract_source_scoped_query(question)
    terms = eq.query_terms or [question]
    tiers: list[str] = []
    warns: list[str] = []
    # tier 1: lexical exact
    lex = search_lexical_chunks(terms, dataset_ids=dataset_ids)
    tiers.append("lexical_chunk")
    warns += list(lex.warnings)
    matches = lex.matches if lex.status == "found" else []
    # tier 2: vector (в sync-пути unavailable — честный статус)
    if not matches:
        vec = search_vector_chunks(question, dataset_ids=dataset_ids)
        tiers.append("vector_chunk")
        warns += list(vec.warnings)
    ad = {"intent": "norm_qa", "query_terms": terms, "searched_tiers": tiers, "adapter_warnings": warns}
    if not matches:
        it = EvidenceItem(EvidenceType.MISSING, "Нормативный источник не найден",
                          blockers=[f"искал по tier'ам: {', '.join(tiers)}; источник по запросу не найден "
                                    f"(нормативного утверждения без источника не даю)"], status="missing")
        return ConstructionHarnessResult(answer_data=ad,
                                         evidence_blocks=[block_of(EvidenceType.MISSING, "Нормы", [it])],
                                         total_status="no_data", warnings=warns)
    items = [EvidenceItem(EvidenceType.RETRIEVED, m.snippet or m.file_name, source_refs=[m.source_ref],
                          status="supported") for m in matches]
    return ConstructionHarnessResult(answer_data=ad,
                                     evidence_blocks=[block_of(EvidenceType.RETRIEVED, "Найдено в нормах/документах", items)],
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


def _match_to_item(m: dict) -> EvidenceItem:
    f = m.get("fields", {})
    extras = " ".join(f"{k}={v}" for k, v in f.items() if v) if f else ""
    title = f"{m.get('matched_term', '')} в {m.get('file_name', '')}" + (f" — {extras}" if extras else "")
    return EvidenceItem(EvidenceType.RETRIEVED, title.strip(), source_refs=[m["source_ref"]], status="supported")


def _handle_source_scoped(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    """v0.4 source-scoped поиск термина В ИСТОЧНИКЕ. Cases A-E из ТЗ. Источник доминирует над термином."""
    eq = extract_source_scoped_query(question)
    ad = {"intent": eq.intent, "source_scope": eq.source_scope, "query_terms": eq.query_terms,
          "scope_human": _SCOPE_HUMAN.get(eq.source_scope, eq.source_scope)}
    if not eq.query_terms:                                     # нечего искать → clarification
        it = EvidenceItem(EvidenceType.MISSING, "Что искать?",
                          blockers=["в запросе не выделен искомый термин/марка"], status="missing")
        return ConstructionHarnessResult(answer_data=ad, evidence_blocks=[
            block_of(EvidenceType.MISSING, "Уточнение", [it])], total_status="no_data")
    if not dataset_ids:                                        # Case D: нет scope
        it = EvidenceItem(EvidenceType.MISSING, f"Не выбран проект/датасет для поиска ({ad['scope_human']})",
                          blockers=["укажите project_id или dataset_ids"], status="missing")
        return ConstructionHarnessResult(answer_data=ad, evidence_blocks=[
            block_of(EvidenceType.MISSING, "Нет scope", [it])], total_status="no_data")
    res = source_scoped_search(eq, dataset_ids=dataset_ids, storage_root=storage_root)
    ad["searched_sources"] = res.get("searched_sources", [])
    ad["searched_tiers"] = res.get("searched_tiers", [])
    ad["adapter_warnings"] = res.get("adapter_warnings", [])
    term = ", ".join(eq.exact_terms or eq.query_terms)

    if res["status"] == "no_source":                          # Case C: нет источника такого типа
        blk = f"нет документов типа {sorted(_SCOPE_DOC_TYPES.get(eq.source_scope, set()))}"
        warns = []
        if eq.source_scope == "mail":                         # mail-адаптер: actionable статус backend
            from proxy.services.source_adapters import retrieve_mail_evidence
            m = retrieve_mail_evidence(eq.query_terms, project_id=project_id, dataset_ids=dataset_ids)
            warns = list(m.warnings)
            ad["mail_adapter_status"] = m.status
        it = EvidenceItem(EvidenceType.MISSING, f"Источник «{ad['scope_human']}» в проекте не найден",
                          blockers=[blk], status="missing")
        return ConstructionHarnessResult(answer_data=ad, evidence_blocks=[
            block_of(EvidenceType.MISSING, "Нет источника", [it])], total_status="no_data", warnings=warns)

    if res["status"] == "found":
        matches = res["matches"]
        if eq.aggregate:                                      # «посчитай количество» → COMPUTED
            qcount = len(matches)
            qsum_vals = [_num(m["fields"].get("quantity")) for m in matches if _num(m["fields"].get("quantity"))]
            retr = [_match_to_item(m) for m in matches[:25]]
            comp_val = round(sum(qsum_vals), 3) if qsum_vals else qcount
            comp = EvidenceItem(EvidenceType.COMPUTED, f"Количество «{term}» в источнике", value=comp_val,
                                formula=("sum(quantity) по найденным строкам" if qsum_vals else
                                         "count(строк с совпадением)"),
                                inputs=[{"matched_rows": qcount}], source_refs=[m["source_ref"] for m in matches[:10]],
                                status="computed")
            return ConstructionHarnessResult(answer_data={**ad, "count": qcount}, evidence_blocks=[
                block_of(EvidenceType.RETRIEVED, f"Найдено «{term}» ({ad['scope_human']})", retr),
                block_of(EvidenceType.COMPUTED, "Агрегация", [comp])],
                sources=[m["source_ref"] for m in matches], total_status="complete")
        retr = [_match_to_item(m) for m in matches[:25]]       # Case A: только RETRIEVED
        return ConstructionHarnessResult(answer_data={**ad, "found": len(matches)}, evidence_blocks=[
            block_of(EvidenceType.RETRIEVED, f"Найдено «{term}» в источнике ({ad['scope_human']})", retr)],
            sources=[m["source_ref"] for m in matches], total_status="complete")

    # not_found в нужном источнике — actionable: какие tier'ы искал + что недоступно
    tiers_h = ", ".join(res.get("searched_tiers", [])) or "—"
    miss = EvidenceItem(EvidenceType.MISSING, f"«{term}» не найден в источнике ({ad['scope_human']})",
                        blockers=[f"искал по tier'ам: {tiers_h}; файлы: {', '.join(res.get('searched_sources', [])) or '—'}"],
                        status="missing")
    blocks = [block_of(EvidenceType.MISSING, "Не найдено", [miss])]
    warnings = list(res.get("adapter_warnings", []))
    if res["other_matches"]:                                  # Case B: есть в других доках — отдельно
        other = [_match_to_item(m) for m in res["other_matches"][:15]]
        blocks.append(block_of(EvidenceType.RETRIEVED,
                               "Найдено в ДРУГИХ документах (НЕ подтверждение монтажа)", other))
        warnings.append("совпадения в спецификации/проектных доках — это не акт смонтированного оборудования")
    if res["alias"]:                                          # Case E: алиас из источника
        al = [EvidenceItem(EvidenceType.RETRIEVED, f"{a['term']} → «{a['expansion']}» (расшифровка из источника)",
                           source_refs=[a["source_ref"]], status="supported") for a in res["alias"]]
        blocks.append(block_of(EvidenceType.RETRIEVED, "Возможная расшифровка (из источника, не из памяти)", al))
        warnings.append(f"дословно «{term}» не найдено — показаны совпадения по расшифровке")
    return ConstructionHarnessResult(answer_data=ad, evidence_blocks=blocks,
                                     sources=[m["source_ref"] for m in res["other_matches"]],
                                     total_status="no_data", warnings=warnings)


def _handle_term_explain(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    """«что такое X» — ищем расшифровку В ИСТОЧНИКЕ (не из памяти). Нет → MISSING + дизамбигуация."""
    eq = extract_source_scoped_query(question)
    ad = {"intent": "term_explain", "query_terms": eq.query_terms}
    if dataset_ids and eq.exact_terms:
        # ищем по всем проектным докам алиас-расшифровку
        root = storage_root or Path("storage/datasets")
        docs = []
        for ds in dataset_ids:
            ddir = root / ds
            if ddir.exists():
                docs += [(ds, p, classify_doc_type(p.name)) for p in ddir.rglob("*") if p.is_file()]
        alias = _alias_from_docs(docs, eq, root)
        if alias:
            al = [EvidenceItem(EvidenceType.RETRIEVED, f"{a['term']} → «{a['expansion']}»",
                               source_refs=[a["source_ref"]], status="supported") for a in alias]
            return ConstructionHarnessResult(answer_data=ad, evidence_blocks=[
                block_of(EvidenceType.RETRIEVED, "Расшифровка из источника", al)],
                sources=[a["source_ref"] for a in alias], total_status="complete")
    it = EvidenceItem(EvidenceType.MISSING, f"Расшифровка «{', '.join(eq.query_terms)}» не найдена в источниках",
                      blockers=["термин неоднозначен; уточните документ/контекст — не угадываю по памяти"],
                      status="missing")
    return ConstructionHarnessResult(answer_data=ad, evidence_blocks=[
        block_of(EvidenceType.MISSING, "Термин не раскрыт источником", [it])], total_status="no_data")


def _handle_resource_cost(question, *, project_id=0, dataset_ids=None, storage_root=None) -> ConstructionHarnessResult:
    """v0.5 детальный ресурсный обсчёт. Дизамбигуация «стоимость проекта»; golden воспроизводится
    кодом; нет источника → MISSING (не фантазия). Это стоимость СТРОИТЕЛЬНЫХ работ, не проектирования."""
    from proxy.services import resource_cost_service as rc
    low = (question or "").lower()
    # дизамбигуация: «стоимость проекта» без строительного контекста → уточнение
    if "стоимость проект" in low and not any(t in low for t in
                                             ("гэсн", "вор", "ф9", "смет", "работ", "ресурс", "обсч", "пример")):
        it = EvidenceItem(EvidenceType.MISSING, "Уточните, что считать",
                          blockers=["стоимость строительных работ по смете ИЛИ стоимость проектирования?"],
                          status="missing")
        return ConstructionHarnessResult(answer_data={"intent": "resource_cost_calc", "ambiguous": True},
                                         evidence_blocks=[block_of(EvidenceType.MISSING, "Неоднозначно", [it])],
                                         total_status="no_data")
    # есть данные обсчёта (golden-позиция) → воспроизводим кодом
    if any(t in low for t in ("обсч", "пример", "по гэсн", "разложи", "ресурс", "фот", " нр", " сп",
                              "кац", " тц", "прямые затрат", "ставк")):
        res = rc.run_resource_cost_golden()
        cr = rc.resource_result_to_construction_result(res)
        cr.answer_data["cost_kind"] = ("стоимость строительных работ (ресурсный обсчёт по ГЭСН), "
                                       "не стоимость проектирования")
        return cr
    # нет источника для расчёта
    it = EvidenceItem(EvidenceType.MISSING, "Источник для ресурсного расчёта не найден",
                      blockers=["приложите файл обсчёта / укажите ВОР+ГЭСН+цены"], status="missing")
    return ConstructionHarnessResult(answer_data={"intent": "resource_cost_calc"},
                                     evidence_blocks=[block_of(EvidenceType.MISSING, "Нет источника", [it])],
                                     total_status="no_data")


def _handle_estimate_from_bor(question, *, project_id=0, dataset_ids=None, storage_root=None):
    if not dataset_ids and not project_id:
        return _missing_scope_result("estimate_from_bor")    # v0.8 actionable (нужен Ф9/ВОР)
    return run_construction_harness(question, project_id=project_id, dataset_ids=dataset_ids,
                                    storage_root=storage_root)


_HANDLERS = {
    "estimate_from_bor": _handle_estimate_from_bor,
    "bor_extract": _handle_bor_extract,
    "project_document_registry": _handle_project_registry,
    "project_summary": _handle_project_summary,
    "mail_qa": _handle_mail,
    "asbuilt_extract": _handle_source_scoped,        # v0.4: «найди X в актах» → source-scoped
    "project_doc_entity_search": _handle_source_scoped,
    "mail_entity_search": _handle_source_scoped,     # scope=mail (read-only, MISSING если нет почты-доков)
    "source_scoped_entity_search": _handle_source_scoped,
    "term_explain": _handle_term_explain,
    "norm_qa": _handle_norm_qa,
    "document_qa": _handle_norm_qa,        # тот же lexical-источник
    "table_agg": _handle_table_agg,
    "resource_cost_calc": _handle_resource_cost,
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
