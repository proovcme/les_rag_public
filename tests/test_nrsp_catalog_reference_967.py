"""A shared-catalog reference must never masquerade as its selectable rule ID."""
from copy import deepcopy
import json

from proxy.services import nr_sp_service
from proxy.services.model_lsr_result_contract import model_lsr_result_field_instruction
from proxy.services.model_rag_grouped_evidence_service import lossless_nrsp_body, restore_nrsp_body, share_registry_catalogs


HEADER = "НР/СП: варианты каталога для сборника; выбор модели по условиям объекта, не готовая ставка:"


def _captured_rule():
    # Literal metadata from966 B0 Q1.H1; no inference or applicability assertion.
    return {"rule_id": "nrsp-11", "label": "Полы", "nr_pct": 112.0, "sp_pct": 65.0,
        "basis": "Приказ 812/пр п.11; Приказ 774/пр п.11", "source_ref": "nr_sp_catalog.v1#rule=nrsp-11",
        "source_sha256": {"nr": "28b0b376f110cf6f21975f4bab41f120d661d6b7bf072cb39682a036a72c4e24",
                          "sp": "21f2c34b3cd3af15366f309dbda30a6af88a261c0e4a68edb0cc507a4c9a547d"}}


def _body(rules):
    return "Literal before\n" + "\n".join([HEADER, *[
        f"{rule['rule_id']}: {rule['label']}; НР {rule['nr_pct']}%; СП {rule['sp_pct']}%; {rule['basis']}; источник {rule['source_ref']}"
        for rule in rules]]) + "\nУсловия: дословное ограничение источника."


def test_captured966_catalog_hash_is_labelled_as_reference_not_rule_id():
    rules = [_captured_rule()]
    original = _body(rules)
    factored = lossless_nrsp_body(original, {"nr_sp_candidates": rules})
    assert factored.catalog_id == "nrsp_828d872a913e5845fc33"
    assert f"catalog_ref=[{factored.catalog_id}] (не rule_id)" in factored.content
    assert len(factored.content) <= len(original.replace(factored.catalog_text,
        f"НР/СП: общий буквальный каталог [{factored.catalog_id}]."))
    assert restore_nrsp_body(factored).encode("utf-8") == original.encode("utf-8")


def test_two_rule_shared_catalog_preserves_both_ids_rates_conditions_and_no_choice():
    rules = [_captured_rule(), {**_captured_rule(), "rule_id": "nrsp-fixture-other", "label": "Другие условия",
        "nr_pct": 98.5, "sp_pct": 57.25, "basis": "Буквальное основание второй строки",
        "source_ref": "nr_sp_catalog.v1#rule=nrsp-fixture-other"}]
    original = _body(rules)
    record = {"evidence_ref": "Q1.H1", "content": original, "source_ref": "literal-source"}
    meta = {"Q1.H1": {"nr_sp_candidates": rules}}
    before = deepcopy((record, meta))
    factored = lossless_nrsp_body(original, meta["Q1.H1"])
    catalogs, rows = share_registry_catalogs([record], meta)
    assert f"catalog_ref=[{factored.catalog_id}] (не rule_id)" in rows[0]["content"]
    assert catalogs["literal_nrsp_catalog"] == {factored.catalog_id: factored.catalog_text}
    for rule in rules:
        assert f"{rule['rule_id']}: {rule['label']}; НР {rule['nr_pct']}%; СП {rule['sp_pct']}%; {rule['basis']}; источник {rule['source_ref']}" in factored.catalog_text
    assert "Условия: дословное ограничение источника." in rows[0]["content"]
    assert restore_nrsp_body(factored) == original
    assert (record, meta) == before


def test_field_instruction_requires_literal_inner_rule_id_not_catalog_reference():
    instruction = model_lsr_result_field_instruction()
    assert "nr_sp_rule_id дословно копируй из rule_id внутри каталога" in instruction
    assert "catalog_ref не ID правила" in instruction
    assert "при неизвестных" in instruction


def test_shared_container_hash_is_still_rejected_instead_of_automatically_selecting_a_rule(tmp_path):
    rules = [{**_captured_rule(), "collections": ["ГЭСН:11"]},
             {**_captured_rule(), "rule_id": "nrsp-fixture-other", "collections": ["ГЭСН:11"]}]
    path = tmp_path / "literal-rules.json"
    path.write_text(json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
    ref = lossless_nrsp_body(_body(rules), {"nr_sp_candidates": rules}).catalog_id
    rejected = nr_sp_service.resolve(code="ГЭСН11-01-011-01", rule_id=ref, path=str(path))
    assert rejected["status"] == "rejected"
    assert rejected["nr_pct"] is None and rejected["sp_pct"] is None
    assert [rule["rule_id"] for rule in rejected["candidates"]] == [rule["rule_id"] for rule in rules]
    for rule in rules:
        selected = nr_sp_service.resolve(code="ГЭСН11-01-011-01", rule_id=rule["rule_id"], path=str(path))
        assert selected["status"] == "resolved_explicit" and selected["rule_id"] == rule["rule_id"]
