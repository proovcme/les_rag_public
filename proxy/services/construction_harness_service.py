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

def retrieve_project_doc(query: str, *, rows: list[dict] | None = None,
                         project_id: int = 0) -> dict[str, Any]:
    """Найти проектный документ (Ф9/ВОР/спецификация). v0.1: rows инъектируются (fixture/демо).
    Прод-расширение — table_query/RAG по project_id/dataset_scope. RETRIEVED или MISSING."""
    if rows:
        sources = sorted({str(r.get("source_file") or "demo") for r in rows})
        return {"status": "found", "rows": rows, "sources": sources}
    return {"status": "not_found", "rows": [], "sources": []}


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
        qty_lsr = round(_f(p.get("qty")) / factor, 6) if factor else _f(p.get("qty"))
        rs = resolve_nr_sp(norm.get("name", ""))
        asm.append({"code": code, "name": p.get("work") or norm.get("name", ""),
                    "unit": norm.get("unit", ""), "qty": qty_lsr, "section": "ВОР",
                    "nr_pct": rs["nr_pct"], "sp_pct": rs["sp_pct"]})
    lsr = assemble(asm) if asm else {"summary": {"total": 0.0}, "positions": []}
    smr = round(_f(lsr.get("summary", {}).get("total")), 2)
    cont = round(smr * 0.02, 2)
    vat = round((smr + cont) * 0.20, 2)
    return {"lsr": lsr, "asm_positions": asm, "blockers": blockers,
            "smr": smr, "grand_total": round(smr + cont + vat, 2)}


# ── оркестратор: Ф9/ВОР → ГЭСН → ЛСР → evidence ──────────────────────────────────────────

def run_construction_harness(query: str, *, rows: list[dict] | None = None,
                             project_id: int = 0) -> ConstructionHarnessResult:
    """End-to-end строительный evidence-контур. Числа из tool-результатов, не из LLM."""
    from proxy.services.object_estimate_service import _f

    trace: list[dict[str, Any]] = []

    # 1. найти документ
    doc = retrieve_project_doc(query, rows=rows, project_id=project_id)
    trace.append({"tool": "retrieve_project_doc", "status": doc["status"]})
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
            formula="кол-во (ВОР) × расценка ГЭСН → ЛСР", source_refs=[ap["code"]] + (ap.get("source_refs") or []),
            status="computed"))
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
                            assumptions=p.get("assumptions", []), status="preliminary")
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


# ── demo fixture (ЯВНО демо, не production-data) ─────────────────────────────────────────

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
