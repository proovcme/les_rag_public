"""PR21: literal work rows, normative generation and resource addresses."""

import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from proxy.services import attachment_source_catalog_service as catalog_service
from proxy.services import gesn_service
from proxy.services.chat_evidence_application_service import bind_row_evidence_ids
from proxy.services.model_resource_binding_service import resource_binding_position_fields
from proxy.services.model_resource_reference_service import resource_slot_records
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows
from proxy.smeta_core import norm_browser


CODE = "ГЭСНм08-02-001-01"
KEY = "ГЭСНм:08-02-001-01"


@pytest.mark.parametrize("title", [
    "Монтаж устройства (всего 2 комплекта)", "Монтаж Total Control", "Устройство с итоговой проверкой",
    "Всего нужно смонтировать два устройства",
])
@pytest.mark.parametrize("unit", ["шт", ""])
def test_work_caption_is_never_a_subtotal_by_substring(tmp_path, title, unit):
    workbook = Workbook()
    workbook.active.title = "ВОР"
    workbook.active.append(["Наименование работ", "Ед. изм.", "Кол-во"])
    workbook.active.append([title, unit, 2])
    path = tmp_path / "works.xlsx"
    workbook.save(path)
    catalog = catalog_service.load_tabular_source_catalog(path)
    assert catalog.lookup("ВОР!R2").is_work_row()
    assert "ВОР!R2" in catalog.work_locators()


def _base(path):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE norms (norm_key TEXT PRIMARY KEY, norm_id TEXT, edition TEXT,
                display_code TEXT, base_type TEXT, norm_name TEXT, norm_unit TEXT,
                work_steps TEXT, source_doc TEXT, source_guid TEXT, resource_count INTEGER);
            CREATE TABLE resources (id INTEGER PRIMARY KEY, parent_norm_id TEXT, kind TEXT,
                resource_code TEXT, resource_name TEXT, resource_unit TEXT, per_unit REAL,
                price REAL, source_doc TEXT, source_guid TEXT);
        """)
        conn.execute("INSERT INTO norms VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            KEY, "N", "fixture", CODE, "ГЭСНм", "Монтаж устройства", "шт",
            "[]", "norm.xml", "norm-guid", 2,
        ))
        for index, price in enumerate((10, 20), 1):
            conn.execute("INSERT INTO resources VALUES (?,?,?,?,?,?,?,?,?,?)", (
                index, "N", "material", "M", "Материал", "шт", 1, price, "norm.xml", "same-guid",
            ))


def _card(path, *, alias="Q1.H1", identity="card-A"):
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    card = norm_browser.read_norm_card_exact(norm_code=CODE, base_path=path, expected_base_sha256=sha)["card"]
    card["resources"] = resource_slot_records(card)
    body = f"Norm: {CODE}\n" + "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in card["resources"])
    return SimpleNamespace(content=body, doc_name="norm.xml", meta={
        **card, "exact_card_read": True, "model_evidence_ref": alias, "global_evidence_id": identity,
    })


def _row(**extra):
    return {"source_row": "S!R2", "row_role": "work", "norm_code": CODE,
            "title": "Монтаж устройства", "unit": "шт", "quantity": 2, "evidence_refs": ["Q1.H1"], **extra}


def test_changed_normative_generation_cannot_be_priced_as_the_shown_card(tmp_path, monkeypatch):
    path = tmp_path / "norms.sqlite"
    _base(path)
    card = _card(path)
    rows = bind_row_evidence_ids([_row()], [card])
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE resources SET per_unit=9")
    monkeypatch.setattr(norm_browser, "_base_path", lambda: path)
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_a, **_k: {
        "code": CODE, "unit": "шт", "resources": [{"kind": "material", "code": "M",
            "name": "Материал", "unit": "шт", "per_unit": 9, "price": 10}],
    })
    trace = build_lsr_trace_from_visible_rows(rows)
    assert trace["row_bindings"][0]["status"] == "norm_source_conflict"
    assert not trace["sections"]
    assert trace["summary"]["result_status"] != "priced_final"
    assert trace["row_bindings"][0]["source_row"]["norm_code"] == CODE


def test_calculation_uses_one_verified_snapshot_not_an_unpinned_second_read(tmp_path, monkeypatch):
    path = tmp_path / "norms.sqlite"
    _base(path)
    card = _card(path)
    rows = bind_row_evidence_ids([_row()], [card])
    monkeypatch.setattr(norm_browser, "_base_path", lambda: path)
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_a, **_k: pytest.fail("unpinned norm read"))
    from proxy.smeta_core import integrity
    monkeypatch.setattr(integrity, "normative_base_integrity", lambda **_k: {"trusted_for_pricing": True})
    trace = build_lsr_trace_from_visible_rows(rows)
    position = trace["sections"][0]["positions"][0]
    assert position["summary"]["known_amount"] == 60
    assert position["summary"]["normative_base_sha256"] == card.meta["normative_base_sha256"]
    assert rows[0]["norm_code"] == CODE


@pytest.mark.parametrize("identical_prices", [False, True])
def test_address_targets_second_resource_even_after_first_is_removed(tmp_path, identical_prices):
    path = tmp_path / "norms.sqlite"
    _base(path)
    if identical_prices:
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE resources SET price=10")
    card = _card(path)
    actions = [{"action": "exclude", "target_resource_ref": "Q1.H1#resource=1", "reason": "Источник",
                "basis_ref": "S!R2"},
               {"action": "reuse", "target_resource_ref": "Q1.H1#resource=2", "reason": "Источник",
                "basis_ref": "S!R2"}]
    bound = bind_row_evidence_ids([_row(resource_bindings=actions)], [card])[0]
    resources = copy.deepcopy(card.meta["resources"])
    before = copy.deepcopy((resources, bound))
    result = resource_binding_position_fields(bound, resources, work_id="W", work_qty=2,
        physical_quantity=2, physical_unit="шт")
    assert result["resource_binding_conflicts"] == []
    assert [entry["status"] for entry in result["resource_binding_audit"]] == ["applied", "applied"]
    assert result["resources"][0]["resource_slot"] == 2
    assert result["resources"][0]["price"] == 0
    assert result["resource_bindings"] == actions
    assert (resources, bound) == before


def test_replayed_alias_does_not_repin_original_norm_to_a_new_generation(tmp_path):
    path = tmp_path / "norms.sqlite"
    _base(path)
    original = _card(path)
    bound = bind_row_evidence_ids([_row()], [original])[0]
    saved = copy.deepcopy(bound["_normative_source_pin"])
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE resources SET per_unit=9")
    current = _card(path, identity="card-B")
    replayed = bind_row_evidence_ids([bound], [current], binding_phase="replay")[0]
    assert replayed["_normative_source_pin"] == saved
    assert replayed["evidence_bindings"] == {"Q1.H1": "card-A"}


def test_old_saved_row_can_pin_only_its_saved_global_card(tmp_path):
    path = tmp_path / "norms.sqlite"
    _base(path)
    original = _card(path)
    bound = bind_row_evidence_ids([_row()], [original])[0]
    bound.pop("_normative_source_pin")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE resources SET per_unit=9")
    current = _card(path, identity="card-B")
    missing = bind_row_evidence_ids([bound], [current], binding_phase="replay")[0]
    assert missing["_normative_source_pin"]["status"] == "saved_generation_unavailable"
    replayed = bind_row_evidence_ids([bound], [original], binding_phase="replay")[0]
    assert replayed["_normative_source_pin"]["normative_base_sha256"] == original.meta["normative_base_sha256"]


def test_two_cited_generations_are_a_conflict_not_a_first_card_choice(tmp_path, monkeypatch):
    path = tmp_path / "norms.sqlite"
    _base(path)
    original = _card(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE resources SET per_unit=9")
    current = _card(path, alias="Q1.H2", identity="card-B")
    rows = bind_row_evidence_ids([_row(evidence_refs=["Q1.H1", "Q1.H2"])], [original, current])
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_a, **_k: pytest.fail("fallback"))
    trace = build_lsr_trace_from_visible_rows(rows)
    assert trace["row_bindings"][0]["status"] == "norm_source_conflict"
    assert rows[0]["_normative_source_pin"]["status"] == "conflict"


def test_action_only_reference_also_pins_the_normative_generation(tmp_path):
    path = tmp_path / "norms.sqlite"
    _base(path)
    card = _card(path)
    row = _row(evidence_refs=[], resource_bindings=[{
        "action": "reuse", "target_resource_ref": "Q1.H1#resource=2",
        "reason": "Источник", "basis_ref": "S!R2",
    }])
    bound = bind_row_evidence_ids([row], [card])[0]
    assert bound["_normative_source_pin"]["normative_base_sha256"] == card.meta["normative_base_sha256"]


def test_first_bind_discards_a_model_forged_private_pin(tmp_path):
    path = tmp_path / "norms.sqlite"
    _base(path)
    card = _card(path)
    forged = {"status": "pinned", "normative_base_sha256": "f" * 64}
    bound = bind_row_evidence_ids([_row(_normative_source_pin=forged)], [card], binding_phase="first")[0]
    assert bound["_normative_source_pin"]["normative_base_sha256"] == card.meta["normative_base_sha256"]


def test_same_slot_with_changed_source_price_is_not_the_shown_resource(tmp_path):
    path = tmp_path / "norms.sqlite"
    _base(path)
    card = _card(path)
    row = _row(resource_bindings=[{"action": "reuse", "target_resource_ref": "Q1.H1#resource=2",
        "reason": "Источник", "basis_ref": "S!R2"}])
    bound = bind_row_evidence_ids([row], [card])[0]
    resources = copy.deepcopy(card.meta["resources"])
    resources[1]["price"] = 999
    result = resource_binding_position_fields(bound, resources, work_id="W", work_qty=2,
        physical_quantity=2, physical_unit="шт")
    assert result["resources"] == resources
    assert result["resource_binding_conflicts"]


def test_exact_address_reaches_actual_trace_with_duplicate_resources(tmp_path, monkeypatch):
    path = tmp_path / "norms.sqlite"
    _base(path)
    card = _card(path)
    row = _row(resource_bindings=[{"action": "reuse", "target_resource_ref": "Q1.H1#resource=2",
        "reason": "Источник", "basis_ref": "S!R2"}])
    rows = bind_row_evidence_ids([row], [card])
    monkeypatch.setattr(norm_browser, "_base_path", lambda: path)
    monkeypatch.setattr(gesn_service, "get_norm", lambda *_a, **_k: pytest.fail("unpinned read"))
    from proxy.smeta_core import integrity
    monkeypatch.setattr(integrity, "normative_base_integrity", lambda **_k: {"trusted_for_pricing": True})
    trace = build_lsr_trace_from_visible_rows(rows)
    position = trace["sections"][0]["positions"][0]
    assert position["summary"]["resource_binding_conflicts"] == []
    assert position["summary"]["known_amount"] == 20
    assert position["summary"]["resource_binding_audit"][0]["target"]["price"] == 20
