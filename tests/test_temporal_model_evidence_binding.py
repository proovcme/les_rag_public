"""A later frame cannot retrospectively supply evidence for an earlier decision."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from proxy.services import chat_evidence_application_service as service


_SELECTED = "ГЭСН01-01-001-01"
_OTHER = "ГЭСН01-01-001-02"


def _card(ref, identity, code, *, condition="current frame"):
    return SimpleNamespace(
        content=f"Шифр: {code}\nУсловия: {condition}", doc_name="shown cards", score=1.0,
        meta={"model_evidence_ref": ref, "global_evidence_id": identity,
              "norm_code": code, "model_query_text": condition,
              "model_delivery_status": "delivered", "body_status": "full"},
    )


def _authored(*, known_ref=False):
    return {
        "source_row": "S!R2", "row_role": "work", "title": "Model-owned operation",
        "unit": "м", "quantity": 1, "norm_code": _SELECTED, "norm_status": "EXACT",
        "evidence_refs": (["Q1.H1"] if known_ref else []) + ["Q2.H1"],
    }


def _durable(row):
    return json.loads(json.dumps(row, ensure_ascii=False))


def _unchanged_model_decision(before, after):
    for key in ("source_row", "row_role", "title", "unit", "quantity", "norm_code", "norm_status", "evidence_refs"):
        assert (key in after) == (key in before)
        assert after.get(key) == before.get(key)


@pytest.mark.parametrize("known_ref", [False, True])
def test_unissued_ref_remains_unissued_when_a_later_frame_allocates_the_same_handle(known_ref):
    authored = _authored(known_ref=known_ref)
    before = deepcopy(authored)
    early = _card("Q1.H1", "early-card", _OTHER)
    late = _card("Q2.H1", "future-card", _SELECTED, condition="future frame")
    saved = _durable(service.bind_row_evidence_ids([authored], [early])[0])
    expected = {"Q1.H1": "early-card"} if known_ref else {}
    assert saved["evidence_bindings"] == expected
    assert saved["_evidence_check"]["unresolved_refs"] == ["Q2.H1"]
    saved_before = deepcopy(saved)

    replayed = service.bind_row_evidence_ids([saved], [early, late])[0]

    assert replayed["evidence_bindings"] == expected
    assert replayed["_evidence_check"]["unresolved_refs"] == ["Q2.H1"]
    assert "future-card" not in replayed["evidence_bindings"].values()
    assert saved == saved_before and authored == before
    _unchanged_model_decision(before, replayed)


def test_final_structure_validation_does_not_resolve_an_early_gap_against_future_alias():
    authored = _authored()
    saved = _durable(service.bind_row_evidence_ids([authored], [
        _card("Q1.H1", "early-card", _OTHER),
    ])[0])
    late = _card("Q2.H1", "future-card", _SELECTED, condition="future frame")

    errors = service.validate_model_rag_result_structure([saved], [late], expected_source_rows=1)

    assert "unknown_evidence_ref:Q2.H1" in errors
    assert saved["evidence_bindings"] == {}
    _unchanged_model_decision(authored, saved)


def test_prior_page_structural_facts_do_not_claim_a_future_card_was_cited():
    authored = _authored()
    saved = _durable(service.bind_row_evidence_ids([authored], [
        _card("Q1.H1", "early-card", _OTHER),
    ])[0])
    before = deepcopy(saved)

    prior, retained = service.model_rag_prior_page_context([saved], [
        _card("Q2.H1", "future-card", _SELECTED, condition="future frame"),
    ])

    fact = prior["prior_result_structural_facts"][0]["norm_reference"]
    assert fact["unresolved_refs"] == ["Q2.H1"]
    assert fact["code_in_refs"] is None and fact["cited_ciphers"] == []
    assert retained == [] and prior["previously_shown_cited_evidence"] == []
    assert saved == before
    _unchanged_model_decision(authored, prior["prior_model_decisions"][0])


def test_saved_global_identity_survives_later_handle_collision():
    authored = _authored()
    original = _card("Q2.H1", "original-card", _SELECTED, condition="original conditions")
    saved = _durable(service.bind_row_evidence_ids([authored], [original])[0])
    later = _card("Q2.H1", "different-card", _OTHER, condition="different future conditions")
    before = deepcopy(saved)

    replayed = service.bind_row_evidence_ids([saved], [later, original])[0]
    prior, retained = service.model_rag_prior_page_context([saved], [later, original])

    assert replayed["evidence_bindings"] == {"Q2.H1": "original-card"}
    assert replayed["_evidence_check"]["cited_ciphers"] == [_SELECTED]
    assert replayed["_evidence_check"]["unresolved_refs"] == []
    assert [item.meta["global_evidence_id"] for item in retained] == ["original-card"]
    assert prior["prior_result_structural_facts"][0]["norm_reference"]["code_in_refs"] is True
    assert saved == before
    _unchanged_model_decision(authored, replayed)


def test_newly_authored_decision_can_first_bind_the_handle_shown_in_its_own_frame():
    authored = {**_authored(), "source_row": "S!R3"}
    before = deepcopy(authored)
    current = _card("Q2.H1", "current-card", _SELECTED)

    bound = service.bind_row_evidence_ids([authored], [current])[0]

    assert bound["evidence_bindings"] == {"Q2.H1": "current-card"}
    assert bound["_evidence_check"]["unresolved_refs"] == []
    assert bound["_evidence_check"]["citation_checkable"] is True
    assert bound["_evidence_check"]["code_not_in_refs"] is False
    assert authored == before
    _unchanged_model_decision(before, bound)


def test_explicit_first_bind_ignores_model_debug_maps_and_binds_the_whole_shown_frame_once():
    authored = {
        **_authored(known_ref=True), "evidence_bindings": {"Q2.H1": "forged-card"},
        "_resource_binding_evidence_bindings": {"0": {"Q2.H1": "forged-card"}},
        "resource_bindings": [{"action": "add", "source_refs": ["Q2.H1"], "resource_code": "R-NATIVE"}],
    }
    before = deepcopy(authored)
    prior_visible = _card("Q1.H1", "earlier-shown-card", _OTHER)
    current_visible = _card("Q2.H1", "current-shown-card", _SELECTED)

    bound = service.bind_row_evidence_ids(
        [authored], [prior_visible, current_visible], binding_phase="first",
    )[0]

    assert bound["evidence_bindings"] == {"Q1.H1": "earlier-shown-card", "Q2.H1": "current-shown-card"}
    assert bound["_resource_binding_evidence_bindings"] == {"0": {"Q2.H1": "current-shown-card"}}
    assert bound["_evidence_check"]["unresolved_refs"] == []
    assert bound["resource_bindings"] == authored["resource_bindings"]
    assert authored == before
    _unchanged_model_decision(before, bound)


def test_nested_resource_refs_are_not_filled_by_future_handles_during_replay():
    authored = {
        **_authored(), "resource_bindings": [
            {"action": "add", "source_refs": ["Q2.H1"], "resource_code": "R-NATIVE"},
        ],
    }
    saved = _durable(service.bind_row_evidence_ids(
        [authored], [_card("Q1.H1", "early-card", _OTHER)], binding_phase="first",
    )[0])
    assert saved["_resource_binding_evidence_bindings"] == {"0": {}}

    replayed = service.bind_row_evidence_ids(
        [saved], [_card("Q2.H1", "future-card", _SELECTED)], binding_phase="replay",
    )[0]

    assert replayed["evidence_bindings"] == {}
    assert replayed["_resource_binding_evidence_bindings"] == {"0": {}}
    assert replayed["_resource_binding_evidence_checks"][0]["unresolved_refs"] == ["Q2.H1"]
    assert replayed["resource_bindings"] == authored["resource_bindings"]
    _unchanged_model_decision(authored, replayed)


def test_nested_resource_saved_global_identity_is_not_erased_when_its_body_is_unavailable():
    authored = {**_authored(), "resource_bindings": [
        {"action": "add", "source_refs": ["Q2.H1"], "resource_code": "R-NATIVE"},
    ]}
    saved = service.bind_row_evidence_ids([authored], [
        _card("Q2.H1", "original-card", _SELECTED),
    ], binding_phase="first")[0]
    before = deepcopy(saved)

    replayed = service.bind_row_evidence_ids([saved], [
        _card("Q2.H1", "different-future-card", _OTHER),
    ], binding_phase="replay")[0]

    assert replayed["evidence_bindings"] == saved["evidence_bindings"]
    assert replayed["_resource_binding_evidence_bindings"] == {"0": {"Q2.H1": "original-card"}}
    assert replayed["_resource_binding_evidence_checks"][0]["unresolved_refs"] == ["Q2.H1"]
    assert saved == before
    _unchanged_model_decision(authored, replayed)


@pytest.mark.parametrize("saved_map", [{}, {"Q1.H1": "original-resource"}, {"Q2.H1": "original-resource"}])
def test_default_replay_recognizes_a_saved_nested_map_without_a_top_level_map(saved_map):
    # Historical saved actions can predate the top-level norm citation map.
    # Presence of their application-owned map is still a replay boundary,
    # including an explicit empty or partial map.
    row = {
        **_authored(), "resource_bindings": [{
            "action": "add", "source_refs": ["Q1.H1", "Q2.H1"], "resource_code": "R-NATIVE",
        }], "_resource_binding_evidence_bindings": {"0": saved_map},
    }
    before = deepcopy(row)
    chunks = [_card("Q2.H1", "future-resource", _OTHER, condition="future frame")]
    if saved_map:
        original_ref = next(iter(saved_map))
        chunks.append(_card(original_ref, "original-resource", _SELECTED, condition="original frame"))

    replayed = service.bind_row_evidence_ids([row], chunks)[0]

    assert replayed["evidence_bindings"] == {}
    assert replayed["_resource_binding_evidence_bindings"] == {"0": saved_map}
    check = replayed["_resource_binding_evidence_checks"][0]
    assert check["evidence_bindings"] == saved_map
    assert check["unresolved_refs"] == [ref for ref in ("Q1.H1", "Q2.H1") if ref not in saved_map]
    assert row == before and replayed["resource_bindings"] == row["resource_bindings"]
    _unchanged_model_decision(row, replayed)


@pytest.mark.parametrize("injected", [
    {"evidence_bindings": {"Q2.H1": "forged-card"}},
    {"_evidence_binding_snapshot": {"schema": "les.evidence_binding_snapshot.v1", "unresolved_refs": ["Q2.H1"]}},
    {"_evidence_check": {"citation_checkable": True}, "_evidence_binding_snapshot": {
        "schema": "les.evidence_binding_snapshot.v1", "bindings": {"Q2.H1": "forged-card"},
    }},
])
def test_model_debug_fields_cannot_select_first_bind_or_replay_mode(injected):
    authored = _authored()
    raw = json.dumps({"rows": [{**authored, **injected}]}, ensure_ascii=False)
    before = raw.encode("utf-8")
    parsed = service.parse_model_rag_result(raw)
    assert parsed is not None
    decision = parsed[1][0]
    assert not any(key in decision for key in injected)

    bound = service.bind_row_evidence_ids([decision], [_card("Q2.H1", "current-card", _SELECTED)])[0]

    assert bound["evidence_bindings"] == {"Q2.H1": "current-card"}
    assert bound["_evidence_check"]["unresolved_refs"] == []
    assert raw.encode("utf-8") == before
    _unchanged_model_decision(authored, bound)


@pytest.mark.parametrize("map_kind", ["absent", "empty", "partial"])
def test_historic_saved_rows_without_snapshot_leave_unbound_handles_visibly_unresolved(map_kind):
    # A historical row is supplied by the durable replay caller, not decoded as
    # a fresh model result. No temporal snapshot may be inferred from today's map.
    historical = {
        **_authored(known_ref=map_kind == "partial"), "operation_id": "existing-operation", "revision": 3,
    }
    if map_kind != "absent":
        historical["evidence_bindings"] = {"Q1.H1": "early-card"} if map_kind == "partial" else {}
    before = deepcopy(historical)
    prior, _ = service.model_rag_prior_page_context([historical], [
        _card("Q1.H1", "early-card", _OTHER),
        _card("Q2.H1", "future-card", _SELECTED, condition="future frame"),
    ])

    fact = prior["prior_result_structural_facts"][0]["norm_reference"]
    assert fact["unresolved_refs"] == ["Q2.H1"]
    assert _SELECTED not in fact["cited_ciphers"]
    assert prior["prior_model_decisions"][0].get("evidence_bindings") == historical.get("evidence_bindings")
    assert historical == before
    _unchanged_model_decision(historical, prior["prior_model_decisions"][0])


def test_historical_packaging_projection_does_not_trust_unsnapshotted_refs_or_change_saved_identity():
    from proxy.services.lsr_source_coverage_service import operation_identity
    from proxy.services.rim_lsr_trace_service import _visible_row_has_evidence
    from proxy.services.workbook_research_job_service import _decision_content_sha

    historical = {**_authored(), "operation_id": "historical-operation", "revision": 2}
    before = deepcopy(historical)
    durable_sha = _decision_content_sha(historical)
    projected = service.saved_model_decisions_for_packaging([historical])[0]
    again = service.saved_model_decisions_for_packaging([historical])[0]

    assert projected["evidence_bindings"] == {}
    assert projected["_evidence_check"]["unresolved_refs"] == ["Q2.H1"]
    assert _visible_row_has_evidence(projected) is False
    assert operation_identity(projected) == operation_identity(historical)
    assert historical == before and _decision_content_sha(historical) == durable_sha
    # Application metadata legitimately changes the packaging arguments. Never
    # bypass that hash change, and keep subsequent recovery deterministic.
    assert _decision_content_sha(projected) != durable_sha
    assert _decision_content_sha(projected) == _decision_content_sha(again)
    _unchanged_model_decision(historical, projected)


@pytest.mark.parametrize("bindings", [{}, {"Q2.H1": "original-card"}])
def test_historical_packaging_projection_preserves_existing_maps_and_checks_byte_for_byte(bindings):
    historical = {
        **_authored(), "operation_id": "historical-operation", "evidence_bindings": bindings,
        "_evidence_check": {"saved": "original check"},
        "resource_bindings": [{"action": "add", "source_refs": ["Q2.H1"], "resource_code": "R-NATIVE"}],
        "_resource_binding_evidence_bindings": {"0": {"Q2.H1": "resource-original-card"}},
    }
    original_bytes = json.dumps(historical, ensure_ascii=False).encode("utf-8")

    projected = service.saved_model_decisions_for_packaging([historical])[0]

    assert json.dumps(projected, ensure_ascii=False).encode("utf-8") == original_bytes
    assert json.dumps(historical, ensure_ascii=False).encode("utf-8") == original_bytes


@pytest.mark.asyncio
async def test_job_repack_projects_historical_refs_but_preserves_durable_decisions_and_repeated_arguments(monkeypatch):
    from proxy.routers import chat
    from proxy.services import chat_attachment_service
    from proxy.services.lsr_source_coverage_service import operation_identity
    from proxy.services.workbook_research_job_service import _decision_content_sha
    from test_workbook_repack_target import _boundary

    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": "lsr"})
    job["accepted_rows"] = [{**_authored(), "operation_id": "historical-operation", "revision": 2}]
    before = deepcopy(job)
    original_sha = _decision_content_sha(job["accepted_rows"][0])
    monkeypatch.setattr(chat_attachment_service, "resolve_read_attachment", lambda *args: (None, {"sha256": "a" * 64}))
    request = chat.LsrRepackRequest(session_id="own-session", job_id=job["job_id"])

    await chat.repack_lsr_without_model(request, _user={})
    await chat.repack_lsr_without_model(request, _user={})

    assert job == before and len(calls) == 2
    first, second = [call[0]["args"]["decisions"][0] for call in calls]
    assert first["evidence_bindings"] == {} and first == second
    assert first["_evidence_check"]["unresolved_refs"] == ["Q2.H1"]
    assert operation_identity(first) == operation_identity(job["accepted_rows"][0])
    assert _decision_content_sha(job["accepted_rows"][0]) == original_sha
    _unchanged_model_decision(job["accepted_rows"][0], first)


@pytest.mark.asyncio
async def test_jobless_operator_repack_does_not_apply_model_replay_projection(monkeypatch):
    from proxy.routers import chat
    from test_workbook_repack_target import _boundary

    _, calls, _ = _boundary(monkeypatch)
    operator_row = _authored()
    before = deepcopy(operator_row)

    await chat.repack_lsr_without_model(chat.LsrRepackRequest(
        session_id="own-session", attachment_id="read_123456abcdef", decisions=[operator_row],
    ), _user={})

    assert calls[0][0]["args"]["decisions"] == [before]
    assert "evidence_bindings" not in calls[0][0]["args"]["decisions"][0]
    assert operator_row == before


def test_historical_missing_identity_refuses_projection_instead_of_changing_fallback_id():
    from proxy.services.lsr_source_coverage_service import operation_identity

    historical = _authored()
    before = deepcopy(historical)
    identity = operation_identity(historical)

    with pytest.raises(service.HistoricalModelEvidenceIdentityError) as error:
        service.saved_model_decisions_for_packaging([historical])

    assert str(error.value) == "HISTORICAL_MODEL_EVIDENCE_IDENTITY_UNAVAILABLE"
    assert historical == before and operation_identity(historical) == identity


def test_historical_quote_projection_does_not_confirm_price_from_unsnapshotted_refs():
    historical = {**_authored(), "operation_id": "historical-price", "norm_code": "",
                  "confirmed_price": 123.45, "price_source": "original quote", "price_unit": "м"}
    before = deepcopy(historical)

    projected = service.saved_model_decisions_for_packaging([historical])[0]

    assert projected["evidence_bindings"] == {}
    check = projected["_price_evidence_check"]
    assert check["checked_evidence_ids"] == []
    assert check["price_in_refs"] is False and check["unit_in_refs"] is False
    assert check["source_in_refs"] is False
    assert projected["confirmed_price"] == 123.45 and historical == before


@pytest.mark.parametrize("norm_code,refs", [("", ["Q2.H1"]), (_SELECTED, [])])
def test_historical_rows_without_cited_normative_or_price_claim_need_no_projection(norm_code, refs):
    row = {**_authored(), "norm_code": norm_code, "evidence_refs": refs}
    before = deepcopy(row)

    assert service.saved_model_decisions_for_packaging([row]) == [before]
    assert row == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["lsr", "vor"])
async def test_unversioned_historical_job_blocks_only_lsr_repack_with_visible_error(monkeypatch, kind):
    from proxy.routers import chat
    from test_workbook_repack_target import _boundary

    job, calls, _ = _boundary(monkeypatch, context={"artifact_intent": kind})
    job["accepted_rows"] = [_authored()]
    before = deepcopy(job)
    request = chat.LsrRepackRequest(session_id="own-session", job_id=job["job_id"])

    if kind == "lsr":
        with pytest.raises(chat.HTTPException) as error:
            await chat.repack_lsr_without_model(request, _user={})
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "HISTORICAL_MODEL_EVIDENCE_IDENTITY_UNAVAILABLE"
        assert error.value.detail["model_called"] is False
        assert "Сохранённые решения" in error.value.detail["message"]
        assert calls == []
    else:
        result = await chat.repack_lsr_without_model(request, _user={})
        assert result["model_called"] is False
        assert calls[0][0]["tool"] == "build_vor_workbook"
        assert calls[0][0]["args"]["decisions"] == before["accepted_rows"]
    assert job == before


@pytest.mark.asyncio
@pytest.mark.parametrize("permanent_identity", [False, True])
async def test_actual_chat_terminal_job_projects_only_evidence_metadata_without_new_model_or_job_changes(
    tmp_path, monkeypatch, permanent_identity,
):
    import sqlite3
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService
    from test_model_rag_sheet_evidence_reads import _run_sheet

    run = await _run_sheet(tmp_path, monkeypatch, reads=True)
    store = WorkbookResearchJobService()
    job_id = run.result["retrieval_trace"]["workbook_research_job"]["job_id"]
    # Test-owned historical snapshot: the real completed-job path must treat
    # its old refs as unverified, rather than consult today's source map.
    historical = deepcopy(store.get(job_id)["accepted_rows"])
    historical[0]["norm_code"] = _SELECTED
    historical[0]["evidence_refs"] = ["Q2.H1"]
    historical[0].pop("evidence_bindings", None)
    historical[0].pop("_evidence_check", None)
    if not permanent_identity:
        historical[0].pop("operation_id", None)
    raw = json.dumps(historical, ensure_ascii=False)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE workbook_research_jobs SET accepted_rows_json=? WHERE job_id=?", (raw, job_id))
    before = deepcopy(store.get(job_id)["accepted_rows"])
    model_calls, packaging_calls = len(run.requests), len(run.executions)

    resumed = await run.resume_same_request()

    assert len(run.requests) == model_calls
    assert store.get(job_id)["accepted_rows"] == before
    if permanent_identity:
        assert len(run.executions) == packaging_calls + 1
        projected = run.executions[-1][0]["args"]["decisions"][0]
        assert projected["evidence_bindings"] == {}
        assert projected["_evidence_check"]["unresolved_refs"] == ["Q2.H1"]
        assert projected["operation_id"] == before[0]["operation_id"]
        _unchanged_model_decision(before[0], projected)
    else:
        assert len(run.executions) == packaging_calls
        result = resumed["retrieval_trace"]["model_result"]
        assert result["status"] == "structural_error" and result["packaged"] is False
        assert "HISTORICAL_MODEL_EVIDENCE_IDENTITY_UNAVAILABLE" in result["errors"]
        assert "HISTORICAL_MODEL_EVIDENCE_IDENTITY_UNAVAILABLE" in resumed["answer"]
