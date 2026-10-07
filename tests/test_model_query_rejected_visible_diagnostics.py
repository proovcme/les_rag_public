"""Rejected technical query outputs expose bounded, sanitized format evidence."""
from __future__ import annotations

import hashlib
import json

import pytest

from proxy.services import chat_evidence_application_service as application
from proxy.services import model_lsr_result_contract as contract
from tests.test_model_rag_sheet_evidence_reads import _run_sheet


SECRET = "literal-fixture-credential"
PRIVATE = "private-thinking-fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["B0_DIRECT", "B1_CANDIDATE"])
async def test_real_producers_only_snapshot_rejected_sanitized_visible_final(tmp_path, monkeypatch, variant):
    original_deps = application.EvidenceRuntimeDeps

    def deps_with_literal_secret(**kwargs):
        kwargs["llm_runtime"]().api_key = SECRET
        return original_deps(**kwargs)

    monkeypatch.setattr(application, "EvidenceRuntimeDeps", deps_with_literal_secret)
    visible = '{"unexpected":"' + SECRET + ' Bearer bearer-fixture api_key=key-fixture"}'
    rejected = "<think>" + PRIVATE + "</think>\n" + visible
    run = await _run_sheet(tmp_path, monkeypatch, reads=True, variant=variant,
                          query_repair=rejected,
                          query_declaration='{"queries":["S!R2 — Cable A","S!R3 — Cable B"]}')
    outputs = run.result["retrieval_trace"]["model_query_outputs"]
    rejected_output, admitted = outputs[:2]
    saved = rejected_output["rejected_visible_final"]
    sanitized = application.model_query_repair_attempt_data(
        "\n" + visible, finish_reason="stop", parse_diagnostics={}, secret_values=(SECRET,)
    )["assistant_visible_final"]
    assert saved == {"text": sanitized, "sha256": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
                     "chars": len(sanitized), "truncated": False}
    assert rejected_output["declared_parse"]["mechanical_format_errors"] == [
        {"path": "$.queries", "code": "QUERY_LIST_REQUIRED"}]
    assert rejected_output["declared_parse"]["reason_counts"] == {"QUERY_LIST_REQUIRED": 1}
    assert "rejected_visible_final" not in admitted
    assert admitted["declared_parse"]["accepted_count"] == 2
    assert "mechanical_format_errors" not in admitted["declared_parse"]
    repair = run.result["retrieval_trace"]["query_repair_context"][0]
    assert repair["parse_diagnostics"]["mechanical_format_errors"] == rejected_output["declared_parse"]["mechanical_format_errors"]
    frame = "\n".join(str(message["content"]) for message in run.requests[1].messages)
    assert "QUERY_LIST_REQUIRED" in frame and sanitized in frame.replace('\\"', '"').replace('\\n', '\n')
    for forbidden in (SECRET, PRIVATE, "bearer-fixture", "key-fixture"):
        assert forbidden not in json.dumps(outputs, ensure_ascii=False)
        assert forbidden not in frame
    assert len(run.requests) == 5 and len(run.executions) == 1


def test_long_unicode_snapshot_hashes_full_sanitized_visible_text_and_bounds_chars():
    visible = '{"unexpected":"' + "Ω中🙂" * 4000 + ' ' + SECRET + '"}'
    raw = "<think>" + PRIVATE + "</think>" + visible
    diagnostic = application.model_query_output_diagnostics(raw, {"finish_reason": "stop"},
                                                           purpose="fixture", budget={})
    diagnostic["declared_parse"] = {"accepted_count": 0, "output_shape": "unsupported_structured_output"}
    application.add_rejected_query_visible_diagnostics(diagnostic, raw, secret_values=(SECRET,))
    sanitized = visible.replace(SECRET, "[redacted]")
    assert diagnostic["rejected_visible_final"] == {
        "text": sanitized[:8192], "sha256": hashlib.sha256(sanitized.encode("utf-8")).hexdigest(),
        "chars": len(sanitized), "truncated": True}
    assert PRIVATE not in str(diagnostic) and SECRET not in str(diagnostic)


@pytest.mark.parametrize("raw,visible", [
    ('note\n<think>PRIVATE_TEST_SENTINEL</think>\n{"unexpected":1}', 'note\n\n{"unexpected":1}'),
    ('<think mode="test">PRIVATE_TEST_SENTINEL</think>\n{"unexpected":1}', '\n{"unexpected":1}'),
    ('note\n<think>api_key=PRIVATE_TEST_SENTINEL</think>\n{"unexpected":"PUBLIC_VISIBLE_SENTINEL"}',
     'note\n\n{"unexpected":"PUBLIC_VISIBLE_SENTINEL"}'),
])
def test_public_snapshot_removes_all_existing_failure_think_block_forms(raw, visible):
    diagnostic = {"declared_parse": {"accepted_count": 0, "output_shape": "unsupported_structured_output"}}
    application.add_rejected_query_visible_diagnostics(diagnostic, raw)
    assert diagnostic["rejected_visible_final"] == {
        "text": visible, "sha256": hashlib.sha256(visible.encode("utf-8")).hexdigest(),
        "chars": len(visible), "truncated": False}
    assert "PRIVATE_TEST_SENTINEL" not in json.dumps(diagnostic)


@pytest.mark.parametrize("raw,path,code", [
    ('{"queries":"private scalar"}', "$.queries", "QUERY_LIST_REQUIRED"),
    ('{"queries":[{"private":"Bearer secret"}]}', "$.queries[0]", "QUERY_ENTRY_STRING_REQUIRED"),
    ('{"queries":[""]}', "$.queries[0]", "QUERY_ENTRY_NONEMPTY_REQUIRED"),
    ('{"queries":["a\\nb"]}', "$.queries[0]", "QUERY_ENTRY_SINGLE_LINE_REQUIRED"),
    ('{"queries":[],"queries":[]}', "$[0]", "QUERY_JSON_DUPLICATE_FIELD"),
    ('{"private-secret":1,"private-secret":2}', "$[0]", "QUERY_JSON_DUPLICATE_FIELD"),
    ('{"queries":["one"]}\n{"queries":["two"]}', "$", "QUERY_COMMENTARY_DOCUMENT_REQUIRED"),
    ('{"queries":[]}\n{"commentary":"a"}\n{"commentary":"b"}', "$", "QUERY_JSON_DOCUMENT_COUNT"),
    ('{"queries":["unfinished"', "$[0]", "QUERY_JSON_INVALID"),
    ('["private-secret"]', "$", "QUERY_ENVELOPE_OBJECT_REQUIRED"),
    ('{"queries":[],"artifact_kind":"private-secret"}', "$.artifact_kind", "QUERY_ARTIFACT_KIND_INVALID"),
])
def test_schema_diagnostics_use_same_rejection_without_authored_values(raw, path, code):
    assert contract.decode_model_query_envelope(raw) is None
    errors = []
    assert contract.decode_model_query_envelope(raw, format_errors=errors) is None
    assert errors == [{"path": path, "code": code}]
    declared = application.read_model_query_response(raw)
    diagnostic = application.declared_query_output_diagnostics(raw, declared)
    assert declared["queries"] == []
    assert diagnostic["mechanical_format_errors"] == errors
    assert diagnostic["reason_counts"][code] == 1
    assert "private" not in json.dumps(errors) and "Bearer" not in json.dumps(errors)


@pytest.mark.parametrize("raw", [
    '{"queries":["  Literal Ω; 2,5 {a}  ","Repeated","Repeated"]}',
    '{"queries":["one"],"artifact_kind":"lsr","commentary":{"literal":"x"}}',
    '{"queries":["one"],"extra":{"literal":"existing single-envelope field"}}',
    '{"queries":[],"artifact_kind":"vor"}',
    '{"commentary":"side"}\n{"queries":["one"],"artifact_kind":"vor"}',
])
def test_valid_envelope_return_and_queries_are_literal_and_have_no_failure_fields(raw):
    before = contract.decode_model_query_envelope(raw)
    errors = []
    assert contract.decode_model_query_envelope(raw, format_errors=errors) == before
    assert before is not None and errors == []
    declared = application.read_model_query_response(raw)
    diagnostic = application.model_query_output_diagnostics(raw, {"finish_reason": "stop"}, purpose="fixture", budget={})
    diagnostic["declared_parse"] = application.declared_query_output_diagnostics(raw, declared)
    application.add_rejected_query_visible_diagnostics(diagnostic, raw)
    assert "mechanical_format_errors" not in diagnostic["declared_parse"]
    assert "rejected_visible_final" not in diagnostic


@pytest.mark.parametrize("parsed", [
    {"accepted_count": 1, "output_shape": "unsupported_structured_output"},
    {"accepted_count": 0, "output_shape": "declared_lines"},
    {"accepted_count": 0, "output_shape": "empty_final"},
])
def test_visible_snapshot_requires_both_exact_failure_conditions(parsed):
    diagnostic = {"declared_parse": parsed}
    application.add_rejected_query_visible_diagnostics(diagnostic, '{"unexpected":"literal"}')
    assert "rejected_visible_final" not in diagnostic
