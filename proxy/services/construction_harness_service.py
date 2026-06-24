"""Construction EVIDENCE Harness v0.1 — evidence-driven контур поверх существующих сервисов.

ВАЖНО (честный статус, Codex): это Construction EVIDENCE Harness, ещё НЕ полноценный RAG Harness —
`retrieve_project_doc` пока FIXTURE/STUB (источник подаётся, не добывается). Контур и контракт
доказаны; настоящий RAG-добытчик проектных источников — v0.2.

НЕ публичный режим, НЕ рефакторинг, НЕ замена smeta/review/rag/free. Тонкий слой:
  вопрос → retrieve_project_doc(facade) → spec_to_bor → gesn_expand → lsr_assemble → evidence-контракт.

project-doc facade даёт источник/fixture; typed-фасады извлекают/считают; gates (Gate 1-4
переиспользуются, НЕ ослабляются) маркируют; число НИКОГДА не из текста LLM — только из tool-
результатов. Ответ: RETRIEVED / COMPUTED / ASSUMED / MISSING / BLOCKED.

SAFETY: неопределённая work_family НЕ даёт COMPUTED (gesn_expand → needs_classification → BLOCKED).

ЧЕСТНО: v0.1 доказывает evidence workflow НА FIXTURE, не доказывает production RAG и не сметное качество.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proxy.services.evidence_contract import (
    ConstructionHarnessResult,
    EvidenceBlock,
    EvidenceItem,
    EvidenceType,
    block_of,
)

# ── work_family инференс (грубый, для gesn_expand) ───────────────────────────────────────

_FAMILY_KEYWORDS = [
    ("earthworks", ("грунт", "котлован", "выемк", "разработ", "землян", "траншея")),
    ("waterproofing", ("гидроизол", "оклеечн", "обмазочн", "мастичн")),
    ("masonry", ("кладк", "кирпич", "перегородк")),
    ("roofing", ("кровл", "рулон", "мембран")),
    ("concrete_monolithic", ("бетон", "монолит", "железобетон", "плит", "стен", "перекрыт", "фундамент", "колонн")),
]


def _infer_family(work_text: str) -> str:
    low = (work_text or "").lower()
    for fam, kws in _FAMILY_KEYWORDS:
        if any(k in low for k in kws):
            return fam
    return ""


# ── typed tool facades (поверх существующих сервисов) ────────────────────────────────────

@dataclass
class SourceRef:
    """Богатая ссылка на источник (Codex v0.2): откуда строка извлечена."""
    dataset_id: str = ""
    file_name: str = ""
    row_id: int | None = None
    page: int | None = None
    table_id: str = ""
    chunk_id: str = ""
    title: str = ""

    def ref(self) -> str:
        base = f"{self.dataset_id}/{self.file_name}" if self.dataset_id else (self.file_name or "doc")
        if self.row_id is not None:
            return f"{base}#row{self.row_id}"
        if self.page is not None:
            return f"{base}#p{self.page}"
        return base


def retrieve_project_doc(query: str = "", *, project_id: int = 0, dataset_ids: list[str] | None = None,
                         dataset_filter: str | None = None, doc_type: str = "", top_k: int = 5,
                         storage_root: Path | None = None, rows: list[dict] | None = None) -> dict[str, Any]:
    """v0.2 RETRIEVAL-BACKED facade: ищет проектный табличный документ (Ф9/ВОР/спецификация) в
    `storage/datasets/{ds}/_parquet/*.parquet` по dataset-scope (dataset_ids | project_id). Читает
    строки + богатый SourceRef. Ничего не нашёл → not_found (НЕ фантазия). `rows=` — ТОЛЬКО для
    unit-тестов facade (прямая инъекция), в production-path оркестратор его НЕ использует."""
    import pandas as pd
    trace: list[dict[str, Any]] = []

    if rows is not None:   # test-only direct injection через facade (не production path)
        for i, r in enumerate(rows):
            r.setdefault("source_file", str(r.get("source_file") or "injected"))
            r.setdefault("pos", str(r.get("pos") or i + 1))
        srcs = sorted({str(r.get("source_file")) for r in rows})
        return {"status": "found", "rows": rows, "sources": srcs,
                "trace": [{"step": "inject", "rows": len(rows)}]}

    root = storage_root or Path("storage/datasets")
    ds_ids = list(dataset_ids or [])
    if not ds_ids and project_id:
        try:
            from proxy.services.project_service import project_dataset_ids
            ds_ids = project_dataset_ids(project_id) or []
        except Exception as e:  # noqa: BLE001
            trace.append({"step": "resolve_scope", "error": str(e)})
    trace.append({"step": "resolve_scope", "datasets": ds_ids})
    if not ds_ids:
        return {"status": "not_found", "rows": [], "sources": [], "trace": trace,
                "warnings": ["нет dataset-scope (нет dataset_ids/project_id)"]}

    out_rows: list[dict[str, Any]] = []
    sources: list[str] = []
    for ds in ds_ids:
        proot = root / ds / "_parquet"
        if not proot.exists():
            continue
        for pq in sorted(proot.rglob("*.parquet")):
            if doc_type and doc_type.lower() not in pq.name.lower():
                continue
            try:
                df = pd.read_parquet(pq)
            except Exception as e:  # noqa: BLE001
                trace.append({"step": "read_parquet", "file": pq.name, "error": str(e)[:60]})
                continue
            fname = pq.name
            for i, rec in enumerate(df.to_dict("records")):
                rec = {k: (None if pd.isna(v) else v) for k, v in dict(rec).items()}
                sr = SourceRef(dataset_id=ds, file_name=fname, row_id=i)
                rec["source_file"] = sr.ref()
                rec.setdefault("pos", str(i + 1))
                out_rows.append(rec)
            sources.append(f"{ds}/{fname}")
            trace.append({"step": "read_parquet", "file": f"{ds}/{fname}", "rows": len(df)})
            if len(out_rows) >= top_k * 50:   # грубый предел
                break
    # v0.12: fallback — markdown-таблицы в .md (реальные датасеты без parquet)
    if not out_rows:
        from proxy.services.source_adapters import (extract_markdown_tables_from_file,
                                                    markdown_table_to_rows)
        md_warn = ""
        for ds in ds_ids:
            ddir = root / ds
            if not ddir.exists():
                continue
            for mp in sorted(ddir.rglob("*.md")):
                for tbl in extract_markdown_tables_from_file(mp):
                    conv = markdown_table_to_rows(tbl, file_name=mp.name, dataset_id=ds)
                    if conv["status"] == "ok":
                        out_rows.extend(conv["rows"])
                        sources.append(f"{ds}/{mp.name}")
                        trace.append({"step": "markdown_table", "file": f"{ds}/{mp.name}", "rows": len(conv["rows"])})
                    elif conv["status"] in ("not_recognized", "missing_required_columns"):
                        md_warn = conv["reason"]
                if len(out_rows) >= top_k * 50:
                    break
        if not out_rows and md_warn:
            trace.append({"step": "markdown_table", "warning": md_warn})

    status = "found" if out_rows else "not_found"
    return {"status": status, "rows": out_rows, "sources": sources, "trace": trace,
            "warnings": [] if out_rows else ["в scope нет табличных проектных документов (ни parquet, ни markdown-таблиц)"]}


def spec_to_bor(rows: list[dict]) -> dict[str, Any]:
    """Спецификация/Ф9-строки → позиции ВОР с PROVENANCE (source_ref). Не извлёк → empty."""
    from proxy.services.spec_to_bor_service import spec_rows_to_work_lines_v2
    lines = spec_rows_to_work_lines_v2(rows or [])
    positions = []
    for ln in lines:
        p = ln.payload()
        positions.append({"work": p["name"], "unit": p["unit"], "qty": p["qty"],
                          "source_refs": p.get("sources", []) or []})
    return {"status": "ok" if positions else "empty", "positions": positions}


def gesn_expand(position: dict[str, Any]) -> dict[str, Any]:
    """ВОР-позиция → кандидаты ГЭСН + bind (переиспользует Gate 2/3 харнесса). Плохая норма НЕ
    проходит: accepted → code; rejected/ambiguous → blocked. НЕ ослабляет применимость/ranking."""
    from proxy.services import estimate_harness_service as hns

    work = str(position.get("work", ""))
    family = _infer_family(work)
    unit = position.get("unit", "")
    # SAFETY (Codex): НЕОПРЕДЕЛЁННАЯ семья работ НЕ даёт COMPUTED. Без классификации
    # applicability была бы пермиссивна (приняла бы по «работа/монтаж») — дыра. Блокируем.
    if not family:
        res = hns.search_norm(work, work_family="", unit_hint=unit)
        return {"status": "needs_classification", "work_family": "", "candidates": res.get("candidates", []),
                "reason": "не удалось классифицировать вид работ (work_family unknown) — норма не привязана"}
    res = hns.search_norm(work, work_family=family, unit_hint=unit)
    cands = res.get("candidates", [])
    accepted = [c for c in cands if c.get("applicability_status") == "accepted"]
    if not accepted:
        why = "нет применимой нормы (все кандидаты rejected/ambiguous)" if cands else "норма не найдена"
        return {"status": "blocked", "work_family": family, "candidates": cands, "reason": why}
    top = accepted[0]
    return {"status": "accepted", "work_family": family, "norm_code": top["norm_code"],
            "norm_title": top["title"], "measure_unit": top["measure_unit"], "candidates": cands}


def lsr_assemble(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Позиции (accepted code + qty из документа) → ЛСР. Считает ТОЛЬКО код. Цена из ГЭСН.
    final запрещён при blockers (нет кода/qty). Числа — COMPUTED/RETRIEVED, не из модели."""
    from proxy.services.estimate_harness_service import _norm_unit_factor, _units_compatible
    from proxy.services.gesn_service import get_norm
    from proxy.services.lsr_assembly_service import assemble
    from proxy.services.nr_sp_service import resolve as resolve_nr_sp
    from proxy.services.object_estimate_service import _f

    asm, blockers = [], []
    for p in positions:
        code = str(p.get("code", ""))
        norm = get_norm(code)
        if norm is None:
            blockers.append({"work": p.get("work"), "reason": f"код {code} не в базе"})
            continue
        if p.get("qty") in (None, 0):
            blockers.append({"work": p.get("work"), "reason": "нет количества в документе"})
            continue
        # UNIT GATE (Gate 1, НЕ ослабляем): физ.объём документа → измеритель нормы.
        # «100 м3» factor=100 → qty_lsr = phys/100. Несовместимая единица → blocker.
        factor, base = _norm_unit_factor(norm.get("unit", ""))
        if not _units_compatible(p.get("unit", ""), base):
            blockers.append({"work": p.get("work"),
                             "reason": f"единица документа {p.get('unit')} ≠ {base} нормы"})
            continue
        phys = _f(p.get("qty"))
        qty_lsr = round(phys / factor, 6) if factor else phys
        rs = resolve_nr_sp(norm.get("name", ""))
        asm.append({"code": code, "name": p.get("work") or norm.get("name", ""),
                    "unit": norm.get("unit", ""), "qty": qty_lsr, "section": "ВОР",
                    "nr_pct": rs["nr_pct"], "sp_pct": rs["sp_pct"],
                    "phys_qty": phys, "phys_unit": p.get("unit", ""), "conversion": f"{phys} / {factor}",
                    "source_refs": p.get("source_refs", [])})
    lsr = assemble(asm) if asm else {"summary": {"total": 0.0}, "positions": []}
    smr = round(_f(lsr.get("summary", {}).get("total")), 2)
    cont = round(smr * 0.02, 2)
    vat = round((smr + cont) * 0.20, 2)
    return {"lsr": lsr, "asm_positions": asm, "blockers": blockers,
            "smr": smr, "grand_total": round(smr + cont + vat, 2)}


# ── оркестратор: Ф9/ВОР → ГЭСН → ЛСР → evidence ──────────────────────────────────────────

def run_construction_harness(query: str, *, project_id: int = 0, dataset_ids: list[str] | None = None,
                             doc_type: str = "", storage_root: Path | None = None,
                             rows: list[dict] | None = None) -> ConstructionHarnessResult:
    """End-to-end строительный evidence-контур (v0.2 retrieval-backed). Источник НАХОДИТСЯ через
    retrieve_project_doc по scope (project_id/dataset_ids), не подаётся напрямую. Числа из tool-
    результатов, не из LLM. `rows=` — только для тестов facade."""
    from proxy.services.object_estimate_service import _f

    trace: list[dict[str, Any]] = []

    # 1. найти документ через retrieval-backed facade
    doc = retrieve_project_doc(query, project_id=project_id, dataset_ids=dataset_ids,
                               doc_type=doc_type, storage_root=storage_root, rows=rows)
    trace.append({"tool": "retrieve_project_doc", "status": doc["status"],
                  "sources": doc.get("sources", [])})
    if doc["status"] != "found":
        miss = EvidenceItem(EvidenceType.MISSING, "Проектный документ не найден",
                            blockers=["нет источника (Ф9/ВОР/спецификация)"], status="missing")
        return ConstructionHarnessResult(
            answer_data={"query": query}, evidence_blocks=[block_of(EvidenceType.MISSING, "Источник", [miss])],
            tool_trace=trace, total_status="no_data")

    sources = doc["sources"]
    # 2. ВОР из документа (provenance) → RETRIEVED
    bor = spec_to_bor(doc["rows"])
    trace.append({"tool": "spec_to_bor", "status": bor["status"], "positions": len(bor["positions"])})
    retrieved_items = [
        EvidenceItem(EvidenceType.RETRIEVED, p["work"], value=p["qty"], unit=p["unit"],
                     source_refs=p["source_refs"] or sources, status="supported")
        for p in bor["positions"] if p.get("qty") is not None
    ]

    # 3. gesn_expand + накопить позиции под расчёт
    computed_items, missing_items, blocked_items = [], [], []
    asm_input = []
    for p in bor["positions"]:
        if p.get("qty") in (None, 0):
            missing_items.append(EvidenceItem(EvidenceType.MISSING, p["work"],
                                 blockers=["нет количества в документе"], status="missing"))
            continue
        exp = gesn_expand(p)
        trace.append({"tool": "gesn_expand", "work": p["work"][:40], "status": exp["status"]})
        if exp["status"] != "accepted":
            blocked_items.append(EvidenceItem(EvidenceType.BLOCKED, p["work"],
                                 blockers=[exp.get("reason", "норма не подтверждена")], status="blocked"))
            continue
        asm_input.append({"code": exp["norm_code"], "work": p["work"], "unit": p["unit"],
                          "qty": p["qty"], "source_refs": p["source_refs"]})

    # 4. lsr_assemble (только accepted+qty) → COMPUTED
    lsr = lsr_assemble(asm_input)
    trace.append({"tool": "lsr_assemble", "positions": len(lsr["asm_positions"]),
                  "blockers": len(lsr["blockers"])})
    for ap in lsr["asm_positions"]:
        computed_items.append(EvidenceItem(
            EvidenceType.COMPUTED, ap["name"], value=ap["qty"], unit=ap["unit"],
            formula=f"кол-во ВОР {ap.get('phys_qty')} {ap.get('phys_unit')} → измеритель нормы "
                    f"({ap.get('conversion')}) × расценка ГЭСН",
            inputs=[{"name": "qty_документа", "value": ap.get("phys_qty"), "unit": ap.get("phys_unit"),
                     "type": "RETRIEVED"},
                    {"name": "norm_unit_conversion", "value": ap.get("conversion")},
                    {"name": "norm_code", "value": ap["code"]}],
            source_refs=[ap["code"]] + (ap.get("source_refs") or []), status="computed"))
    for b in lsr["blockers"]:
        blocked_items.append(EvidenceItem(EvidenceType.BLOCKED, str(b.get("work", "")),
                             blockers=[b.get("reason", "")], status="blocked"))

    # статус итога: complete только если есть computed и НЕТ blockers/missing
    has_blockers = bool(blocked_items or missing_items)
    if not computed_items:
        total_status = "blocked"
    elif has_blockers:
        total_status = "partial"
    else:
        total_status = "complete"

    blocks = [block_of(EvidenceType.RETRIEVED, "Исходный документ (Ф9/ВОР)", retrieved_items)]
    if computed_items:
        blocks.append(block_of(EvidenceType.COMPUTED, "Рассчитано (ЛСР)", computed_items))
    if missing_items:
        blocks.append(block_of(EvidenceType.MISSING, "Нет данных", missing_items))
    if blocked_items:
        blocks.append(block_of(EvidenceType.BLOCKED, "Отклонено / итог не полон", blocked_items))

    partial = {"smr": lsr["smr"], "grand_total": lsr["grand_total"], "positions": len(lsr["asm_positions"])}
    return ConstructionHarnessResult(
        answer_data={"query": query, "object_positions": len(bor["positions"])},
        evidence_blocks=blocks, tool_trace=trace, sources=sources,
        total_status=total_status,
        blockers=[{"work": i.title, "reason": "; ".join(i.blockers)} for i in blocked_items],
        partial_total=lsr["grand_total"] if computed_items else None,
        final_total=lsr["grand_total"] if total_status == "complete" else None)


# ── адаптеры существующих результатов в evidence ─────────────────────────────────────────

def rag_result_to_evidence(rag_response: dict[str, Any]) -> ConstructionHarnessResult:
    """Обернуть обычный RAG-ответ в RETRIEVED (НЕ душить сметными gates). Нет источников → MISSING."""
    answer = str(rag_response.get("answer", "") or "")
    srcs = list(rag_response.get("sources", []) or [])
    if srcs:
        items = [EvidenceItem(EvidenceType.RETRIEVED, s, source_refs=[s], status="supported") for s in srcs]
        block = block_of(EvidenceType.RETRIEVED, "Источники ответа", items)
        return ConstructionHarnessResult(answer_data={"answer": answer}, evidence_blocks=[block],
                                          sources=srcs, total_status="complete")
    miss = EvidenceItem(EvidenceType.MISSING, "Ответ без подтверждённых источников",
                        blockers=["RAG не вернул источников"], status="missing")
    return ConstructionHarnessResult(answer_data={"answer": answer},
                                     evidence_blocks=[block_of(EvidenceType.MISSING, "Источники", [miss])],
                                     total_status="no_data")


def smeta_harness_result_to_evidence(hres: dict[str, Any]) -> ConstructionHarnessResult:
    """Результат smeta_harness (Gate 1-4) → evidence-блоки. Safety-логику НЕ меняем — адаптируем выход.
    computed→COMPUTED; by_assumption→ASSUMED; needs_input→MISSING; rejected→BLOCKED."""
    computed = [EvidenceItem(EvidenceType.COMPUTED, p.get("work", ""), value=p.get("qty"),
                             unit=p.get("norm_unit", ""), formula=p.get("formula", ""),
                             source_refs=[p.get("code", "")], status="computed")
                for p in hres.get("computed", [])]
    assumed = [EvidenceItem(EvidenceType.ASSUMED, p.get("work", ""),
                            assumptions=(p.get("assumptions") or ["принято допущение"]), status="preliminary")
               for p in hres.get("by_assumption", [])]
    missing = [EvidenceItem(EvidenceType.MISSING, p.get("work", ""),
                            blockers=[p.get("reason", "нет данных")], status="missing")
               for p in hres.get("needs_input", [])]
    blocked = [EvidenceItem(EvidenceType.BLOCKED, p.get("work", ""),
                            blockers=[f"{p.get('status')}: {p.get('reason', '')}"], status="blocked")
               for p in hres.get("rejected", [])]
    blocks = []
    for et, title, items in ((EvidenceType.COMPUTED, "Рассчитано", computed),
                             (EvidenceType.ASSUMED, "Допущения", assumed),
                             (EvidenceType.MISSING, "Нет данных", missing),
                             (EvidenceType.BLOCKED, "Отклонено", blocked)):
        if items:
            blocks.append(block_of(et, title, items))
    ts_map = {"complete": "complete", "partial": "partial", "blocked": "blocked"}
    total_status = ts_map.get(hres.get("total_status", ""), "blocked")
    pt = (hres.get("partial_total") or {}).get("grand_total") if hres.get("partial_total") else None
    ft = (hres.get("final_total") or {}).get("grand_total") if hres.get("final_total") else None
    return ConstructionHarnessResult(
        answer_data={"schema": hres.get("schema", {})}, evidence_blocks=blocks,
        total_status=total_status, partial_total=pt, final_total=ft,
        blockers=[{"work": i.title, "reason": "; ".join(i.blockers)} for i in blocked])


# ── feature flag + route hints (Codex E/F): OFF по умолчанию, НЕ вшито в chat.py ─────────

def construction_harness_enabled() -> bool:
    """Feature flag. OFF (дефолт) → chat-поведение НЕ меняется."""
    return os.getenv("LES_CONSTRUCTION_HARNESS_ENABLED", "").strip().lower() in ("1", "true", "yes")


@dataclass
class RouteHint:
    """Подсказка маршрута (НЕ ответчик): keyword-каскад даёт hint, не отдельный ответ (Codex F)."""
    source: str                       # keyword | explicit | llm_router | fallback
    intent: str                       # retrieve_norm | estimate_from_bor | table_agg | none
    confidence: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)


_BOR_INTENT_TERMS = ("по ф9", "по вор", "ведомость объ", "собери лср", "предварительн", "смету по ф9",
                     "лср по", "из ведомости")


def route_hint(question: str) -> RouteHint:
    """Keyword → hint (не ответ). Распознаёт «собрать ЛСР по Ф9/ВОР» → estimate_from_bor."""
    ql = (question or "").lower()
    matched = [t for t in _BOR_INTENT_TERMS if t in ql]
    if matched:
        return RouteHint("keyword", "estimate_from_bor", 0.6, matched,
                         ["retrieve_project_doc", "spec_to_bor", "gesn_expand", "lsr_assemble"])
    return RouteHint("keyword", "none", 0.0)


def maybe_construction_harness(question: str, *, project_id: int = 0,
                               dataset_ids: list[str] | None = None,
                               storage_root: Path | None = None) -> ConstructionHarnessResult | None:
    """Feature-flagged entrypoint. OFF → None (chat не меняется). ON + intent=estimate_from_bor →
    запуск. НЕ вшит в chat.py (по ТЗ — рискованно), тестируется напрямую."""
    if not construction_harness_enabled():
        return None
    if route_hint(question).intent != "estimate_from_bor":
        return None
    return run_construction_harness(question, project_id=project_id, dataset_ids=dataset_ids,
                                    storage_root=storage_root)


# ── demo fixture (ЯВНО демо, не production-data) ─────────────────────────────────────────

def write_demo_project_doc(storage_root: Path, *, dataset_id: str = "demo_ds") -> str:
    """Записать demo Ф9 как ПРОЕКТНУЮ ТАБЛИЦУ (parquet) в storage — чтобы golden НАХОДИЛ её через
    retrieve_project_doc, а не получал напрямую. Возвращает dataset_id. ЯВНО демо, не production."""
    import pandas as pd
    pdir = Path(storage_root) / dataset_id / "_parquet"
    pdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(demo_f9_rows()).to_parquet(pdir / "f9_vor.parquet", index=False)
    return dataset_id


def demo_f9_rows() -> list[dict[str, Any]]:
    """ДЕМО Ф9/ВОР-fixture (НЕ реальные данные) для golden end-to-end. Объёмы — из «документа»."""
    return [
        {"name": "разработка грунта в котловане экскаватором", "unit": "м3", "qty": 7200,
         "source_file": "demo_f9_parking.xlsx", "pos": "1"},
        {"name": "устройство монолитной железобетонной фундаментной плиты", "unit": "м3", "qty": 720,
         "source_file": "demo_f9_parking.xlsx", "pos": "2"},
        {"name": "гидроизоляция фундаментов оклеечная", "unit": "м2", "qty": 1500,
         "source_file": "demo_f9_parking.xlsx", "pos": "3"},
    ]
