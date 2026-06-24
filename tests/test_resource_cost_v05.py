"""Unified Construction Harness v0.5 — Resource-Based Cost Calculation.

Воспроизведение ресурсного обсчёта ГЭСН09-06-006-03 кодом: норма→коэфф→цены→прямые→ФОТ→НР→СП→
итог позиции→ТЦ/КАЦ→grand. Числа только из tool (формулы+inputs+source_refs), не из модели. Нет
цены/ставки/коэфф → MISSING/BLOCKED. Golden = expected output, не вычислительный движок.

ЧЕСТНО: исходный xlsx отсутствовал в репо → fixture реконструирован по документированной структуре;
движок реальный, все golden-числа воспроизводятся точно.
"""

from pathlib import Path

import pytest

from proxy.services import resource_cost_service as rc
from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services.evidence_contract import EvidenceType

FIXTURE = Path("tests/fixtures/cost_calc/ПРИМЕР_обсчета_24_06.xlsx")
MONEY = 0.01
QTY = 0.001


# ── parsing (xlsx-fixture присутствует) ──────────────────────────────────────────────────

def test_parse_cost_workbook_sheets():
    pr = rc.parse_cost_workbook(FIXTURE)
    assert pr["status"] == "found"
    assert "пример" in pr["sheets"] and "по_кац" in pr["sheets"]

def test_parse_gesn_sheets_detected():
    pr = rc.parse_cost_workbook(FIXTURE)
    assert any("09-06-006-03" in c for c in pr["norm_codes"])
    assert any("06-03-004-13" in c for c in pr["norm_codes"])

def test_parse_example_position_qty():
    pr = rc.parse_cost_workbook(FIXTURE)
    assert abs(pr["position_qty"] - 26.958848) < 1e-4

def test_parse_kac_sheet_needs_kac_rows():
    pr = rc.parse_cost_workbook(FIXTURE)
    assert pr["kac_rows"] and all(r["status"] == "needs_kac" for r in pr["kac_rows"])

def test_parse_missing_file_not_found(tmp_path):
    pr = rc.parse_cost_workbook(tmp_path / "нет.xlsx")
    assert pr["status"] == "not_found"


# ── classification ───────────────────────────────────────────────────────────────────────

def test_resource_category_labor():
    assert rc.classify_resource_category("1-100-39", "Труд рабочих") == "labor"

def test_resource_category_machine():
    assert rc.classify_resource_category("91.05.05-015", "Кран") == "machine"

def test_resource_category_machinist_labor():
    assert rc.classify_resource_category("4-100-060", "ОТм(ЗТм) машинистов 6") == "machinist_labor"
    assert rc.classify_resource_category("2", "Затраты труда машинистов") == "machinist_labor"

def test_resource_category_material():
    assert rc.classify_resource_category("01.7.15.06-0111", "Кислород") == "material"

def test_project_quantity_p_is_project_quantity():
    assert rc.classify_resource_category("07.2.06.06", "материал", raw_qty="П") == "project_quantity"

def test_price_item_kac():
    assert rc.classify_resource_category("ТЦ_07.2.03.00_78", "Крепежная рама") == "price_item"


# ── coefficients ─────────────────────────────────────────────────────────────────────────

def test_coeff_1_15_retrieved_from_source():
    coeff = rc.golden_position()["coeff"]
    assert coeff.labor_coeff == 1.15 and coeff.status == "retrieved" and "55/пр" in coeff.reason

def test_material_coeff_is_1():
    coeff = rc.golden_position()["coeff"]
    assert coeff.material_coeff == 1.0


# ── expansion: total_qty = norm × position × coeff ───────────────────────────────────────

def test_expand_worker_labor_qty():
    coeff = rc.golden_position()["coeff"]
    e = rc.expand_resource(rc.NormResource("1-100-39", "труд", 230.21, "чел.-ч", "labor"), 26.958848, coeff)
    assert abs(e.total_qty - 7137.1258578) < QTY

def test_expand_crane_qty():
    samples = {e.resource_code: e for e in rc.expand_sample()}
    assert abs(samples["91.05.05-015"].total_qty - 22.6319529) < QTY

def test_expand_oxygen_qty_no_material_coeff():
    samples = {e.resource_code: e for e in rc.expand_sample()}
    assert abs(samples["01.7.15.06-0111"].total_qty - 21.5670784) < QTY  # коэфф материала = 1

def test_expand_metal_structures_qty():
    samples = {e.resource_code: e for e in rc.expand_sample()}
    assert abs(samples["14.4.01.01-0003"].total_qty - 0.7278889) < QTY

def test_project_quantity_resource_not_computed():
    coeff = rc.golden_position()["coeff"]
    e = rc.expand_resource(rc.NormResource("07.2.06.06", "мат", None, "", "project_quantity", raw_qty="П"),
                           26.958848, coeff)
    assert e.total_qty is None and e.status == "missing"


# ── machinist mapping ─────────────────────────────────────────────────────────────────────

def test_machine_to_machinist_mapping_known():
    assert rc.machine_to_machinist("91.05.05-015") == "4-100-060"
    assert rc.machine_to_machinist("91.14.02-001") == "4-100-040"

def test_machine_to_machinist_unknown_returns_none():
    assert rc.machine_to_machinist("91.99.99-999") is None


# ── prices ───────────────────────────────────────────────────────────────────────────────

def test_price_found_current():
    p = rc.resolve_price(rc.ResourcePrice("1-100-39", "чел.-ч", current_price=552.21))
    assert p.price_status == "found_current" and p.current_price == 552.21

def test_price_base_times_index():
    p = rc.resolve_price(rc.ResourcePrice("91.06.03-062", "маш.-ч", base_price=13.44, index=1.42))
    assert p.price_status == "base_times_index" and abs(p.current_price - 19.08) < MONEY

def test_price_needs_kac_from_missing():
    p = rc.resolve_price(rc.ResourcePrice("01.7.15.06-0111", "м3"))
    assert p.price_status == "needs_kac" and p.current_price is None


# ── costs: golden ────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def golden():
    return rc.run_resource_cost_golden()

def test_worker_labor_cost_matches_golden(golden):
    assert abs(golden.labor_cost_total - 3941192.27) < MONEY

def test_direct_cost_total_matches_golden(golden):
    assert abs(golden.direct_cost_total - 4333793.60) < MONEY

def test_fot_matches_golden(golden):
    assert abs(golden.fot - 3960420.87) < MONEY

def test_nr_matches_golden(golden):
    assert golden.nr_rate == 0.93 and abs(golden.nr_amount - 3683191.41) < MONEY

def test_sp_matches_golden(golden):
    assert golden.sp_rate == 0.62 and abs(golden.sp_amount - 2455460.94) < MONEY

def test_position_total_matches_golden(golden):
    assert abs(golden.position_total - 10472445.95) < MONEY

def test_kac_item_total_matches_golden(golden):
    assert abs(golden.additional_price_items_total - 6354837.24) < MONEY

def test_grand_total_matches_golden(golden):
    assert abs(golden.grand_total - 16827283.19) < MONEY and golden.total_status == "complete"


# ── evidence invariants ──────────────────────────────────────────────────────────────────

def test_resource_calc_retrieved_sources_present(golden):
    retr = next(b for b in golden.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert all(it.source_refs for it in retr.items)

def test_computed_values_have_formula_and_inputs(golden):
    comp = next(b for b in golden.evidence_blocks if b.type is EvidenceType.COMPUTED)
    for it in comp.items:
        assert it.value is not None and (it.formula or it.inputs)

def test_project_quantity_p_is_missing_in_evidence(golden):
    miss = [it for b in golden.evidence_blocks if b.type is EvidenceType.MISSING for it in b.items]
    assert any("07.2.06.06" in it.title or "П" in "".join(it.blockers) for it in miss)

def test_missing_rate_blocks_complete():
    pos = rc.golden_position()
    pos["nr_rate"] = None        # нет ставки НР из источника
    res = rc.run_resource_cost_golden(pos)
    assert res.total_status != "complete" and res.grand_total is None

def test_no_llm_number_all_have_provenance(golden):
    for b in golden.evidence_blocks:
        for it in b.items:
            if it.value is not None:
                assert it.source_refs or it.formula


# ── routing + chat ───────────────────────────────────────────────────────────────────────

def test_route_resource_cost_calc():
    for q in ["проверь пример обсчёта", "разложи по ресурсам ГЭСН09-06-006-03", "покажи ФОТ НР СП по примеру",
              "что требует КАЦ", "прямые затраты по примеру"]:
        assert u.route_construction_intent(q).intent == "resource_cost_calc", q

def test_cost_project_ambiguous_requests_clarification():
    r = u.run_unified_construction_harness("стоимость проекта")
    assert r.total_status == "no_data" and r.answer_data.get("ambiguous")

def test_chat_resource_golden_complete():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY

def test_flag_off_preserves(monkeypatch):
    monkeypatch.delenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", raising=False)
    assert u.maybe_unified_construction_harness("проверь пример обсчёта") is None

def test_flag_on_routes_resource(monkeypatch):
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    r = u.maybe_unified_construction_harness("проверь пример обсчёта")
    assert r is not None and r.answer_data.get("intent") == "resource_cost_calc"


# ── регрессии v0.3/v0.4 (не сломали) ─────────────────────────────────────────────────────

def test_v04_source_scoped_ozk_still_asbuilt():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"

def test_v04_rules_ozk_still_norm_qa():
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_v03_f9_lsr_still_passes(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None

def test_v03_unit_gate_still_passes():
    res = ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])
    assert res["asm_positions"][0]["qty"] == 7.2
