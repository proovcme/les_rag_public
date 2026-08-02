"""Memory Core v1 contracts: strict capture, scoping and fail-safe recall."""

from __future__ import annotations

import asyncio
from pathlib import Path

from proxy.memory_core.config import MemoryConfig
from proxy.memory_core.contracts import (
    EntryKind,
    EvidenceRef,
    MemoryEntry,
    MemoryMode,
    RouteEvidenceCacheDTO,
    SmetaRecallMode,
    SmetaSuccessTrace,
    SmetaTraceTrust,
    ValidationStatus,
)
from proxy.memory_core.store import MemoryStore
from proxy.memory_core.validation import grounded_turn_eligible, initial_assertion_status
from proxy.services.memory_port import NullMemoryPort
from proxy.services.memory_rag_adapter import ActiveMemoryPort, normalized_work_signature
from proxy.services.memory_worker_service import MemoryWorker


def _store(tmp_path: Path | None = None) -> MemoryStore:
    return MemoryStore(":memory:")


def _grounded_turn() -> dict:
    return {
        "question": "Какая масса насоса?",
        "answer": "85 кг [Источник 1]",
        "crag_status": "VERIFIED",
        "cache_hit": False,
        "query_route": {"channel": "rag", "profile": {"profile_id": "grounded_rag"}},
        "evidence_refs": [{
            "ref_id": "S1", "doc_id": "letter-147", "locator": "page=3",
            "source_revision": "r1", "is_evidence": True, "snippet_sha256": "",
        }],
    }


def test_off_port_is_zero_io_contract():
    port = NullMemoryPort()
    assert port.get_mode() == MemoryMode.OFF
    assert port.enqueue_rag_turn(1, _grounded_turn()) is False
    assert port.recall_project_advisory(1, "насос") == ""
    assert port.recall_route_cache(1, {}) == []


def test_grounded_predicate_is_strict():
    turn = _grounded_turn()
    assert grounded_turn_eligible(project_id=7, turn=turn)
    for mutation in (
        {"crag_status": "UNVALIDATED"}, {"cache_hit": True},
        {"evidence_refs": []}, {"query_route": {"channel": "free"}},
    ):
        assert not grounded_turn_eligible(project_id=7, turn={**turn, **mutation})
    assert not grounded_turn_eligible(project_id=None, turn=turn)


def test_shadow_enqueues_but_never_recalls():
    store = _store()
    port = ActiveMemoryPort(store, MemoryConfig(mode=MemoryMode.SHADOW))
    assert port.enqueue_rag_turn(3, _grounded_turn())
    assert store.status()["queue"] == {"pending": 1}
    assert port.recall_project_advisory(3, "насос") == ""


def test_project_fact_is_scoped_and_ordinary_text_stays_candidate():
    store = _store()
    entry = MemoryEntry(
        entry_id="e1", project_id=1, kind=EntryKind.ASSERTION,
        subject="Насос Н1", predicate="масса", value=85,
    )
    refs = [EvidenceRef("S1", "letter-147", "page=3", "r1")]
    entry.validation_status = initial_assertion_status(entry, refs)
    store.insert_entry(entry, refs)
    assert entry.validation_status == ValidationStatus.CANDIDATE
    assert [item.entry_id for item in store.get_entries_by_project(1)] == ["e1"]
    assert store.get_entries_by_project(2) == []


def test_only_typed_or_computed_assertions_can_code_confirm():
    refs = [EvidenceRef("S1", "typed-sheet", "sheet=1;cell=B2", "r1")]
    typed = MemoryEntry(
        "typed", 1, EntryKind.ASSERTION, "Насос", "масса", 85,
        provenance={"confirmation_kind": "typed_exact_locator"},
    )
    computed = MemoryEntry(
        "computed", 1, EntryKind.ASSERTION, "Кабель", "масса", 12,
        provenance={"confirmation_kind": "computed", "computed": {"formula": "m*l", "inputs": {"m": 2, "l": 6}}},
    )
    assert initial_assertion_status(typed, refs) == ValidationStatus.CONFIRMED
    assert initial_assertion_status(computed, refs) == ValidationStatus.CONFIRMED


def test_conflict_has_no_confidence_winner():
    from proxy.memory_core.conflicts import register_fact_conflicts

    store = _store()
    for entry_id, value in (("old", 85), ("new", 90)):
        entry = MemoryEntry(entry_id, 1, EntryKind.ASSERTION, "Насос Н1", "масса", value)
        store.insert_entry(entry)
        register_fact_conflicts(store, entry)
    statuses = {item.entry_id: item.validation_status for item in store.get_entries_by_project(1)}
    assert statuses == {"old": ValidationStatus.DISPUTED, "new": ValidationStatus.DISPUTED}
    assert store.status()["open_conflicts"] == 1


def test_worker_uses_candidate_for_model_text():
    async def extract(_payload):
        return [{"subject": "Насос Н1", "predicate": "масса", "value": 85}]

    async def scenario():
        store = _store()
        store.enqueue(1, "grounded_rag_turn", _grounded_turn())
        worker = MemoryWorker(store, asyncio.Semaphore(1), extractor=extract)
        assert await worker.run_once()
        entries = store.get_entries_by_project(1)
        assert len(entries) == 1
        assert entries[0].validation_status == ValidationStatus.CANDIDATE
        assert store.status()["queue"] == {"done": 1}

    asyncio.run(scenario())


def test_route_reuse_requires_same_project_signature_and_edition():
    store = _store()
    features = {"title": "Монтаж кабеля", "unit": "м", "function": "СКС", "knowledge_edition": "ФСНБ-2022:r1"}
    signature = normalized_work_signature(features)
    route = RouteEvidenceCacheDTO(
        "route:gesnm:10:10-04:10-04-067", "ГЭСНм", "10", "10-04", "10-04-067",
        "ФСНБ-2022:r1", "r1", signature,
    )
    trace = SmetaSuccessTrace(
        "t1", 1, "attachment", "a1", "rev:w1", "abc", "priced_draft", "q",
        features, (route,), ("ГЭСНм10-04-067-01",), (), "ФСНБ-2022:r1",
    )
    assert store.save_smeta_trace(trace)
    port = ActiveMemoryPort(store, MemoryConfig(MemoryMode.ON, True, SmetaRecallMode.ROUTE_REUSE))
    assert port.recall_route_cache(1, features) == []
    assert store.confirm_smeta_revision(
        "rev", locked_revision_id="rev-locked", review_note="Проверено по смете"
    ) == 1
    assert [item.cache_id for item in port.recall_route_cache(1, features)] == [route.cache_id]
    assert port.recall_route_cache(2, features) == []
    assert port.recall_route_cache(1, {**features, "knowledge_edition": "ФСНБ-2022:r2"}) == []


def test_smeta_advisory_teaches_only_after_explicit_confirmation():
    store = _store()
    features = {
        "title": "telecommunication cabinet",
        "unit": "pcs",
        "function": "structured cabling",
    }
    trace = SmetaSuccessTrace(
        "candidate", 1, "attachment", "a1", "rev:w1", "abc", "priced_draft", "q",
        features, (), ("GESNm10-01-001-01",), (), "FSNB-2022:r1",
        trust_level=SmetaTraceTrust.CANDIDATE,
    )
    assert store.save_smeta_trace(trace)
    port = ActiveMemoryPort(
        store,
        MemoryConfig(MemoryMode.ON, True, SmetaRecallMode.ADVISORY),
    )

    assert port.recall_smeta_advisory(1, features) == []
    assert store.confirm_smeta_revision(
        "rev",
        locked_revision_id="rev-locked",
        review_note="verified by estimator",
    ) == 1
    advisory = port.recall_smeta_advisory(1, features)
    assert advisory[0]["selected_norm_refs"] == ["GESNm10-01-001-01"]
    assert advisory[0]["trust_level"] == "accepted_project"
    assert port.recall_smeta_advisory(2, features) == []


def test_rejected_smeta_trace_is_not_recalled():
    store = _store()
    features = {"title": "Монтаж кабеля", "unit": "м", "knowledge_edition": "FSNB-2022:r1"}
    signature = normalized_work_signature(features)
    route = RouteEvidenceCacheDTO(
        "route:1", "ГЭСНм", "10", "10-04", "10-04-067",
        "FSNB-2022:r1", "rev", signature,
    )
    trace = SmetaSuccessTrace(
        "rejected", 1, "attachment", "a1", "rev:w1", "abc", "priced_draft", "q",
        features, (route,), ("ГЭСНм10-04-067-01",), (), "FSNB-2022:r1",
        trust_level=SmetaTraceTrust.CANDIDATE,
    )
    assert store.save_smeta_trace(trace)
    assert store.review_smeta_trace("rejected", "reject", "Неверная привязка")
    port = ActiveMemoryPort(store, MemoryConfig(MemoryMode.ON, True, SmetaRecallMode.ROUTE_REUSE))
    assert port.recall_route_cache(1, features) == []


def test_project_fact_cannot_promote_to_global():
    store = _store()
    store.insert_entry(MemoryEntry("fact", 1, EntryKind.ASSERTION, "Насос", "масса", 85))
    try:
        store.promote_non_fact("fact", "global")
    except ValueError as error:
        assert "facts cannot" in str(error)
    else:
        raise AssertionError("project fact was promoted")
