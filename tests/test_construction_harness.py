"""Construction RAG Harness v0.1 — evidence-driven контур, golden Ф9→ГЭСН→ЛСР.

Доказывает КОНТУР (не полное сметное качество): RAG нашёл источник → spec_to_bor извлёк
позиции с provenance → gesn_expand (Gate 2/3) → lsr_assemble (Gate 1 unit) → evidence-блоки.
Числа не из текста LLM.
"""

from proxy.services import construction_harness_service as ch
from proxy.services.evidence_contract import EvidenceType, numbers_in_answer_have_provenance


# ── фасады ────────────────────────────────────────────────────────────────────────────────

def test_spec_to_bor_positions_keep_source_ref():
    bor = ch.spec_to_bor(ch.demo_f9_rows())
    assert bor["status"] == "ok" and bor["positions"]
    for p in bor["positions"]:
        assert p["source_refs"]                       # каждая позиция — с provenance


def test_gesn_expand_rejected_norm_not_computed():
    # работа без нормы (полная абракадабра) → не accepted (норма не пройдёт в расчёт)
    exp = ch.gesn_expand({"work": "жжжыыы щщщъъъ ёёёххх ыфвапр", "unit": "м3"})
    assert exp["status"] != "accepted"


def test_unknown_work_family_not_computed_safety():
    """SAFETY: неопределённая семья работ → needs_classification, НЕ accepted (нет COMPUTED).
    Даже если что-то нашлось по «работа/общего» — без классификации в расчёт не идёт."""
    exp = ch.gesn_expand({"work": "некие работы общего вида по объекту", "unit": "м3"})
    assert exp["status"] == "needs_classification"     # не accepted → не посчитается
    # сквозь оркестратор: позиция без семьи → BLOCKED, не COMPUTED, final запрещён
    rows = ch.demo_f9_rows() + [{"name": "некие работы общего вида", "unit": "м3", "qty": 5,
                                 "source_file": "demo_f9_parking.xlsx", "pos": "8"}]
    r = ch.run_construction_harness("смета", rows=rows)
    assert r.total_status in ("partial", "blocked") and r.final_total is None
    blocked = [it for b in r.evidence_blocks if b.type is EvidenceType.BLOCKED for it in b.items]
    assert blocked and any("классифиц" in "; ".join(it.blockers).lower() for it in blocked)


def test_lsr_unit_gate_converts_physical_to_norm_measure():
    # физ.720 м³ при норме «100 м3» → 7.2 нормо-ед (НЕ 720), Gate 1 не ослаблен
    res = ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])
    assert res["asm_positions"] and res["asm_positions"][0]["qty"] == 7.2


def test_lsr_unit_mismatch_blocks():
    # норма в м2, документ в м3 → blocker, не считаем
    res = ch.lsr_assemble([{"code": "12-01-021-01", "work": "кровля?", "unit": "м3", "qty": 100}])
    assert res["asm_positions"] == [] and res["blockers"]


# ── golden end-to-end ───────────────────────────────────────────────────────────────────

def test_construction_harness_e2e_f9_to_lsr():
    r = ch.run_construction_harness("смета по Ф9 паркинга", rows=ch.demo_f9_rows())
    # контур пройден
    tools = [t["tool"] for t in r.tool_trace]
    assert "retrieve_project_doc" in tools and "spec_to_bor" in tools
    assert "gesn_expand" in tools and "lsr_assemble" in tools
    types = {b.type for b in r.evidence_blocks}
    assert EvidenceType.RETRIEVED in types and EvidenceType.COMPUTED in types
    # RETRIEVED несёт source refs
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert all(it.source_refs for it in retr.items)
    # все числа имеют provenance (не из текста LLM)
    assert numbers_in_answer_have_provenance(r)
    # unit-gate сработал — итог не миллиардный
    assert r.partial_total is not None and r.partial_total < 100_000_000


def test_final_total_blocked_when_critical_blockers():
    # строка БЕЗ количества → позиция MISSING → итог не complete, final None
    rows = ch.demo_f9_rows() + [{"name": "устройство стен монолитных", "unit": "м3",
                                 "source_file": "demo_f9_parking.xlsx", "pos": "9"}]  # нет qty
    r = ch.run_construction_harness("смета", rows=rows)
    assert r.total_status in ("partial", "blocked")
    assert r.final_total is None                       # critical (missing) → final запрещён
    assert any(b.type is EvidenceType.MISSING for b in r.evidence_blocks)


def test_llm_numbers_not_used_without_tool_result():
    # контур чисто детерминированный: числа ТОЛЬКО из tool-результатов (qty документа + цена ГЭСН)
    r = ch.run_construction_harness("смета по Ф9", rows=ch.demo_f9_rows())
    for b in r.evidence_blocks:
        for it in b.items:
            if it.value is not None:
                # каждое число — RETRIEVED(источник) или COMPUTED(формула+код)
                assert it.source_refs or it.formula


# ── адаптеры существующих результатов ────────────────────────────────────────────────────

def test_rag_result_wrapped_as_retrieved():
    r = ch.rag_result_to_evidence({"answer": "СП говорит...", "sources": ["СП 1.13130", "ГОСТ 30247"]})
    assert r.total_status == "complete"
    assert r.evidence_blocks[0].type is EvidenceType.RETRIEVED
    assert len(r.evidence_blocks[0].items) == 2
    # без источников → MISSING
    r2 = ch.rag_result_to_evidence({"answer": "из головы", "sources": []})
    assert r2.evidence_blocks[0].type is EvidenceType.MISSING


# ── v0.2: retrieval-backed facade (источник НАХОДИТСЯ, не подаётся) ───────────────────────

def test_retrieve_project_doc_returns_source_refs(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)              # demo Ф9 → parquet в storage
    doc = ch.retrieve_project_doc("ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert doc["status"] == "found" and doc["rows"]
    assert doc["sources"]                                 # источник (dataset/file)
    assert all("#row" in str(r.get("source_file", "")) for r in doc["rows"])  # богатый source_ref


def test_retrieve_project_doc_not_found_yields_missing_evidence(tmp_path):
    # scope без табличных документов → not_found → MISSING evidence, НЕ фантазия
    r = ch.run_construction_harness("ЛСР", dataset_ids=["nonexistent_ds"], storage_root=tmp_path)
    assert r.total_status == "no_data"
    assert r.evidence_blocks[0].type is EvidenceType.MISSING
    assert r.final_total is None


def test_retrieval_backed_f9_to_lsr_golden(tmp_path):
    """ГЛАВНЫЙ v0.2 golden: документ НАЙДЕН через facade (parquet по scope), не подан напрямую."""
    ds = ch.write_demo_project_doc(tmp_path)
    r = ch.run_construction_harness("собери предварительную ЛСР по Ф9 паркинга",
                                    dataset_ids=[ds], storage_root=tmp_path)
    tools = [t["tool"] for t in r.tool_trace]
    assert tools[0] == "retrieve_project_doc" and r.tool_trace[0]["status"] == "found"
    types = {b.type for b in r.evidence_blocks}
    assert EvidenceType.RETRIEVED in types and EvidenceType.COMPUTED in types
    # source_ref сквозной: facade(dataset/file/row) → spec_to_bor(#pos) → evidence
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert all(it.source_refs and "f9_vor.parquet" in it.source_refs[0] for it in retr.items)
    assert numbers_in_answer_have_provenance(r)
    assert r.partial_total is not None and r.partial_total < 100_000_000   # unit-gate


# ── v0.2: feature flag (OFF по умолчанию, не меняет chat) ─────────────────────────────────

def test_feature_flag_off_returns_none(monkeypatch):
    monkeypatch.delenv("LES_CONSTRUCTION_HARNESS_ENABLED", raising=False)
    assert ch.maybe_construction_harness("собери ЛСР по Ф9") is None   # OFF → None, chat не меняется


def test_feature_flag_on_routes_matching_query(monkeypatch, tmp_path):
    monkeypatch.setenv("LES_CONSTRUCTION_HARNESS_ENABLED", "1")
    ds = ch.write_demo_project_doc(tmp_path)
    # подходящий intent (estimate_from_bor) + scope → запуск
    res = ch.maybe_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert res is not None and res.evidence_blocks
    # неподходящий запрос → None даже при ON
    assert ch.maybe_construction_harness("что такое огнестойкость") is None


def test_route_hint_is_hint_not_answer():
    h = ch.route_hint("собери ЛСР по Ф9")
    assert h.intent == "estimate_from_bor" and h.source == "keyword" and h.suggested_tools
    assert ch.route_hint("привет").intent == "none"


def test_smeta_harness_result_maps_to_evidence_blocks():
    hres = {
        "computed": [{"work": "плита", "code": "06-02-001-01", "qty": 7.2, "norm_unit": "100 м3", "formula": "S1*0.4"}],
        "by_assumption": [{"work": "плита", "assumptions": ["толщина 0.4"]}],
        "needs_input": [{"work": "стены", "reason": "нет длины"}],
        "rejected": [{"work": "реактор", "status": "rejected_applicability", "reason": "защитная оболочка"}],
        "total_status": "partial",
        "partial_total": {"grand_total": 1000.0}, "final_total": None,
    }
    r = ch.smeta_harness_result_to_evidence(hres)
    types = {b.type for b in r.evidence_blocks}
    assert {EvidenceType.COMPUTED, EvidenceType.ASSUMED, EvidenceType.MISSING, EvidenceType.BLOCKED} <= types
    assert r.total_status == "partial" and r.final_total is None and r.partial_total == 1000.0
