"""Unread pointer field sharing must preserve every independent evidence handle."""

import copy
import json
from types import SimpleNamespace

import pytest

from proxy.services.model_rag_grouped_evidence_service import (
    EvidenceCard, compact_read_replay, inventory_pointer, prepare_model_read_replay,
)


def _chunk(ref, *, pointer=None, **metadata):
    meta = {
        "model_evidence_ref": ref, "global_evidence_id": f"immutable:{ref}",
        "norm_key": "literal-key", "norm_code": "literal-code",
        "title": 'Literal title with "quotes" and Unicode м³', "measure_unit": "м³",
        "source_ref": "C:/literal source/catalog#card", "source_sha256": "a" * 64,
        "edition": "literal-edition", "base_type": "literal-base",
        "doc_id": "literal-document", "dataset_id": "literal-dataset",
        "body_status": "deferred_capacity", "model_delivery_status": "prepared",
        "model_inventory_delivery_status": "prepared", "model_read_tool": "search_sources",
        **metadata,
    }
    content = pointer if pointer is not None else inventory_pointer(
        EvidenceCard(ref, "literal-source", "", "", meta))
    meta["model_inventory_view"] = content
    return {"doc_name": "literal-source", "doc_id": meta["doc_id"], "content": content, "meta": meta}


def _records(replay):
    return [json.loads(line) for line in replay[2].splitlines()[1:]]


def _restore(records):
    owners = {}
    restored = []
    for record in records:
        if len(record) == 2 and isinstance(record[1], dict) and "same_pointer_fields_as" in record[1]:
            owner = owners[record[1]["same_pointer_fields_as"]]
            record = [record[0], *copy.deepcopy(owner[1:])]
        else:
            owners[record[0]] = record
        restored.append(record)
    return restored


def test_unread_aliases_restore_all_fields_with_first_owner_and_distinct_raw_ids():
    refs = ["Q8.H3", "Q2.H1", "Q5.H6"]
    pointers = [[ref, "deferred_capacity", "literal-key", "literal-code", "long literal title " * 8,
                 "м³", "literal-source-id", {"global_evidence_id": "wire-owned-id", "page": 0,
                 "unit": "", "future_fields": {"flag": False, "values": [0, None, ""]}}] for ref in refs]
    chunks = [_chunk(ref, pointer=json.dumps(pointer, ensure_ascii=False, separators=(",", ":")))
              for ref, pointer in zip(refs, pointers)]
    original = copy.deepcopy(chunks)

    replay = compact_read_replay(chunks)
    records = _records(replay)

    assert records[0] == pointers[0]
    assert records[1:] == [[ref, {"same_pointer_fields_as": refs[0]}] for ref in refs[1:]]
    assert _restore(records) == pointers
    assert "distinct evidence identities" in replay[2].splitlines()[0]
    assert replay[1]["previously_shown_evidence_registry"] == []
    assert list(replay[0]["literal_source_catalog"].values()) == [chunks[0]["meta"]["source_ref"]]
    assert chunks == original
    assert len({chunk["meta"]["global_evidence_id"] for chunk in chunks}) == len(refs)


@pytest.mark.parametrize("field", [2, 3, 4, 5, 6, 7, 8])
def test_any_changed_wire_field_stays_a_separate_pointer(field):
    owner = ["Q1.H1", "deferred_capacity", "key", "code", "long title " * 8, "m", "source",
             {"global_evidence_id": "original", "status": False}, [0, None, False]]
    other = copy.deepcopy(owner)
    other[0] = "Q2.H1"
    other[field] = {"changed": field} if field >= 7 else f"changed-{field}"
    chunks = [_chunk(pointer[0], pointer=json.dumps(pointer)) for pointer in [owner, other]]

    records = _records(compact_read_replay(chunks))

    assert records == [owner, other]


@pytest.mark.parametrize("changed", [
    {"source_sha256": "b" * 64}, {"edition": "other-edition"}, {"base_type": "other-base"},
    {"norm_key": "other-key"}, {"norm_code": "other-code"}, {"source_ref": "other-source"},
    {"doc_id": "other-document"}, {"dataset_id": "other-dataset"},
])
def test_changed_immutable_provenance_never_shares_even_equal_pointer_fields(changed):
    first = _chunk("Q1.H1")
    pointer = json.loads(first["content"])
    pointer[0] = "Q2.H1"
    second = _chunk("Q2.H1", pointer=json.dumps(pointer), **changed)

    records = _records(compact_read_replay([first, second]))

    assert records == [json.loads(first["content"]), pointer]


def test_ambiguous_owner_alias_is_never_the_target_of_field_sharing():
    first = _chunk("Q1.H1")
    conflicting = _chunk("Q1.H1", title="Different literal title")
    repeated = _chunk("Q2.H1")
    chunks = [first, conflicting, repeated]

    records = _records(compact_read_replay(chunks))

    assert records == [json.loads(chunk["content"]) for chunk in chunks]


def test_large_unique_inventory_keeps_exact_wire_records_sources_and_order():
    chunks = [_chunk(f"Q{index}.H1", norm_key=f"literal-key-{index}", norm_code=f"literal-code-{index}",
                     source_ref=f"literal-source-{index}", title=f"literal-{index} " * 20)
              for index in range(1, 601)]
    original = copy.deepcopy(chunks)

    replay = compact_read_replay(chunks)

    assert _records(replay) == [json.loads(chunk["content"]) for chunk in chunks]
    assert replay[2] == "Deferred identity pointers; read_norm_card/read_source remain available:\n" + "\n".join(
        chunk["content"] for chunk in chunks)
    assert len(replay[0]["literal_source_catalog"]) == len(chunks)
    assert chunks == original


def test_short_duplicate_pointers_do_not_grow_the_wire_to_explain_sharing():
    pointers = [[ref, "deferred_capacity", "k", "c", "t", "m", "s"] for ref in ("Q1.H1", "Q2.H1")]
    chunks = [_chunk(pointer[0], pointer=json.dumps(pointer, separators=(",", ":"))) for pointer in pointers]

    replay = compact_read_replay(chunks)

    assert _records(replay) == pointers
    assert replay[2] == "Deferred identity pointers; read_norm_card/read_source remain available:\n" + "\n".join(
        chunk["content"] for chunk in chunks)


def test_all_delivered_aliases_keep_their_body_required_without_raw_mutation():
    body = "LITERAL ALL CONDITIONS AND RESOURCES; " + "quantity=0.125, source=literal; " * 30
    chunks = [_chunk(ref, model_raw_body_retained=True, body_status="full", model_delivery_status="delivered")
              for ref in ("Q1.H1", "Q2.H1", "Q3.H1", "Q4.H1")]
    for chunk in chunks:
        chunk["content"] = body
    original = copy.deepcopy(chunks)

    replay = prepare_model_read_replay(chunks, required_refs=["immutable:Q1.H1"])

    assert replay.inventory_refs == [chunk["meta"]["model_evidence_ref"] for chunk in chunks]
    assert replay.exact_body_refs == [chunk["meta"]["model_evidence_ref"] for chunk in chunks]
    row, = replay.required[1]["previously_shown_evidence_registry"]
    assert row["content"] == body
    assert row["global_evidence_id"] == "immutable:Q1.H1"
    aliases = [{"evidence_ref": row["evidence_ref"], "global_evidence_id": row["global_evidence_id"]},
               *row.get("aliases", [])]
    assert aliases == [{"evidence_ref": chunk["meta"]["model_evidence_ref"],
                        "global_evidence_id": chunk["meta"]["global_evidence_id"]} for chunk in chunks]
    assert all(row["content"].encode("utf-8") == chunk["content"].encode("utf-8") for chunk in chunks)
    assert replay.optional == replay.optional_body_refs == []
    assert chunks == original


def _preset(limit=100_000):
    from proxy.services.model_execution_preset_service import ModelExecutionPreset
    return ModelExecutionPreset(
        preset_id="literal-pointer-replay", model_family="fixture", input_token_limit=limit,
        generation_reserve_tokens=100, safety_reserve_tokens=100, normal_tool_count=5,
        max_tools=5, max_batch_items=6, parallel_read_limit=1, reasoning_enabled=False,
        source_chain=("test",),
    )


def test_actual_governor_wire_is_smaller_and_all_mandatory_inventory_refs_remain(monkeypatch):
    from proxy.services import chat_evidence_application_service as application
    from proxy.services.context_governor_service import conservative_token_estimate
    chunks = [SimpleNamespace(**_chunk(f"Q{index}.H1", title="literal immutable long pointer " * 30))
              for index in range(1, 61)]
    original = copy.deepcopy(chunks)
    context = dict(preset=_preset(), profile_prefix="literal profile", request_payload="literal question",
                   source_context=["literal complete attachment"], chunks=chunks)

    messages, packet, inventory, bodies = application.govern_model_read_messages(**context)
    replay = prepare_model_read_replay(chunks)
    unshared_required = copy.deepcopy(replay.required)
    unshared_required[2] = "Deferred identity pointers; read_norm_card/read_source remain available:\n" + "\n".join(
        chunk.content for chunk in chunks)
    monkeypatch.setattr(application, "prepare_model_read_replay", lambda *args, **kwargs:
                        type(replay)(unshared_required, replay.optional, replay.inventory_refs,
                                     replay.exact_body_refs, replay.optional_body_refs))
    old_messages, old_packet, old_inventory, old_bodies = application.govern_model_read_messages(**context)

    assert inventory == old_inventory == [chunk.meta["model_evidence_ref"] for chunk in chunks]
    assert bodies == old_bodies == []
    assert packet.included_tokens < old_packet.included_tokens
    assert conservative_token_estimate(json.dumps(messages, ensure_ascii=False)) < conservative_token_estimate(
        json.dumps(old_messages, ensure_ascii=False))
    assert _restore(_records(replay.required)) == [json.loads(chunk.content) for chunk in chunks]
    assert [vars(chunk) for chunk in chunks] == [vars(chunk) for chunk in original]


@pytest.mark.asyncio
async def test_shared_inventory_preserves_delivery_bindings_and_exact_read_handles(monkeypatch):
    from proxy.services import chat_evidence_application_service as application
    from proxy.services import model_research_tool_service as research
    code = "ГЭСН99-01-001-01"
    chunks = [SimpleNamespace(**_chunk(ref, norm_code=code)) for ref in ("Q1.H1", "Q2.H1", "Q3.H1")]
    original = copy.deepcopy(chunks)
    calls = []

    def exact_reader(**args):
        calls.append(args)
        return {"status": "ok", "card": {
            "norm_key": "literal-key", "norm_code": code, "source_ref": "literal-exact-source",
            "title": "Literal exact card", "measure_unit": "м³", "work_steps": ["Literal condition"],
            "resources": [{"code": "literal-resource", "unit": "m", "per_unit": 0.125}],
            "resource_count": 1, "resources_returned": 1, "resources_complete": True,
            "resource_consumption_known": True,
        }, "missing": [], "warnings": []}

    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **kwargs: [])
    reader = research.ModelResearchToolService(
        retrieve=lambda **kwargs: pytest.fail("No search requested"), frozen_dataset_ids=("literal-dataset",),
        retrieval_kwargs={}, fallback=lambda *args: pytest.fail("No fallback requested"), norm_card_reader=exact_reader)
    reader.register_shown_norm_cards(chunks)
    exact_call = {"tool": "read_norm_card", "args": {"norm_key": "literal-key"}}
    assert (await reader.execute(exact_call)).chunks == ()
    assert calls == []
    messages, _, inventory, bodies = application.govern_model_read_messages(
        preset=_preset(), profile_prefix="literal profile", request_payload="literal question",
        source_context=["literal attachment"], chunks=chunks)
    assert "same_pointer_fields_as" in str(messages)
    assert [vars(chunk) for chunk in chunks] == [vars(chunk) for chunk in original]
    application.confirm_model_read_delivery(chunks, inventory_refs=inventory, body_refs=bodies)
    assert bodies == []
    assert all(chunk.meta["model_inventory_delivery_status"] == "delivered" for chunk in chunks)
    assert all(chunk.meta["model_delivery_status"] == "prepared" for chunk in chunks)
    row, = application.bind_row_evidence_ids(
        [{"source_row": "literal!R1", "norm_code": code, "evidence_refs": inventory}], chunks)
    assert row["evidence_bindings"] == {chunk.meta["model_evidence_ref"]: chunk.meta["global_evidence_id"]
                                        for chunk in chunks}
    assert row["_evidence_check"]["card_body_shown"] is False
    reader.register_shown_norm_cards(chunks)
    exact = await reader.execute(exact_call)
    assert calls == [{"norm_key": "literal-key", "norm_code": code}]
    assert '"per_unit": 0.125' in exact.chunks[0].content
    _, exact_chunks, _ = application.bind_model_requested_read_evidence(
        [exact], existing_chunks=chunks, evidence_namespace="literal-exact-read")
    replay = prepare_model_read_replay([*chunks, *exact_chunks])
    assert replay.exact_body_refs == [exact_chunks[0].meta["model_evidence_ref"]]
    exact_row, = replay.required[1]["previously_shown_evidence_registry"]
    assert exact_row["content"] == exact.chunks[0].content
    assert exact_row["global_evidence_id"] == exact_chunks[0].meta["global_evidence_id"]
    assert exact_row["normative_card_complete"] is True
    assert [chunk.meta["global_evidence_id"] for chunk in chunks] == [chunk.meta["global_evidence_id"] for chunk in original]
