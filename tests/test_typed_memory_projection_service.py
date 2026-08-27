import hashlib
import json
import sqlite3

from proxy.services.context_governor_service import ContextKind
from proxy.services.typed_memory_projection_service import (
    MemoryItemKind,
    MemoryLimits,
    project_memory,
    project_memory_from_records,
)


def test_projection_separates_memory_from_evidence():
    projection = project_memory_from_records(
        session_id="s1",
        project_id=7,
        dataset_ids=("dataset-a",),
        chat_profile={"last_status": "VERIFIED", "turn_count": 2},
        dialogue=({"turn_id": "turn-1", "question": "Q", "answer": "A"},),
        notes=({"id": 3, "text": "Комментарий оператора", "project_id": 7},),
        traces=(),
        advisory_items=(),
        limits=MemoryLimits(),
    )

    assert projection.context_role == "advisory_state"
    assert projection.items
    assert all(item.is_evidence is False for item in projection.items)
    assert any(item.kind == MemoryItemKind.EVIDENCE_LOCATOR for item in projection.items)


def test_model_decision_is_stored_as_revision_reference_not_rewritten_fact():
    projection = project_memory_from_records(
        session_id="s1",
        project_id=7,
        dataset_ids=(),
        chat_profile={},
        dialogue=(),
        notes=(),
        traces=(
            {
                "decision_checkpoint": {
                    "revision_ref": "rev-2",
                    "payload": {"status": "accepted"},
                }
            },
        ),
        advisory_items=(),
        limits=MemoryLimits(),
    )

    decision = next(item for item in projection.items if item.kind == MemoryItemKind.DECISION)
    assert decision.revision_ref == "rev-2"
    assert decision.payload == {"status": "accepted"}
    assert decision.is_evidence is False


def test_projection_filters_notes_to_current_project():
    projection = project_memory_from_records(
        session_id="s1",
        project_id=7,
        dataset_ids=(),
        chat_profile={},
        dialogue=(),
        notes=(
            {"id": 1, "text": "current", "project_id": 7},
            {"id": 2, "text": "foreign", "project_id": 8},
            {"id": 3, "text": "global", "project_id": 0},
        ),
        traces=(),
        advisory_items=(),
        limits=MemoryLimits(),
    )

    payloads = [item.payload for item in projection.items if item.kind == MemoryItemKind.ADVISORY_FACT]
    assert {payload["text"] for payload in payloads} == {"current", "global"}


def test_projection_rejects_foreign_memory_port_items():
    projection = project_memory_from_records(
        session_id="s1",
        project_id=7,
        dataset_ids=(),
        chat_profile={},
        dialogue=(),
        notes=(),
        traces=(),
        advisory_items=(
            {"item_id": "current", "project_id": 7, "payload": {"text": "ok"}},
            {"item_id": "foreign", "project_id": 8, "payload": {"text": "leak"}},
        ),
        limits=MemoryLimits(),
    )

    assert {item.item_id for item in projection.items} == {"current"}


def test_every_payload_is_bounded_after_json_serialization():
    limits = MemoryLimits(max_payload_chars=40)
    projection = project_memory_from_records(
        session_id="s1",
        project_id=7,
        dataset_ids=("d" * 500,),
        chat_profile={"blockers": ["b" * 500]},
        dialogue=({"turn_id": "1", "question": "q" * 500, "answer": "a" * 500},),
        notes=({"id": 1, "project_id": 7, "text": "n" * 500},),
        traces=(
            {"decision_checkpoint": {"revision_ref": "rev", "payload": {"k" * 500: "v" * 500}}},
        ),
        advisory_items=({"item_id": "port", "project_id": 7, "payload": {"x" * 500: "y"}},),
        limits=limits,
    )

    assert all(
        len(json.dumps(dict(item.payload), ensure_ascii=False, separators=(",", ":")))
        <= limits.max_payload_chars
        for item in projection.items
    )


def test_projection_emits_governor_candidates_and_bounded_omission_cursor():
    projection = project_memory_from_records(
        session_id="s1",
        project_id=None,
        dataset_ids=(),
        chat_profile={"blockers": ["b1", "b2"]},
        dialogue=(),
        notes=(),
        traces=(),
        advisory_items=(),
        limits=MemoryLimits(max_items=1),
    )

    candidates = projection.as_context_candidates()

    assert len(projection.items) == 1
    assert projection.omitted == 1
    assert projection.cursor.startswith("memory:s1:")
    assert candidates[0].kind == ContextKind.CHECKPOINT


def test_project_memory_uses_existing_store_adapters_without_writes(monkeypatch):
    import proxy.services.typed_memory_projection_service as projection_service

    monkeypatch.setattr(
        projection_service,
        "chat_memory_projection_record",
        lambda session_id: {"session_id": session_id, "last_status": "ok"},
    )
    monkeypatch.setattr(
        projection_service,
        "session_memory_items",
        lambda session_id, max_turns: [{"turn_id": "1", "question": "Q", "answer": "A"}],
    )
    monkeypatch.setattr(projection_service, "session_recent_retrieval_traces", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        projection_service,
        "project_note_items",
        lambda limit, project_id: [{"id": 1, "text": "note", "project_id": project_id or 0}],
    )
    monkeypatch.setattr(
        projection_service,
        "project_advisory_items",
        lambda project_id, limit: [{"item_id": "port-1", "payload": {"text": "advisory"}}],
    )

    projection = project_memory(
        session_id="s1",
        project_id=7,
        dataset_ids=("ds-1",),
        limits=MemoryLimits(max_items=20),
    )

    assert projection.context_role == "advisory_state"
    assert any(item.item_id == "port-1" for item in projection.items)


def test_project_memory_is_read_only_against_existing_sqlite(tmp_path, monkeypatch):
    import proxy.services.context_memory_service as context_store
    import proxy.services.memory_service as memory_store

    db_path = tmp_path / "memory.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE les_chat_profiles (session_id TEXT PRIMARY KEY, profile_json TEXT, "
            "turn_count INTEGER, updated_at REAL)"
        )
        conn.execute(
            "INSERT INTO les_chat_profiles VALUES (?,?,?,?)",
            ("s1", json.dumps({"last_status": "ok", "blockers": ["missing"]}), 1, 1.0),
        )
        conn.execute(
            "CREATE TABLE chat_history (id INTEGER PRIMARY KEY, session_id TEXT, question TEXT, "
            "answer TEXT, retrieval_trace_json TEXT)"
        )
        conn.execute(
            "INSERT INTO chat_history VALUES (1,'s1','Q','A','{}')"
        )
        conn.execute(
            "CREATE TABLE les_notes (id INTEGER PRIMARY KEY, text TEXT, project_id INTEGER)"
        )
        conn.execute("INSERT INTO les_notes VALUES (1,'note',7)")
        conn.commit()
    monkeypatch.setattr(context_store, "rag_meta_db_path", lambda: str(db_path))
    monkeypatch.setattr(memory_store, "rag_meta_db_path", lambda: str(db_path))
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    projection = project_memory(
        session_id="s1",
        project_id=7,
        dataset_ids=("ds-1",),
        limits=MemoryLimits(),
    )

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert projection.items
    assert before == after
