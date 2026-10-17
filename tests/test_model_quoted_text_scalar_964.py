"""Literal quoted text records use the same model-owned rows as JSON.

No selection of work, parent, quantity or norm is performed by this transport.
The installed963 failure used this representation for sixteen explicit records.
"""
import json

import pytest

from proxy.services.chat_evidence_application_service import parse_model_rag_result, profile_system_prompt
from proxy.services.model_lsr_result_contract import (
    decode_model_artifact_kind, decode_model_quoted_text_scalar,
)
from proxy.services.prompt_registry_service import build_factory_mode_system_prompt


def test_named_multiline_quoted_records_keep_every_authored_decision_and_raw_answer():
    raw = '''artifact_kind: "vor"
rows:
  - source_row: "Sheet with spaces!R2"
    row_role: "work"
    work_row: "Sheet with spaces!R2"
    title: "Literal work, layer 150 mm | colour unchanged"
    unit: "м 2"
    quantity: 23,6
    open_gap: ""
  - source_row: "Sheet with spaces!R3"
    row_role: "material"
    work_row: "Sheet with spaces!R2"
    title: "Literal component"
    unit: "м 2"
    quantity: 23,6
    open_gap: "Do not guess missing conditions"
    covered_by_work_id: "author_supplied_id"
  - source_row: "Sheet with spaces!R4"
    row_role: "work"
    work_row: "Sheet with spaces!R4"
    title: "Explicit zero"
    unit: "шт"
    quantity: 0
    open_gap: ""
'''
    diagnostics = []
    answer, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert answer == raw and diagnostics == []
    assert rows == [
        {"source_row": "Sheet with spaces!R2", "row_role": "work", "work_row": "Sheet with spaces!R2",
         "title": "Literal work, layer 150 mm | colour unchanged", "unit": "м 2", "quantity": 23.6, "open_gap": ""},
        {"source_row": "Sheet with spaces!R3", "row_role": "material", "work_row": "Sheet with spaces!R2",
         "title": "Literal component", "unit": "м 2", "quantity": 23.6,
         "open_gap": "Do not guess missing conditions", "covered_by_work_id": "author_supplied_id"},
        {"source_row": "Sheet with spaces!R4", "row_role": "work", "work_row": "Sheet with spaces!R4",
         "title": "Explicit zero", "unit": "шт", "quantity": 0, "open_gap": ""},
    ]


@pytest.mark.parametrize("value", ["", "null", "false", "0", "23,6", "19\" rack", "'vor'", '"unfinished', '["vor"]', '{"kind":"vor"}', '"vor" trailing'])
def test_text_scalar_does_not_interpret_non_string_or_incomplete_syntax(value):
    assert decode_model_quoted_text_scalar(value) == value


@pytest.mark.parametrize("value", ["", "null", "false", "19\" rack | type", "line\nnext", "с кавычками и пробелами"])
def test_only_explicit_json_string_quotes_are_decoded(value):
    assert decode_model_quoted_text_scalar(json.dumps(value, ensure_ascii=False)) == value


@pytest.mark.parametrize("kind", ["vor", "lsr"])
def test_one_quoted_target_has_same_authority_and_duplicate_protection(kind):
    declaration = decode_model_artifact_kind(f'artifact_kind: "{kind}"')
    assert declaration["status"] == "declared" and declaration["artifact_kind"] == kind
    repeated = decode_model_artifact_kind(f'artifact_kind: "{kind}"\nartifact_kind: {kind}')
    assert repeated["status"] == "conflict" and not repeated["artifact_kind"]
    opposite = "lsr" if kind == "vor" else "vor"
    conflicting = decode_model_artifact_kind(f'artifact_kind: "{kind}"\n' + json.dumps({"artifact_kind": opposite, "rows": []}))
    assert conflicting["status"] == "conflict"


def test_ordinary_format_guidance_does_not_forbid_active_document_contract():
    prompt = build_factory_mode_system_prompt("rag")
    assert "Для обычного ответа не используй JSON без запроса пользователя" in prompt
    assert "не запрещает JSON или вызов инструмента" in prompt
    assert "Формат строк создаваемого документа определяется его активным контрактом" in prompt
    assert "без внутренних служебных терминов и JSON, если JSON не просили" not in prompt


def test_historical_bound_prompt_is_preserved_with_phase_specific_format_clarification():
    original = "Literal saved custom profile: без JSON, если JSON не просили."
    snapshot = {"prompt_text": original, "skill_text": "Literal skill"}
    result = profile_system_prompt(snapshot, strict=False, purpose="workbook_result", artifact_kind="vor")
    assert result.startswith(original + "\n\n")
    assert "Формат документа важнее общих правил стиля" in result
    assert "Карты не доказательства" in result
    assert snapshot == {"prompt_text": original, "skill_text": "Literal skill"}
    ordinary = profile_system_prompt(snapshot, strict=False, purpose="source_read")
    assert ordinary.startswith(original + "\n\n")
    assert "Формат документа важнее общих правил стиля" not in ordinary


def test_duplicate_named_text_fields_stay_raw_proposals_and_valid_sibling_survives():
    raw = '''artifact_kind: "vor"
- source_row: "A!R2"
  row_role: "material"
  title: "Literal bad proposal"
  unit: "м"
  quantity: 2
  row_role: "work"
- source_row: "A!R3"
  row_role: "work"
  title: "Literal valid work"
  unit: "м"
  quantity: 0
'''
    diagnostics = []
    answer, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert answer == raw
    assert rows == [{"source_row": "A!R3", "row_role": "work", "title": "Literal valid work", "unit": "м", "quantity": 0}]
    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "MODEL_RESULT_TEXT_DUPLICATE_FIELD"
    assert diagnostics[0]["fields"] == ["row_role"]
    assert 'row_role: "material"' in diagnostics[0]["decision"]["raw_block"]
    assert 'row_role: "work"' in diagnostics[0]["decision"]["raw_block"]


def test_multiline_one_source_can_still_author_multiple_distinct_operations():
    rows = [{"source_row": "A!R2", "row_role": role, "title": title, "unit": "шт", "quantity": 1}
            for role, title in (("work", "Literal operation"), ("material", "Literal supply"))]
    raw = 'artifact_kind: "vor"\n' + "\n".join(
        "\n".join(("- " if index == 0 else "  ") + key + ": " + json.dumps(value, ensure_ascii=False)
                  for index, (key, value) in enumerate(row.items())) for row in rows)
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, rows)
    assert diagnostics == []


@pytest.mark.parametrize("presentation", ["markdown", "block"])
def test_explicit_nullable_text_fields_match_json_without_fake_links_or_questions(presentation):
    row = {"source_row": "A!R2", "row_role": "work", "title": "Literal operation",
           "work_row": None, "unit": None, "quantity": None, "open_gap": None}
    values = {key: "null" if value is None else value for key, value in row.items()}
    if presentation == "markdown":
        raw = 'artifact_kind: vor\n| ' + " | ".join(values) + " |\n| " + " | ".join("---" for _ in values) + " |\n| " + " | ".join(values.values()) + " |"
    else:
        raw = 'artifact_kind: "vor"\n' + "\n".join(key + ": " + value for key, value in values.items())
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [row])
    assert diagnostics == []
    json_result = parse_model_rag_result(json.dumps({"artifact_kind": "vor", "rows": [row]}))
    assert json_result[1] == [row]


def test_json_quoted_null_is_literal_and_cannot_hide_a_question_or_relabel_work():
    raw = '''artifact_kind: "vor"
source_row: "A!R2"
row_role: "work"
title: "null"
unit: "м"
quantity: 0
work_row: "null"
open_gap: "null"
'''
    row = parse_model_rag_result(raw)[1][0]
    assert row["title"] == row["work_row"] == row["open_gap"] == "null"
    assert row["quantity"] == 0 and row["row_role"] == "work"


@pytest.mark.parametrize("field,first,second", [
    ("norm_code", '""', '"AuthorSelectedNorm"'),
    ("quantity", "-", "7"),
    ("evidence_refs", '""', '"Q1.H1"'),
    ("open_gap", "null", '"Literal question"'),
])
def test_duplicate_labels_are_detected_even_when_first_value_is_absent(field, first, second):
    raw = ('artifact_kind: "vor"\nsource_row: "A!R2"\nrow_role: "work"\ntitle: "Literal"\nunit: "м"\n'
           + ("" if field == "quantity" else "quantity: 1\n") + field + ": " + first + "\n" + field + ": " + second)
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, [])
    assert diagnostics[0]["fields"] == [field]
    assert first in diagnostics[0]["decision"]["raw_block"] and second in diagnostics[0]["decision"]["raw_block"]


def test_explicit_empty_norm_in_lsr_text_preserves_unpriced_work_instead_of_losing_row():
    raw = '''artifact_kind: "lsr"
source_row: "A!R2"
row_role: "work"
title: "Literal work awaiting a norm"
unit: "м"
quantity: 12
norm_code: ""
open_gap: "Applicable norm not found"
'''
    diagnostics = []
    answer, rows = parse_model_rag_result(raw, diagnostics=diagnostics)
    assert answer == raw and diagnostics == []
    assert rows == [{"source_row": "A!R2", "row_role": "work", "title": "Literal work awaiting a norm",
                     "unit": "м", "quantity": 12, "norm_code": "", "open_gap": "Applicable norm not found"}]


def test_explicit_new_list_record_keeps_both_prior_operation_ids_and_revisions():
    rows = [{"operation_id": operation, "expected_revision": revision, "source_row": "A!R2",
             "row_role": role, "title": title, "unit": "шт", "quantity": 1}
            for operation, revision, role, title in (("first", 2, "work", "Literal operation"),
                                                    ("second", 3, "material", "Literal supply"))]
    raw = 'artifact_kind: "vor"\n' + "\n".join(
        "\n".join(("- " if index == 0 else "  ") + key + ": " + json.dumps(value)
                  for index, (key, value) in enumerate(row.items())) for row in rows)
    diagnostics = []
    assert parse_model_rag_result(raw, diagnostics=diagnostics) == (raw, rows)
    assert diagnostics == []
