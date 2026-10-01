"""No model-authored row or resource action is lost to presentation changes."""
import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service


def authored_row():
    return {
        "source_row": "Лист источника!R7", "row_role": "work",
        "work_row": "Лист источника!R7", "title": "Монтаж с повторным использованием",
        "unit": "м2", "quantity": 15, "norm_code": "ГЭСН15-01-047-16",
        "evidence_refs": ["Q1.H1"],
        "resource_bindings": [{"action": "reuse", "target_resource_code": "MAT-1",
            "reason": "Повторное использование; unit=м2, quantity=15 по источнику",
            "basis_ref": "Лист источника!R7", "source_refs": ["Q1.H1"]}],
        "resource_review": {"status": "actions_confirmed", "reason": "Проверен состав"},
    }


def format_row(row, format_name):
    if format_name == "json":
        return json.dumps({"rows": [row]}, ensure_ascii=False)
    values = {key: (json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict))
                    else str(value)) for key, value in row.items()}
    if format_name == "markdown":
        return "\n".join(("| " + " | ".join(values) + " |",
                          "| " + " | ".join("---" for _ in values) + " |",
                          "| " + " | ".join(values.values()) + " |"))
    if format_name == "inline":
        return ", ".join(f"{key}={value}" for key, value in values.items())
    return "\n".join(f"{key}: {value}" for key, value in values.items())


@pytest.mark.parametrize("role", ["work", "material", "equipment", "resource", "header", "unresolved"])
def test_complete_json_keeps_authored_role_with_absent_blank_fields(role):
    row = {"source_row": "Другое имя!R77", "title": "Авторская строка", "row_role": role}
    raw = json.dumps({"rows": [row]}, ensure_ascii=False)
    assert service.parse_model_rag_result(raw) == (raw, [row])
    assert set(row) == {"source_row", "title", "row_role"}


@pytest.mark.parametrize("extra", [
    '"norm_code":"01-02-003-04","norm_code":"01-02-003-05"',
    '"norm_code":"01-02-003-04","resource_bindings":[{"action":"exclude","action":"reuse"}]',
    '"norm_code":"01-02-003-04","Наименование":"Вторая работа"',
])
def test_duplicate_json_keys_or_aliases_do_not_silently_select_last_value(extra):
    raw = '{"rows":[{"source_row":"S!R7","title":"Первая работа","unit":"м",' + extra + '}]}'
    assert service.parse_model_rag_result(raw) is None


@pytest.mark.parametrize("format_name", ["json", "markdown", "inline", "block"])
def test_authored_resource_actions_survive_all_formats_and_replay(format_name):
    row = authored_row()
    original = copy.deepcopy(row)
    answer = format_row(row, format_name)
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None and parsed[0] == answer
    assert len(parsed[1]) == 1
    result = parsed[1][0]
    for key in ("resource_bindings", "resource_review"):
        assert result[key] == original[key]
        assert service.compact_estimator_draft_rows([result])[0][key] == original[key]
    assert row == original


@pytest.mark.parametrize("wrapper", ["array", "object", "fenced_array", "fenced_object"])
def test_complete_json_rows_are_accepted_with_explanatory_prose(wrapper):
    row = authored_row()
    value = [row] if "array" in wrapper else {"rows": [row]}
    answer = json.dumps(value, ensure_ascii=False)
    if wrapper.startswith("fenced"):
        answer = "Результат по исходнику:\n```json\n" + answer + "\n```\nОткрытые вопросы перечислены в строках."
    parsed = service.parse_model_rag_result(answer)
    assert parsed is not None and parsed[0] == answer
    assert parsed[1] == [row]


def test_two_complete_fenced_results_are_not_arbitrarily_chosen():
    row = authored_row()
    block = "```json\n" + json.dumps([row], ensure_ascii=False) + "\n```"
    parsed = service.parse_model_rag_result(block + "\n" + block)
    assert parsed is None or parsed[1] == []


def test_truncated_json_array_is_not_repaired():
    parsed = service.parse_model_rag_result(json.dumps([authored_row()], ensure_ascii=False)[:-2])
    assert parsed is None or parsed[1] == []


@pytest.mark.parametrize("format_name", ["json", "markdown", "block"])
def test_malformed_resource_values_are_preserved_for_visible_validation(format_name):
    row = authored_row()
    row["resource_bindings"] = "[{broken JSON"
    parsed = service.parse_model_rag_result(format_row(row, format_name))
    assert parsed[1][0]["resource_bindings"] == "[{broken JSON"


def test_nested_values_cannot_author_application_trust_flags():
    row = authored_row()
    row["_resource_binding_evidence_checks"] = [{"price_in_refs": True}]
    row["_resource_binding_evidence_bindings"] = {"0": {"Q1.H1": "invented"}}
    result = service.parse_model_rag_result(json.dumps({"rows": [row]}, ensure_ascii=False))[1][0]
    assert "_resource_binding_evidence_checks" not in result
    assert "_resource_binding_evidence_bindings" not in result


def evidence(ref, identity, body, *, name="Норма", **meta):
    return SimpleNamespace(content=body, doc_name=name, meta={
        "model_evidence_ref": ref, "global_evidence_id": identity, **meta})


def test_resource_refs_are_resolved_without_replacing_norm_citations():
    row = authored_row()
    row["resource_bindings"][0]["source_refs"] = ["Q2.H1"]
    norm = evidence("Q1.H1", "norm-card", "Шифр: ГЭСН15-01-047-16\nРесурс MAT-1")
    resource = evidence("Q2.H1", "resource-card", "Ресурс MAT-1, м2")
    result = service.bind_row_evidence_ids([row], [norm, resource])[0]
    assert result["evidence_refs"] == ["Q1.H1"]
    assert result["evidence_bindings"] == {"Q1.H1": "norm-card"}
    assert result["_evidence_check"]["code_not_in_refs"] is False
    assert result["_resource_binding_evidence_bindings"] == {"0": {"Q2.H1": "resource-card"}}
    assert result["_resource_binding_evidence_checks"][0]["target_code_in_refs"] is True
    assert result["resource_bindings"] == row["resource_bindings"]
    assert service.compact_estimator_draft_rows([result])[0]["_resource_binding_evidence_bindings"] == result["_resource_binding_evidence_bindings"]


def test_resource_action_durable_reference_survives_colliding_packet_alias():
    row = authored_row()
    row["resource_bindings"][0]["source_refs"] = ["Q2.H1"]
    row["_resource_binding_evidence_bindings"] = {"0": {"Q2.H1": "old-resource"}}
    old = evidence("Q2.H1", "old-resource", "Ресурс MAT-1")
    new = evidence("Q2.H1", "new-resource", "Другой ресурс MAT-2")
    result = service.bind_row_evidence_ids([row], [new, old])[0]
    check = result["_resource_binding_evidence_checks"][0]
    assert check["evidence_bindings"] == {"Q2.H1": "old-resource"}
    assert check["target_code_in_refs"] is True
    assert check["unresolved_refs"] == []


def test_resource_action_price_requires_amount_unit_and_source_in_one_quote():
    row = authored_row()
    row["resource_bindings"] = [{"action": "add", "resource_name": "Ресурс",
        "resource_code": "MAT-2", "quantity": 5, "unit": "м2", "explicit_price": 12,
        "price_source_ref": "КП", "reason": "Выбранная поставка", "source_refs": ["Q2.H1", "Q2.H2"]}]
    chunks = [evidence("Q2.H1", "quote-amount", "MAT-2 цена 12 за шт", name="КП"),
              evidence("Q2.H2", "quote-unit", "MAT-2 цена 99 за м2", name="Другой КП")]
    check = service.bind_row_evidence_ids([row], chunks)[0]["_resource_binding_evidence_checks"][0]
    assert not all(check[key] for key in ("price_in_refs", "unit_in_refs", "source_in_refs"))
    quoted = evidence("Q2.H3", "quote-all", "MAT-2 цена 12 за м2", name="КП")
    row["resource_bindings"][0]["source_refs"] = ["Q2.H3"]
    check = service.bind_row_evidence_ids([row], [quoted])[0]["_resource_binding_evidence_checks"][0]
    assert all(check[key] for key in ("price_in_refs", "unit_in_refs", "source_in_refs"))


@pytest.mark.parametrize("explicit_price", [None, 0])
def test_reuse_source_identity_does_not_require_a_market_zero_quote(explicit_price):
    row = authored_row()
    action = {"action": "reuse", "target_resource_code": "MAT-1", "reason": "Повторное использование",
              "source_refs": ["Q2.H1"], "price_source_ref": "Исходный проект"}
    if explicit_price is not None:
        action["explicit_price"] = explicit_price
    row["resource_bindings"] = [action]
    chunks = [evidence("Q2.H1", "project", "MAT-1 сохранить для повторного монтажа", name="Исходный проект")]
    result = service.bind_row_evidence_ids([row], chunks)[0]
    assert result["_resource_binding_evidence_checks"][0]["source_in_refs"] is True
    action["price_source_ref"] = "Другой документ"
    result = service.bind_row_evidence_ids([row], chunks)[0]
    assert result["_resource_binding_evidence_checks"][0]["source_in_refs"] is False


def test_nested_cited_card_replayed_and_checks_stay_out_of_model_authored_rows():
    row = authored_row()
    row["resource_bindings"][0]["source_refs"] = ["Q2.H1"]
    norm = evidence("Q1.H1", "norm-card", "Шифр: ГЭСН15-01-047-16\nMAT-1")
    resource = evidence("Q2.H1", "resource-card", "MAT-1")
    for chunk in (norm, resource):
        chunk.doc_id = chunk.meta["global_evidence_id"]
    bound = service.bind_row_evidence_ids([row], [norm, resource])
    context, retained = service.model_rag_prior_page_context(bound, [norm, resource])
    assert {chunk.meta["global_evidence_id"] for chunk in retained} == {"norm-card", "resource-card"}
    prior = context["prior_model_decisions"][0]
    assert prior["resource_bindings"] == row["resource_bindings"]
    assert "_resource_binding_evidence_checks" not in prior


def test_found_pointer_is_not_proof_of_a_read_full_card():
    from proxy.services.lsr_norm_quality_gate_service import applicability_gap_kind, norm_applicability_substantiated
    row = authored_row()
    row["norm_status"] = "EXACT"
    for key in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers"):
        row[key] = "yes"
    pointer = evidence("Q1.H1", "norm", "Шифр: ГЭСН15-01-047-16\nКарточка отложена")
    pointer.meta.update(norm_code=row["norm_code"], source_ref="База", edition="2022")
    pointer.meta["body_status"] = "deferred_capacity"
    result = service.bind_row_evidence_ids([row], [pointer])[0]
    assert result["norm_code"] == row["norm_code"] and result["norm_status"] == "EXACT"
    assert result["_evidence_check"]["card_body_shown"] is False
    assert applicability_gap_kind(result) == "norm_card_body_unread"
    assert norm_applicability_substantiated(result) is False
    full = evidence("Q2.H1", "norm", "Шифр: ГЭСН15-01-047-16\nПолный состав MAT-1")
    full.meta.update(norm_code=row["norm_code"], source_ref="База", edition="2022")
    full.meta["body_status"] = "full"
    row["evidence_refs"] = ["Q2.H1", "Q1.H1"]
    result = service.bind_row_evidence_ids([row], [full, pointer])[0]
    assert norm_applicability_substantiated(result) is True
    assert result["_resource_binding_evidence_checks"][0]["target_code_in_refs"] is True


def test_production_inventory_pointer_uses_its_literal_norm_identity_without_body_proof():
    from proxy.services.model_rag_grouped_evidence_service import EvidenceCard, inventory_pointer
    from proxy.services.lsr_norm_quality_gate_service import applicability_gap_kind
    row = authored_row()
    row.update(norm_status="EXACT", evidence_refs=["Q1.H1"])
    for key in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers"):
        row[key] = "yes"
    meta = {"norm_key": "ГЭСН:15-01-047-16", "norm_code": row["norm_code"],
            "source_ref": "База", "edition": "2022", "body_status": "deferred_capacity"}
    pointer_body = inventory_pointer(EvidenceCard("Q1.H1", "norm", "identity", "raw", meta))
    pointer = evidence("Q1.H1", "pointer", pointer_body, name="smeta_norm_cards.v1")
    pointer.meta.update(meta)
    result = service.bind_row_evidence_ids([row], [pointer])[0]
    assert result["_evidence_check"]["cited_ciphers"] == [row["norm_code"]]
    assert result["_evidence_check"]["card_body_shown"] is False
    assert applicability_gap_kind(result) == "norm_card_body_unread"
    assert result["norm_code"] == row["norm_code"]


def test_exact_read_json_body_preserves_its_shown_cipher_and_discharges_same_pointer():
    from proxy.services.model_rag_grouped_evidence_service import EvidenceCard, inventory_pointer
    from proxy.services.lsr_norm_quality_gate_service import norm_applicability_substantiated
    row = authored_row()
    row.update(norm_status="EXACT", evidence_refs=["Q1.H1", "Q2.H1"])
    for key in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers"):
        row[key] = "yes"
    meta = {"norm_key": "ГЭСН:15-01-047-16", "norm_code": row["norm_code"],
            "source_ref": "База", "edition": "2022"}
    pointer_body = inventory_pointer(EvidenceCard("Q1.H1", "norm", "identity", "raw", meta))
    pointer = evidence("Q1.H1", "pointer", pointer_body, name="smeta_norm_cards.v1")
    pointer.meta.update(meta, body_status="deferred_capacity")
    full = evidence("Q2.H1", "exact-read", json.dumps(meta, ensure_ascii=False), name="smeta_norm_cards.v1")
    full.meta.update(meta, body_status="full", exact_card_read=True)
    result = service.bind_row_evidence_ids([row], [pointer, full])[0]
    assert set(result["_evidence_check"]["cited_ciphers"]) == {row["norm_code"]}
    assert result["_evidence_check"]["card_body_shown"] is True
    assert norm_applicability_substantiated(result) is True


@pytest.mark.parametrize("shown", ["Служебное описание без шифра", "ГЭСН15-01-047-160"])
def test_hidden_metadata_cipher_does_not_prove_a_shown_norm(shown):
    row = authored_row()
    row.update(norm_status="EXACT", evidence_refs=["Q1.H1"])
    pointer = evidence("Q1.H1", "pointer", shown, name="smeta_norm_cards.v1")
    pointer.meta.update(body_status="deferred_capacity", norm_code=row["norm_code"])
    result = service.bind_row_evidence_ids([row], [pointer])[0]
    assert row["norm_code"] not in result["_evidence_check"]["cited_ciphers"]
    assert result["norm_code"] == row["norm_code"]


@pytest.mark.parametrize("difference", ["parent_cipher", "source_ref", "edition"])
def test_other_full_card_cannot_prove_a_deferred_exact_item(difference):
    row = authored_row()
    row.update(norm_status="EXACT", evidence_refs=["Q1.H1", "Q2.H1"])
    pointer = evidence("Q1.H1", "pointer", "Шифр: " + row["norm_code"])
    pointer.meta.update(body_status="deferred_capacity", norm_code=row["norm_code"], source_ref="База", edition="2022")
    full = evidence("Q2.H1", "other", "Шифр: " + row["norm_code"])
    full.meta.update(body_status="full", norm_code=row["norm_code"], source_ref="База", edition="2022")
    if difference == "parent_cipher":
        full.meta["norm_code"] = "ГЭСН15-01-047"
        full.content = "Шифр: ГЭСН15-01-047\nТаблица раздела"
    else:
        full.meta[difference] = "Другой источник"
    result = service.bind_row_evidence_ids([row], [pointer, full])[0]
    assert result["_evidence_check"]["card_body_shown"] is False
    assert result["norm_code"] == row["norm_code"]


@pytest.mark.parametrize("extra_kind", ["other_norm", "document"])
def test_unrelated_deferred_reference_does_not_hide_delivered_selected_norm(extra_kind):
    from proxy.services.lsr_norm_quality_gate_service import norm_applicability_substantiated
    row = authored_row()
    row.update(norm_status="EXACT", evidence_refs=["Q1.H1", "Q2.H1"])
    for key in ("action_match", "object_match", "condition_match", "unit_compatible", "composition_covers"):
        row[key] = "yes"
    full = evidence("Q1.H1", "selected", "Шифр: " + row["norm_code"] + "\nСостав MAT-1")
    full.meta.update(body_status="full", norm_code=row["norm_code"], source_ref="База", edition="2022")
    extra = evidence("Q2.H1", "other", "Дополнительное основание")
    extra.meta["body_status"] = "deferred_capacity"
    if extra_kind == "other_norm":
        extra.meta["norm_code"] = "ГЭСН15-01-047-17"
        extra.content = "Шифр: ГЭСН15-01-047-17"
    result = service.bind_row_evidence_ids([row], [full, extra])[0]
    assert result["_evidence_check"].get("card_body_shown") is not False
    assert norm_applicability_substantiated(result) is True
    assert result["norm_code"] == row["norm_code"]


def test_excluded_and_reused_actions_remain_visible_in_delivered_check_sheet(tmp_path):
    import openpyxl
    from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
    actions = [
        {"action": "exclude", "target_resource_code": "MAT-1", "reason": "Поставка уже учтена",
         "source_refs": ["Q1.H1"]},
        {"action": "reuse", "target_resource_name": "Сохранённый материал", "reason": "Повторный монтаж",
         "basis_ref": "Исходник!R7"},
    ]
    lsr = {"name": "Контроль действий", "summary": {}, "sections": [],
           "row_bindings": [{"row": "Исходник!R7", "resource_binding_audit": [
               {"proposal": action, "status": "applied"} for action in actions]}]}
    output = render_lsr_xlsx(lsr, tmp_path / "resource-audit.xlsx")
    wb = openpyxl.load_workbook(output)
    try:
        note = wb["Проверка"].cell(2, 12).value
        assert "исключить MAT-1 — применено" in note
        assert "повторно использовать Сохранённый материал — применено" in note
        assert "Поставка уже учтена" in note and "Q1.H1" in note
        assert "Повторный монтаж" in note and "Исходник!R7" in note
    finally:
        wb.close()
