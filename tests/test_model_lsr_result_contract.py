import json

import pytest

from proxy.services import model_lsr_result_contract as contract
from proxy.services.lsr_norm_quality_gate_service import lsr_result_table_instruction


@pytest.mark.parametrize("instruction,marker", [
    (contract.model_vor_result_field_instruction, "Поля строки: "),
    (contract.model_lsr_result_field_instruction, "Поля ВОР: "),
    (lsr_result_table_instruction, "КОНТРАКТ ВОР — только при artifact_kind: vor\n"),
])
def test_advertised_vor_fields_include_authored_scope_and_parent_evidence(instruction, marker):
    # The model must be offered structured fields for the justification and
    # relationships required by the same instruction, not only prose after rows.
    fields = instruction().split(marker, 1)[1].split(". ", 1)[0].split(", ")
    assert {"source_row", "row_role", "work_row", "title", "unit", "quantity",
            "open_gap", "coverage", "covered_by_work_id", "evidence_refs"} <= set(fields)


@pytest.mark.parametrize("instruction_factory", [
    contract.model_lsr_result_field_instruction,
    lsr_result_table_instruction,
])
def test_explicit_result_format_overrides_general_presentation_hints(instruction_factory):
    instruction = instruction_factory()

    assert "соблюдай явно заданный пользователем формат" in instruction
    assert 'Без указания формата предпочти компактный JSON {"rows":[...]}; допустимы Markdown или текст' in instruction
    assert "JSON не обязателен" not in instruction


def test_format_choice_precedes_markdown_hints_and_examples_do_not_override_it():
    shared = contract.model_lsr_result_field_instruction()
    instruction = lsr_result_table_instruction()
    examples = contract.model_lsr_result_field_instruction(include_examples=True)

    assert instruction.index(shared) < instruction.index("Если выбран Markdown")
    assert "не разрешение менять явно запрошенный формат" in examples
    assert all(value in examples for value in contract.model_lsr_result_examples().values())


@pytest.mark.parametrize("action,basis", [("add", "explicit"), ("replace", "explicit"),
                                        ("add", "source_work"), ("replace", "target_norm")])
def test_resource_quantity_instruction_matches_the_actual_binding_contract(action, basis):
    from proxy.smeta_core.contracts import ResourceBinding
    binding = ResourceBinding(work_id="source-operation", selected_by="model", action=action,
        resource_name="Literal shown resource", unit="kg", quantity=2,
        quantity_basis=basis, target_resource_code="shown-target")
    instruction = contract.model_lsr_resource_decision_instruction()
    assert binding.quantity_basis in instruction
    assert "target_norm только для replace, source_work только для add" in instruction
    assert "полный физический расход" in instruction


@pytest.mark.parametrize("status", ["keep_all_confirmed", "actions_confirmed", "unresolved"])
def test_resource_review_instruction_exposes_real_review_statuses(status):
    from proxy.smeta_core.contracts import ResourceReview
    review = ResourceReview(work_id="source-operation", selected_by="model", status=status,
        reason="Literal source comparison", labor_status="confirmed", labor_reason="Shown labor",
        machine_status="not_present", material_status="unresolved")
    instruction = contract.model_lsr_resource_decision_instruction()
    assert review.status in instruction
    assert "confirmed/not_present/unresolved/rejected" in instruction
    assert "labor_reason/machine_reason/material_reason" in instruction


def test_selected_norm_facts_are_required_and_not_in_optional_fields():
    instruction = contract.model_lsr_result_field_instruction()
    required_clause = instruction.split("Для каждой выбранной нормы обязательно верни ", 1)[1].split(". ", 1)[0]

    assert all(field in required_clause for field in (*contract.MATCH_FIELDS, "coverage"))
    assert not set(contract.SELECTED_NORM_FIELDS) & set(contract.OPTIONAL_FIELDS)
    assert "resource_code" in instruction and "nr_sp_rule_id" in instruction
    assert "unknown" in instruction and "конкретный вопрос в open_gap" in instruction


def test_all_format_examples_preserve_the_same_authored_fields():
    examples = contract.model_lsr_result_examples()
    json_row = json.loads(examples["json"])["rows"][0]
    table_lines = examples["markdown"].splitlines()
    fields = [value.strip() for value in table_lines[0].strip("|").split("|")]
    values = [value.strip() for value in table_lines[2].strip("|").split("|")]
    table_row = dict(zip(fields, values))
    text_row = dict(line.split(": ", 1) for line in examples["text"].splitlines())

    assert table_row == json_row == text_row
    assert set(contract.BASE_FIELDS + contract.SELECTED_NORM_FIELDS).issubset(json_row)
    assert json_row["nr_sp_rule_id"] == ""
    assert json_row["open_gap"].endswith("?")


def test_result_table_contract_allows_delta_and_ordinary_text_without_weaker_flags():
    shared = contract.model_lsr_result_field_instruction()
    instruction = lsr_result_table_instruction(sheet_clause="SHEET ", remaining_clause=" REMAINING")

    assert shared in instruction
    assert instruction.startswith("SHEET ") and instruction.endswith(" REMAINING")
    assert "допустимы Markdown или текст" in instruction
    assert "Без указания формата" in instruction
    assert "Не выводи JSON" not in instruction
    assert "неизменённые строки prior_model_decisions повторять не обязательно" in instruction
    assert "expected_revision из её revision в prior_model_decisions" in instruction
    assert "или base_revision" in instruction
    assert "Не назначай свои ID и новый revision" in instruction
    assert "набор source_row результата точно равен" not in instruction


def test_format_hints_do_not_contradict_empty_cell_transport_or_force_markdown():
    instruction = lsr_result_table_instruction()

    assert "не перечисляй пустые поля" not in instruction
    assert "Если выбран Markdown" in instruction
    assert "сохраняй пустую ячейку" in instruction
    assert "предпочти компактный JSON" in instruction
    assert "Без указания формата" in instruction
    assert "пояснение пиши в coverage, не вместо признака" in instruction
    assert "Неприменимые поля не выводи" not in instruction
    assert "Не объявляй неприменимые необязательные колонки" in instruction


TRANSPORT_ROW = {"source_row": "Section!R12", "row_role": "work", "title": "Literal authored operation",
    "unit": "m", "quantity": 2.5, "norm_code": "literal-norm", "evidence_refs": ["Q7.H3"],
    "coverage": "Literal field containing artifact_kind: lsr", "condition_match": "unknown",
    "open_gap": "Literal unresolved condition"}


def _supply_match_transport_row(decision="unknown"):
    title = 'Изделие «А» с "кавычками" и е\u0301'
    return {"source_row": "Section with spaces!R12", "row_role": "material",
            "work_row": "Section with spaces!R11", "title": title, "unit": "м", "quantity": 0,
            "norm_code": "", "norm_status": "", "resource_code": "11.22.33.44-0001",
            "evidence_refs": ["Q7.H3"], "coverage": "Literal model decision; no code substitution",
            "supply_resource_match": {"source_title": title, "resource_code": "11.22.33.44-0001",
                "decision": decision, "reason": 'Буквальное основание «А»; источник с "кавычками"',
                "source_refs": ["Q7.H3"]}}


@pytest.mark.parametrize("format_name", ["json", "markdown", "text"])
@pytest.mark.parametrize("decision", ["yes", "no", "unknown"])
def test_supply_resource_match_nested_object_survives_all_result_formats_and_draft(format_name, decision):
    from proxy.services.chat_evidence_application_service import parse_model_rag_result, compact_estimator_draft_rows

    row = _supply_match_transport_row(decision)
    if format_name == "json":
        raw = json.dumps({"artifact_kind": "lsr", "rows": [row]}, ensure_ascii=False)
    else:
        values = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                  for key, value in row.items()}
        if format_name == "markdown":
            raw = ("artifact_kind: lsr\n| " + " | ".join(row) + " |\n| "
                   + " | ".join("---" for _ in row) + " |\n| " + " | ".join(values.values()) + " |")
        else:
            raw = "artifact_kind: lsr\n" + "\n".join(f"{key}: {value}" for key, value in values.items())

    parsed = parse_model_rag_result(raw)

    assert parsed is not None
    actual, = parsed[1]
    assert actual["supply_resource_match"] == row["supply_resource_match"]
    assert actual["resource_code"] == row["resource_code"] and actual["quantity"] == 0
    assert compact_estimator_draft_rows([actual])[0]["supply_resource_match"] == row["supply_resource_match"]


def test_supply_resource_match_instruction_names_its_separate_resource_contract():
    instruction = contract.model_lsr_result_field_instruction()
    assert "supply_resource_match" in instruction
    assert all(field in instruction for field in ("source_title", "resource_code", "decision", "reason", "source_refs"))
    assert "yes/no/unknown" in instruction


@pytest.mark.parametrize("format_name", ["json", "markdown", "text"])
def test_explicit_work_coverage_survives_all_result_formats_and_draft(format_name):
    from proxy.services.chat_evidence_application_service import parse_model_rag_result, compact_estimator_draft_rows
    row = {**TRANSPORT_ROW, "covered_by_work_id": "Section!R11", "norm_code": "-", "norm_status": ""}
    if format_name == "json":
        raw = json.dumps({"rows": [row]})
    elif format_name == "markdown":
        raw = "| " + " | ".join(row) + " |\n| " + " | ".join("---" for _ in row) + " |\n| " + " | ".join(
            json.dumps(v) if isinstance(v, list) else str(v) for v in row.values()) + " |"
    else:
        raw = "\n".join(f"{key}: {json.dumps(value) if isinstance(value, list) else value}" for key, value in row.items())
    parsed = parse_model_rag_result(raw)
    assert parsed is not None
    result = parsed[1]
    assert result[0]["covered_by_work_id"] == "Section!R11"
    assert compact_estimator_draft_rows(result)[0]["covered_by_work_id"] == "Section!R11"


@pytest.mark.parametrize("kind", ["vor", "lsr"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("position", ["before", "after", "outside_fence"])
def test_standalone_artifact_transport_preserves_literal_json_rows(kind, newline, position):
    body = json.dumps({"rows": [TRANSPORT_ROW], "resource_bindings": []}, ensure_ascii=False)
    marker = "\tartifact_kind : " + kind + newline
    if position == "before":
        raw = marker + newline + body
    elif position == "after":
        raw = body + newline + marker
    else:
        raw = marker + "```json" + newline + body + newline + "```"
    diagnostics = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) == [TRANSPORT_ROW]
    assert diagnostics == []
    assert contract.decode_model_artifact_kind(raw)["artifact_kind"] == kind


@pytest.mark.parametrize("marker,status", [
    ("artifact_kind: vor\nartifact_kind: lsr\n", "conflict"),
    ("artifact_kind: vor\nartifact_kind: vor\n", "conflict"),
    ("artifact_kind: unknown\n", "invalid"),
])
def test_invalid_or_repeated_transport_target_does_not_replace_authored_rows(marker, status):
    raw = marker + json.dumps({"rows": [TRANSPORT_ROW]}, ensure_ascii=False)

    assert contract.decode_model_result_rows(raw) == [TRANSPORT_ROW]
    assert contract.decode_model_artifact_kind(raw)["status"] == status
    assert contract.decode_model_artifact_kind(raw)["artifact_kind"] == ""


def test_transport_line_does_not_hide_duplicate_authored_row_or_its_literal_json():
    duplicate = '{"source_row":"Section!R12","row_role":"work","title":"Literal","quantity":1,"quantity":2}'
    raw = 'artifact_kind: vor\n{"rows":[' + duplicate + ']}'
    diagnostics = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics[0]["code"] == "MODEL_RESULT_JSON_DUPLICATE_FIELD"
    assert diagnostics[0]["decision"]["raw_json"] == duplicate
    assert diagnostics[0]["duplicate_fields"][0]["field"] == "quantity"


@pytest.mark.parametrize("raw", [
    'artifact_kind: vor\n{"rows":[',
    '{"rows":[\nartifact_kind: vor\n' + json.dumps(TRANSPORT_ROW) + ']}',
])
def test_incomplete_json_retains_full_original_transport_and_is_not_repaired(raw):
    diagnostics = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics[0]["code"] == "MODEL_RESULT_JSON_INCOMPLETE_RESULT"
    assert diagnostics[0]["decision"]["raw_json"] == raw


@pytest.mark.parametrize("prefix", ["Prose artifact_kind: vor\n", "```json\nartifact_kind: vor\n"])
def test_nonstandalone_or_inside_fence_transport_never_declares_document_kind(prefix):
    raw = prefix + json.dumps({"rows": [TRANSPORT_ROW]}) + ("\n```" if prefix.startswith("```") else "")

    assert contract.decode_model_result_rows(raw) == (None if prefix.startswith("```") else [TRANSPORT_ROW])
    target = contract.decode_model_artifact_kind(raw)
    assert target["status"] == "missing" and target["artifact_kind"] == ""


def test_transport_between_two_results_keeps_ambiguity_and_original_bytes():
    body = json.dumps({"rows": [TRANSPORT_ROW]})
    raw = body + "\nartifact_kind: vor\n" + body
    diagnostics = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert diagnostics[0]["code"] == "MODEL_RESULT_JSON_AMBIGUOUS_RESULTS"
    assert diagnostics[0]["decision"]["raw_json"] == raw


# Installed 933 measured the all-or-nothing reader on a live customer document
# (`artifacts/live_933/installed933_bap_b1/`): the model answered a closed 12-row JSON for a
# 7-locator packet and wrote "conversion_factor":1/100 three times.  The envelope parse failed on
# those tokens, the decoder returned nothing, and the run ended with
# `source_coverage_incomplete:1/20`, `packaging_reason = ARTIFACT_KIND_UNRESOLVED` and no file.

BROKEN_ROW_TEXT = ('{"source_row":"PDF!R21","row_role":"material","title":"Коробка оконечная",'
                   '"unit":"шт","quantity":0.16,"conversion_factor":1/100}')


def _authored_rows_row(source_row, title):
    return {**TRANSPORT_ROW, "source_row": source_row, "title": title}


def test_a_closed_rows_array_keeps_the_rows_that_parse_and_names_the_one_that_does_not():
    first, second = _authored_rows_row("PDF!R18", "First"), _authored_rows_row("PDF!R19", "Second")
    raw = ('{"artifact_kind":"lsr","rows":['
           + json.dumps(first, ensure_ascii=False) + ","
           + json.dumps(second, ensure_ascii=False) + "," + BROKEN_ROW_TEXT + "]}")
    diagnostics: list[dict] = []

    rows = contract.decode_model_result_rows(raw, diagnostics=diagnostics)

    assert [row["source_row"] for row in rows or []] == ["PDF!R18", "PDF!R19"]
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INVALID_ROW"]
    assert diagnostics[0]["reason"] == "unreadable_authored_json_row"
    # the unreadable row is kept as the model's own bytes, not rewritten and not invented
    assert diagnostics[0]["decision"]["raw_json"] == BROKEN_ROW_TEXT
    assert diagnostics[0]["decision"]["source_row"] == "PDF!R21"


def test_a_bare_rows_array_salvages_the_same_way():
    good = _authored_rows_row("PDF!R24", "Work with a readable sibling")
    raw = "[" + json.dumps(good, ensure_ascii=False) + "," + BROKEN_ROW_TEXT + "]"
    diagnostics: list[dict] = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) == [good]
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INVALID_ROW"]


def test_an_unreadable_envelope_member_is_still_refused_as_a_whole_result():
    """Only a row is salvageable; an unreadable envelope means the application cannot know
    what kind of document the model authored, and guessing it would be authoring the answer."""
    raw = ('{"artifact_kind":1/2,"rows":[' + json.dumps(TRANSPORT_ROW, ensure_ascii=False) + "]}")
    diagnostics: list[dict] = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INCOMPLETE_RESULT"]
    assert diagnostics[0]["decision"]["raw_json"] == raw


def test_a_rows_array_without_one_readable_row_is_refused_and_not_repaired():
    raw = '{"artifact_kind":"lsr","rows":[' + BROKEN_ROW_TEXT + "]}"
    diagnostics: list[dict] = []

    assert contract.decode_model_result_rows(raw, diagnostics=diagnostics) is None
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INCOMPLETE_RESULT"]


@pytest.mark.parametrize("unfinished", [
    '{"artifact_kind":"lsr","rows":[{"source_row":"PDF!R18","title":"Cut',
    '{"artifact_kind":"lsr","rows":[{"source_row":"PDF!R18","title":"Whole"},',
    '{"artifact_kind":"lsr","rows":[{"source_row":"PDF!R18","title":"Bad":1}',
])
def test_salvage_never_resurrects_an_unfinished_answer(unfinished):
    """A cut-off document is a different fact from a badly-valued row, and it stays refused."""
    diagnostics: list[dict] = []

    assert contract.decode_model_result_rows(unfinished, diagnostics=diagnostics) is None
    assert [item["code"] for item in diagnostics] == ["MODEL_RESULT_JSON_INCOMPLETE_RESULT"]
    assert diagnostics[0]["decision"]["raw_json"] == unfinished
