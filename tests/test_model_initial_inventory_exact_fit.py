"""Exact whole-wire inventory expansion cannot displace admitted evidence."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from proxy.services import model_rag_grouped_evidence_service as grouped
from proxy.services.chat_evidence_application_service import (
    govern_inference_messages, govern_model_rag_initial_messages,
    build_model_rag_evidence_groups, measured_connection_revision,
)
from proxy.services.model_execution_preset_service import ModelExecutionPreset


def _hits():
    return [
        (f"literal query {q}", [SimpleNamespace(
            content=f"literal whole preview {q}/{h}: " + "resource composition " * 15,
            doc_id=f"doc-{q}-{h}", doc_name="fixture", score=float(7-h),
            meta={"norm_key":f"key-{q}-{h}", "norm_code":f"code-{q}-{h}",
                  "title":f"literal title {q}/{h}", "measure_unit":"100 m2",
                  "source_ref":f"literal-source-{q}-{h}", "resources_complete":False,
                  "resource_preview":[{"code":"r0", "per_unit":0}]})
          for h in range(1,7)]) for q in range(1,23)]


def _context():
    return dict(preset=ModelExecutionPreset("wire-test", "fixture", 30000, 2000,
                 1000, 1, 5, 6, 1, False, ("fixture",)),
                profile_prefix="literal profile", request_payload="literal task",
                native_tools=[{"type":"function", "function":{"name":"read_norm_card",
                   "description":"literal schema", "parameters":{"type":"object"}}}],
                dialogue=["literal dialogue"])


def _count(tokens):
    seen=[]
    async def count(messages):
        digest=hashlib.sha256(json.dumps(messages,sort_keys=True).encode()).hexdigest()
        assert digest not in seen
        seen.append(digest)
        return SimpleNamespace(tokens=tokens, source="bound-tokenizer", model_id="fixture-model",
             connection_revision_id="fixture:r8", model_identity_sha256="a"*64, wire_sha256=digest)
    return count,seen


async def _run(counter, *, reserved=5000):
    hits=_hits(); before=copy.deepcopy(hits); context=_context(); source=["whole attachment"]
    old=build_model_rag_evidence_groups(hits,max_chars=7000,hits_per_query=6)
    result=await govern_model_rag_initial_messages(
        count_messages=counter, query_hits=hits, evidence_groups=old[0],
        evidence_chunks=old[1], omitted_refs=old[2], max_chars=7000,
        inventory_chars_limit=120000, hits_per_query=6, source_context=source,
        native_read_reserved_tokens=reserved, **context)
    assert hits==before
    return result, old, govern_inference_messages(**context,required_evidence=[*source,*old[0]])


@pytest.mark.asyncio
async def test_exact_count_expands_132_inventory_without_losing_any_whole_preview():
    count,seen=_count(21000)
    result,old,_legacy=await _run(count)
    messages,packet,groups,chunks,omitted,trace=result
    # Governor measures the required whole frame, then the same frame with
    # optional literal dialogue; it never measures 132 separate cards.
    assert trace["status"]=="expanded" and len(seen)==2
    assert len(chunks)==132 and len(chunks)>len(old[1])
    old_bodies={c.meta["model_evidence_ref"]:c.content for c in old[1] if c.meta["body_status"]=="full"}
    new_bodies={c.meta["model_evidence_ref"]:c.content for c in chunks if c.meta["body_status"]=="full"}
    assert new_bodies==old_bodies and len(new_bodies)==6
    assert len(omitted)==126
    assert all(c.meta["normative_card_complete"] is False for c in chunks)
    assert "whole attachment" in messages[-1]["content"]
    assert "literal dialogue" in messages[-1]["content"]
    assert packet.input_budget_tokens==27000 and packet.provider_payload_tokens==0
    assert packet.included_tokens+5000<=packet.input_budget_tokens
    assert packet.token_count_binding["distinct_count_requests"]==2
    assert measured_connection_revision(packet)=="fixture:r8"
    assert [c.meta["model_evidence_ref"] for c in chunks]==[f"Q{q}.H{h}" for q in range(1,23) for h in range(1,7)]


@pytest.mark.asyncio
@pytest.mark.parametrize("tokens,expected",[(22001,"native_read_reserve"),(27001,"input_capacity")])
async def test_failed_exact_fit_keeps_original_page_and_messages_byte_for_byte(tokens,expected):
    count,_seen=_count(tokens)
    result,old,legacy=await _run(count)
    messages,packet,groups,chunks,omitted,trace=result
    assert trace["status"]=="unchanged" and trace["reason"]==expected
    assert messages==legacy[0] and packet==legacy[1]
    assert (groups,chunks,omitted)==old
    assert measured_connection_revision(packet)==""


@pytest.mark.asyncio
async def test_exact_fit_does_not_spend_legacy_initial_compatibility_headroom():
    count,_seen=_count(22000)
    result,old,legacy=await _run(count)
    # Whole-wire counting includes tools, so its physical budget is 27000.
    # The original conservative allocation left extra schema headroom; initial
    # expansion must keep it without subtracting tools twice in the Governor.
    trace=result[5]
    assert trace["exact_wire_input_budget_tokens"]==27000
    assert trace["original_input_budget_tokens"]==legacy[1].input_budget_tokens<27000
    assert 22000+5000>trace["initial_admission_budget_tokens"]
    assert trace["compatibility_headroom_tokens"]>0
    assert trace["reason"]=="initial_compatibility_headroom"
    assert result[:2]==legacy and result[2:5]==old


@pytest.mark.asyncio
async def test_unsupported_counter_keeps_original_page_and_messages_byte_for_byte():
    async def unsupported(messages): return None
    result,old,legacy=await _run(unsupported)
    assert result[:2]==legacy and result[2:5]==old
    assert result[5]["reason"]=="counter_unavailable"


@pytest.mark.asyncio
async def test_no_counter_does_not_attempt_any_exact_expansion():
    result,old,legacy=await _run(None)
    assert result[:2]==legacy and result[2:5]==old
    assert result[5]["reason"]=="counter_unavailable"


@pytest.mark.asyncio
async def test_registered_char_limit_is_still_a_hard_boundary():
    from proxy.services.chat_evidence_application_service import _model_rag_full_groups
    hits=_hits(); groups,_=_model_rag_full_groups(hits,hits_per_query=6)
    page=grouped.plan_full_group_page(groups,7000)
    expanded=grouped.inventory_expansion_page(groups,page)
    assert expanded.rendered_chars>7000 and page.rendered_chars<=7000
    count,seen=_count(100)
    context=_context();old=build_model_rag_evidence_groups(hits,max_chars=7000,hits_per_query=6)
    result=await govern_model_rag_initial_messages(count_messages=count,query_hits=hits,
         evidence_groups=old[0],evidence_chunks=old[1],omitted_refs=old[2],max_chars=7000,
         inventory_chars_limit=7000,hits_per_query=6,source_context=["whole attachment"],**context)
    assert result[5]["reason"]=="registered_char_capacity" and seen==[]


@pytest.mark.asyncio
async def test_registered_zero_char_limit_remains_unbounded():
    hits=_hits(); count,seen=_count(100)
    old=build_model_rag_evidence_groups(hits,max_chars=7000,hits_per_query=6)
    result=await govern_model_rag_initial_messages(count_messages=count,query_hits=hits,
         evidence_groups=old[0],evidence_chunks=old[1],omitted_refs=old[2],max_chars=7000,
         inventory_chars_limit=0,hits_per_query=6,source_context=["whole attachment"],**_context())
    assert result[5]["status"]=="expanded" and len(result[3])==132 and seen


def test_expansion_preserves_preview_metadata_and_literal_empty_query_order():
    from proxy.services.chat_evidence_application_service import _model_rag_full_groups
    hits=_hits(); groups,_=_model_rag_full_groups(hits,hits_per_query=6)
    groups.insert(3,grouped.EvidenceGroup("literal empty query after the admitted prefix",[]))
    page=grouped.plan_full_group_page(groups,7000)
    before=copy.deepcopy(groups)
    expanded=grouped.inventory_expansion_page(groups,page)
    assert groups==before
    assert expanded.body_by_ref==page.body_by_ref
    assert expanded.body_refs==page.body_refs
    assert expanded.shared_refs==page.shared_refs
    assert expanded.unshown_refs==[]
    assert all(expanded.meta_by_ref[r]==page.meta_by_ref[r] for r in page.body_refs)
    text="\n\n".join(expanded.groups)
    assert "literal empty query after the admitted prefix\n\nhits=0" in text
    assert text.index("literal query 3")<text.index("literal empty query after")<text.index("literal query 4")


def test_expansion_preserves_already_shown_deferred_preview_pointer_metadata():
    cards=[]
    for n in range(12):
        ref=f"Q{n//2+1}.H{n%2+1}"
        meta={"norm_key":ref,"norm_code":ref,"title":"literal title",
              "measure_unit":"m","source_ref":f"literal-source-{n}",
              "resources_complete":True,"resources_returned":1,
              "resources":[{"code":"r0","per_unit":0}],"exact_card_read":True}
        preview={k:v for k,v in meta.items() if k not in
                 {"resources","resources_complete","resources_returned"}}
        preview.update(resource_preview=[{"code":"r0"}],exact_card_read=False)
        cards.append(grouped.EvidenceCard(ref,ref,ref,"whole resource "*8000,meta,
                     "literal preview "*12,preview))
    groups=[grouped.EvidenceGroup(f"literal query {q}",cards[q*2:q*2+2]) for q in range(6)]
    previews=[grouped.EvidenceGroup(g.header,[grouped.EvidenceCard(c.ref,c.header,
              c.identity,c.preview_content,c.preview_meta) for c in g.cards]) for g in groups]
    budget=grouped._render(previews,{c.ref for c in cards[:5]},1).rendered_chars
    admitted=grouped.plan_full_group_page(groups,budget)
    assert admitted.body_refs and set(admitted.inventory_refs)-set(admitted.body_refs)
    assert admitted.complete_card_deferred_refs and admitted.unshown_refs
    expanded=grouped.inventory_expansion_page(groups,admitted)
    for ref in admitted.inventory_refs:
        assert expanded.pointer_by_ref[ref]==admitted.pointer_by_ref[ref]
        assert expanded.meta_by_ref[ref]==admitted.meta_by_ref[ref]
        assert expanded.meta_by_ref[ref]["exact_card_read"] is False
    assert expanded.body_by_ref==admitted.body_by_ref


def test_expansion_rejects_unknown_or_repeated_retained_references():
    from dataclasses import replace
    from proxy.services.chat_evidence_application_service import _model_rag_full_groups
    hits=_hits(); groups,_=_model_rag_full_groups(hits,hits_per_query=6)
    page=grouped.plan_full_group_page(groups,7000)
    with pytest.raises(ValueError,match="unique retained"):
        grouped.inventory_expansion_page(groups,replace(page,inventory_refs=[*page.inventory_refs,"unknown"]))
    with pytest.raises(ValueError,match="unique retained"):
        grouped.inventory_expansion_page([*groups,groups[0]],page)


@pytest.mark.asyncio
async def test_changed_bound_owner_does_not_admit_the_expanded_frame():
    requests=[]
    async def changed(messages):
        requests.append(messages)
        return SimpleNamespace(tokens=100,source="bound-tokenizer",model_id="fixture-model",
           connection_revision_id="fixture:r8" if len(requests)==1 else "fixture:r9",
           model_identity_sha256="a"*64,wire_sha256="b"*64)
    result,old,legacy=await _run(changed)
    assert result[:2]==legacy and result[2:5]==old
    assert result[5]["reason"]=="counter_identity_changed"
