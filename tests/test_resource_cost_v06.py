"""Unified Construction Harness v0.6 — Real Workbook Resource Cost Validation + Method Extraction.

Реальный ПРИМЕР_обсчета_24_06.xlsx (creator=fsnb2022.ru) найден и скопирован в fixtures. Движок
воспроизводит КОДОМ значения РЕАЛЬНОГО workbook; правая методзона листа `пример` → RETRIEVED
method-notes. xlsx хранит значения (4 формулы), не движок. Reconstructed НЕ выдаётся за real.
"""

from pathlib import Path

import pytest

from proxy.services import resource_cost_service as rc
from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services.evidence_contract import EvidenceType

REAL = rc.REAL_WORKBOOK
MONEY = 1.0


# ── presence / provenance ────────────────────────────────────────────────────────────────

def test_real_workbook_fixture_exists():
    assert REAL.exists(), "реальный workbook должен быть скопирован в tests/fixtures/cost_calc/"

def test_real_workbook_is_real_provenance():
    st = rc.real_workbook_status(REAL)
    assert st["provenance"] == "real" and "fsnb" in st["creator"].lower()

def test_reconstructed_not_marked_real():
    st = rc.real_workbook_status(rc.RECONSTRUCTED_FIXTURE)
    assert st["provenance"] == "reconstructed"     # openpyxl-генерация ≠ real

def test_absent_workbook_marks_absent(tmp_path):
    st = rc.real_workbook_status(tmp_path / "нет.xlsx")
    assert st["provenance"] == "absent" and not st["available"]


# ── parsing real workbook ────────────────────────────────────────────────────────────────

def test_real_workbook_sheet_names():
    pr = rc.parse_cost_workbook(REAL)
    assert set(["ГЭСН 06-03-004-13", "Лист2", "пример", "по_кац", "ГЭСН 09-06-006-03"]) <= set(pr["sheets"])

def test_real_workbook_formula_cells_are_few_not_engine():
    cells = rc.parse_formula_cells(REAL)
    # формул МАЛО (≈4: Z6=R6...), осн. расчёты — значениями (xlsx не движок)
    assert 0 < len(cells) <= 10
    assert all(c["formula"].startswith("=") for c in cells)

def test_parse_real_position_qty_and_lines():
    pr = rc.parse_real_workbook_position(REAL)
    assert pr["status"] == "found" and abs(pr["position_qty"] - 26.958848) < 1e-4
    assert len(pr["lines"]) >= 20

def test_parse_real_method_notes_right_zone():
    notes = rc.parse_method_notes(REAL)
    assert len(notes) > 10
    texts = " ".join(n.text.lower() for n in notes)
    assert "гр." in texts and "сплит" in texts        # реальные методнотации

def test_every_real_method_note_has_cell_ref():
    notes = rc.parse_method_notes(REAL)
    assert all(n.source_ref() and "!" in n.source_ref() for n in notes)

def test_parse_real_kac_item():
    pr = rc.parse_real_workbook_position(REAL)
    assert pr["kac"] and pr["kac"]["qty"] == 4 and abs(pr["kac"]["price"] - 1588709.31) < MONEY


# ── validation: code reproduces real workbook ────────────────────────────────────────────

@pytest.fixture(scope="module")
def val():
    return rc.validate_real_workbook(REAL)

def test_real_workbook_provenance_in_validation(val):
    assert val["provenance"] == "real"

def test_real_workbook_line_formulas_validated(val):
    assert val["line_diffs"] == []          # каждая строка: qty=norm×coeff×pos, current=base×idx, total=qty×cur

def test_real_workbook_direct_sum_matches(val):
    assert abs(val["computed_direct"] - val["stored"]["direct"]) < MONEY
    assert abs(val["stored"]["direct"] - 4333793.60) < MONEY

def test_real_workbook_fot_nr_sp_match(val):
    s = val["stored"]
    assert abs(s["fot"] - 3960420.87) < MONEY
    assert s["nr"]["rate"] == 93 and abs(s["nr"]["amount"] - 3683191.41) < MONEY
    assert s["sp"]["rate"] == 62 and abs(s["sp"]["amount"] - 2455460.94) < MONEY

def test_real_workbook_position_and_kac(val):
    assert abs(val["stored"]["position"] - 10472445.95) < MONEY
    assert abs(val["kac"]["total"] - 6354837.24) < MONEY

def test_real_workbook_matches_overall(val):
    assert val["matches"] is True

def test_engine_golden_matches_real_stored(val):
    # канонический v0.5-движок воспроизводит РЕАЛЬНЫЕ stored-итоги точно
    g = rc.run_resource_cost_golden()
    s = val["stored"]
    assert abs(g.direct_cost_total - s["direct"]) < MONEY
    assert abs(g.fot - s["fot"]) < MONEY
    assert abs(g.nr_amount - s["nr"]["amount"]) < MONEY
    assert abs(g.sp_amount - s["sp"]["amount"]) < MONEY
    assert abs(g.position_total - s["position"]) < MONEY
    assert abs(g.grand_total - 16827283.19) < MONEY


# ── resource logic on real lines ─────────────────────────────────────────────────────────

def test_real_workbook_categories():
    pr = rc.parse_real_workbook_position(REAL)
    cats = {l["category"] for l in pr["lines"]}
    assert {"labor", "machine", "machinist_labor", "material"} <= cats

def test_real_workbook_project_quantity_p_in_gesn_sheet():
    # 07.2.06.06 «Профили стальные» с qty «П» в листе ГЭСН → project_quantity (не считается)
    assert rc.classify_resource_category("07.2.06.06", "Профили стальные", raw_qty="П") == "project_quantity"

def test_real_workbook_needs_kac_rows():
    pr = rc.parse_cost_workbook(REAL)
    assert pr["kac_rows"] and all(r["status"] == "needs_kac" for r in pr["kac_rows"])


# ── evidence / chat ──────────────────────────────────────────────────────────────────────

def test_chat_resource_uses_real_workbook():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.answer_data.get("provenance") == "real"
    assert "fsnb" in r.answer_data.get("source_note", "").lower()
    assert r.answer_data.get("method_notes", 0) > 0

def test_chat_resource_method_notes_are_retrieved_evidence():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    retr_blocks = [b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED]
    method_block = [b for b in retr_blocks if "етодик" in b.title]
    assert method_block and all(it.source_refs for it in method_block[0].items)

def test_chat_resource_validation_present():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    v = r.answer_data.get("validation")
    assert v and v["matches"] is True and v["line_diffs"] == 0

def test_chat_resource_grand_complete():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY

def test_chat_resource_no_value_without_provenance():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    for b in r.evidence_blocks:
        for it in b.items:
            if it.value is not None:
                assert it.source_refs or it.formula

def test_not_design_cost():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert "не стоимость проектирования" in r.answer_data.get("cost_kind", "")


# ── routing + regressions ────────────────────────────────────────────────────────────────

def test_route_resource_cost_calc():
    assert u.route_construction_intent("проверь пример обсчёта").intent == "resource_cost_calc"

def test_v04_source_scoped_ozk_still_asbuilt():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"

def test_v04_rules_ozk_still_norm_qa():
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_v03_f9_lsr_still_passes(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None

def test_flag_off_preserves(monkeypatch):
    monkeypatch.delenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", raising=False)
    assert u.maybe_unified_construction_harness("проверь пример обсчёта") is None
