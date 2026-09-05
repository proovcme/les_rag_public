import json
import sqlite3
from dataclasses import replace

import pytest

from proxy.services import typed_memory_projection_service as memory
from proxy.services.chat_evidence_application_service import (
    context_packet_trace,
    govern_inference_messages,
)
from proxy.services.context_governor_service import ContextKind
from proxy.services.model_execution_preset_service import _FACTORY_9B


def project(notes, **kwargs):
    return memory.project_memory_from_records(
        session_id="workspace", project_id=7, dataset_ids=(), chat_profile={},
        dialogue=(), notes=notes, traces=(), advisory_items=(),
        limits=kwargs.get("limits", memory.MemoryLimits()),
    )


def model_packet(projection, budget=6000):
    working = tuple(obj for c in projection.as_context_candidates()
                    if c.kind == ContextKind.WORKING_MEMORY for obj in c.objects)
    return govern_inference_messages(
        preset=replace(_FACTORY_9B, input_token_limit=budget),
        profile_prefix="Answer from evidence", request_payload="ORIGINAL QUESTION + COMPLETE ATTACHMENT",
        evidence=("EXACT RETRIEVED EVIDENCE",), source_map=("Q1.H1 source",),
        working_memory=working,
    )


def test_scope_and_enabled_filter_precede_note_limit():
    projection = project([
        {"id": 1, "project_id": 8, "text": "foreign"},
        {"id": 2, "project_id": 7, "text": "disabled", "enabled": False},
        {"id": 3, "project_id": 7, "text": "explicit preference"},
    ], limits=memory.MemoryLimits(max_notes=1))
    assert [item.item_id for item in projection.items] == ["note:3"]


def test_edit_and_disable_change_next_model_input_without_losing_evidence():
    note = {"id": 3, "project_id": 7, "text": "Original preference", "enabled": True}
    first, _ = model_packet(project([note]))
    note["text"] = "Updated preference"
    second, packet = model_packet(project([note]))
    note["enabled"] = False
    third, _ = model_packet(project([note]))
    assert "Original preference" in json.dumps(first)
    assert "Original preference" not in json.dumps(second)
    assert "Updated preference" in json.dumps(second)
    assert "Updated preference" not in json.dumps(third)
    for messages in (first, second, third):
        assert "ORIGINAL QUESTION + COMPLETE ATTACHMENT" in json.dumps(messages)
        assert "EXACT RETRIEVED EVIDENCE" in json.dumps(messages)
    trace = context_packet_trace(packet, purpose="answer")
    working = next(s for s in trace["sections"] if s["kind"] == "working_memory")
    assert working["object_ids"] == ["note:3"]
    assert "Updated preference" not in json.dumps(trace)


def test_oversized_note_is_omitted_whole_and_addressable():
    projection = project([{"id": 3, "project_id": 7, "text": "x" * 701}])
    assert projection.items == ()
    assert projection.omitted == 1
    assert projection.omitted_item_ids == ("note:3",)


def test_memory_omission_under_9b_budget_preserves_request_and_evidence():
    projection = project([{"id": 3, "project_id": 7, "text": "x" * 500}])
    messages, packet = model_packet(projection, budget=1850)
    assert "ORIGINAL QUESTION + COMPLETE ATTACHMENT" in json.dumps(messages)
    assert "EXACT RETRIEVED EVIDENCE" in json.dumps(messages)
    assert "x" * 500 not in json.dumps(messages)
    assert any("note:3" in omitted.object_ids for omitted in packet.omissions)


def test_registered_model_rag_context_uses_only_explicit_notes():
    from proxy.services.chat_evidence_application_service import workspace_note_objects
    projection = memory.project_memory_from_records(
        session_id="workspace", project_id=7, dataset_ids=("ds",), chat_profile={},
        dialogue=({"turn_id": "old", "question": "old question"},),
        notes=({"id": 3, "project_id": 7, "text": "preference"},),
        traces=(), advisory_items=(), limits=memory.MemoryLimits(),
    )
    assert [obj.object_id for obj in workspace_note_objects(
        projection.as_context_candidates(), registered=True)] == ["note:3"]
    assert workspace_note_objects(projection.as_context_candidates(), registered=False) == ()


@pytest.mark.parametrize("record,requested,expected", [
    ({"registered": True, "project_id": None}, 7, None),
    ({"registered": True, "project_id": 8}, 7, 8),
    ({"registered": False, "project_id": None}, 7, 7),
    (None, 7, 7),
])
def test_session_ownership_is_authoritative_only_for_memory(monkeypatch, record, requested, expected):
    from proxy.services import chat_session_service
    monkeypatch.setattr(chat_session_service, "get_session", lambda session_id: record)
    monkeypatch.setattr(memory, "chat_memory_projection_record", lambda _: {})
    monkeypatch.setattr(memory, "session_memory_items", lambda *a, **k: [])
    monkeypatch.setattr(memory, "session_recent_retrieval_traces", lambda *a, **k: [])
    monkeypatch.setattr(memory, "project_advisory_items", lambda *a, **k: [])
    monkeypatch.setattr(memory, "project_note_items", lambda **k: [
        {"id": 7, "project_id": 7, "text": "project seven"},
        {"id": 8, "project_id": 8, "text": "project eight"},
        {"id": 1, "project_id": 0, "text": "global preference"},
    ])
    projection = memory.project_memory(session_id="workspace", project_id=requested,
                                      dataset_ids=("explicit-dataset-seven",), limits=memory.MemoryLimits())
    assert projection.project_id == expected
    ids = {item.item_id for item in projection.items}
    assert "note:1" in ids
    assert ("note:7" in ids) == (expected == 7)
    assert ("note:8" in ids) == (expected == 8)
    assert "dataset-locator:explicit-dataset-seven" in ids


def test_registered_notes_keep_full_api_length_without_autonomous_memory(monkeypatch):
    from proxy.services import chat_session_service
    monkeypatch.setattr(chat_session_service, "get_session", lambda _: {
        "registered": True, "project_id": 7,
    })
    monkeypatch.setattr(memory, "chat_memory_projection_record", lambda _: {})
    monkeypatch.setattr(memory, "session_memory_items", lambda *a, **k: [])
    monkeypatch.setattr(memory, "session_recent_retrieval_traces", lambda *a, **k: [])
    def forbid_autonomous_recall(*a, **k):
        pytest.fail("Registered workspaces only use explicitly saved project notes")
    monkeypatch.setattr(memory, "project_advisory_items", forbid_autonomous_recall)
    monkeypatch.setattr(memory, "project_note_items", lambda **k: [
        {"id": 3, "project_id": 7, "text": "x" * 2000},
    ])
    projection = memory.project_memory(session_id="workspace", project_id=7,
                                      dataset_ids=tuple(f"dataset-{i}" for i in range(30)),
                                      limits=memory.MemoryLimits())
    assert projection.items[0].payload["text"] == "x" * 2000
    assert "note:3" not in projection.omitted_item_ids
    assert len(projection.items) == 24


def test_saved_note_changes_reach_next_packet_from_read_only_stores(tmp_path, monkeypatch):
    from proxy.services import chat_session_service, memory_service, context_memory_service
    db = tmp_path / "workspace.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE les_projects (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO les_projects VALUES (7)")
    for store in (chat_session_service, memory_service, context_memory_service):
        monkeypatch.setattr(store, "rag_meta_db_path", lambda: str(db))
    owned = chat_session_service.create_session(project_id=7)["session_id"]
    ordinary = chat_session_service.create_session()["session_id"]
    note = memory_service.create_note("Saved old preference", project_id=7)
    for index in range(6):
        memory_service.create_note(f"Autonomous old fact {index}", project_id=7, auto=True)

    def next_input(sid):
        before = db.read_bytes()
        projection = memory.project_memory(session_id=sid, project_id=7,
                                          dataset_ids=("project-seven-dataset",), limits=memory.MemoryLimits())
        messages, packet = model_packet(projection)
        assert db.read_bytes() == before
        return json.dumps(messages), context_packet_trace(packet, purpose="answer")

    assert "Saved old preference" in next_input(owned)[0]
    assert "Autonomous old fact" not in next_input(owned)[0]
    assert "Saved old preference" not in next_input(ordinary)[0]
    memory_service.update_note(note["id"], project_id=7, text="Saved new preference")
    edited, trace = next_input(owned)
    assert "Saved new preference" in edited and "Saved old preference" not in edited
    assert "Saved new preference" not in json.dumps(trace)
    memory_service.update_note(note["id"], project_id=7, enabled=False)
    disabled, _ = next_input(owned)
    assert "Saved new preference" not in disabled
    assert "ORIGINAL QUESTION + COMPLETE ATTACHMENT" in disabled
    assert "EXACT RETRIEVED EVIDENCE" in disabled


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_active_model_rag_flow_receives_only_enabled_workspace_notes(tmp_path, monkeypatch, enabled):
    import test_chat_evidence_application_service as existing_flow
    from proxy.services import chat_evidence_application_service as application, chat_session_service
    monkeypatch.setattr(chat_session_service, "get_session", lambda _: {
        "registered": True, "project_id": 7,
    })
    monkeypatch.setattr(memory, "chat_memory_projection_record", lambda _: {})
    monkeypatch.setattr(memory, "session_memory_items", lambda *a, **k: [])
    monkeypatch.setattr(memory, "session_recent_retrieval_traces", lambda *a, **k: [])
    monkeypatch.setattr(memory, "project_note_items", lambda **k: [
        {"id": 3, "project_id": 7, "text": "UNIQUE WORKSPACE PREFERENCE", "enabled": enabled},
    ])
    def forbid_autonomous_memory():
        pytest.fail("Registered workspace must neither recall nor enqueue autonomous memory")
    monkeypatch.setattr(application, "get_memory_port", forbid_autonomous_memory)
    captured = []
    def capture_packet(**kwargs):
        messages, packet = govern_inference_messages(**kwargs)
        captured.append((json.dumps(messages), packet))
        return messages, packet
    monkeypatch.setattr(application, "govern_inference_messages", capture_packet)
    # Reuse the production-flow transport fixture and all its original assertions
    # for literal queries, full attachment/evidence, unchanged decisions and XLSX.
    await existing_flow.test_actual_chat_shadow_failure_preserves_legacy_answer_history_and_model_count(
        monkeypatch, tmp_path, "active_model_rag_result",
    )
    with_note = [packet for messages, packet in captured if "UNIQUE WORKSPACE PREFERENCE" in messages]
    assert len(with_note) >= 2 if enabled else not with_note
