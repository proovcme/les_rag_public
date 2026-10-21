"""A composer hint belongs to exact open operations, not a document-wide review."""
import ast
import asyncio
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from proxy.routers import chat
from proxy.services import chat_evidence_application_service as application
from proxy.services.workbook_research_job_service import WorkbookResearchJobService
from sovushka.pages import chat as page
from tests.test_workbook_gap_followup_955 import baseline, identity, SOURCE


def request_for(store, job, hint="Literal engineer hint\nwithout coordinates"):
    target = job["accepted_rows"][1]
    fresh = store.get(job["job_id"], include_retry_token=True)
    return chat.LsrPatchRequest(session_id=job["identity"]["session_id"], job_id=job["job_id"],
        attachment_id=job["identity"]["attachment_id"], question=job["task_context"]["original_question"],
        reopen_locators=[target["source_row"]], research_operation_ids=[target["operation_id"]],
        preserve_accepted=True, repack=False, review_instruction=hint, expected_retry_state=fresh["retry_state_sha256"])


@pytest.mark.asyncio
async def test_literal_hint_keeps_closed_shared_anchor_prices_and_the_saved_question(tmp_path, monkeypatch):
    store, original = baseline(tmp_path)
    monkeypatch.setattr(chat, "WorkbookResearchJobService", lambda: store)
    req = request_for(store, original)
    progress = await chat.get_workbook_research(original["job_id"], view="progress", _user=SimpleNamespace())
    assert progress["retry_state_sha256"] == req.expected_retry_state
    assert "evidence" not in progress and "query_cache" not in progress
    result = await chat.patch_lsr_rows(req, _user=SimpleNamespace())
    current = result["job"]
    assert result["model_called"] is False and current["accepted_rows"] == original["accepted_rows"]
    assert current["task_context"]["price_basis"] == original["task_context"]["price_basis"]
    assert current["evidence"] == original["evidence"] and current["query_cache"] == original["query_cache"]
    assert store.pending_research_operation_ids(current) == {original["accepted_rows"][1]["operation_id"]}
    context = store.chat_review_context(current["job_id"])
    assert context["message"] == req.review_instruction and context["prior_rows"] == [original["accepted_rows"][1]]
    note = store.list_events(current["job_id"], "locators_reopened")[-1]["payload"]["chat_review"]
    assert note["request_sha256"] == hashlib.sha256(req.question.encode("utf-8")).hexdigest()
    assert note["review_scope"] == "operations"
    resumed = WorkbookResearchJobService(store.db_path).begin_or_resume(identity(store, req.question))
    assert not application.workbook_chat_review_needed(req.question, resumed, store.list_events_with_lineage(resumed["job_id"]))
    assert store.chat_review_context(resumed["job_id"])["message"] == req.review_instruction


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["running", "changed_state", "new_packaging"])
async def test_api_rechecks_running_and_opaque_state_inside_the_reopen_transaction(tmp_path, monkeypatch, race):
    store, original = baseline(tmp_path)
    req = request_for(store, original)
    before_get = store.get
    fired = False
    def stale_get(job_id, **kwargs):
        nonlocal fired
        result = before_get(job_id, **kwargs)
        if not fired:
            fired = True
            if race == "running":
                store.reopen_locators(job_id, [SOURCE], preserve_accepted=True, operation_ids=req.research_operation_ids)
                store.begin_or_resume(identity(store))
            elif race == "changed_state":
                store.record_overrides(job_id, {SOURCE: {"confirmed_price": 42}})
            else:
                store.record_packaging(job_id, tool="build_lsr_workbook", revision_id="new_revision", draft=False)
        return result
    monkeypatch.setattr(store, "get", stale_get)
    monkeypatch.setattr(chat, "WorkbookResearchJobService", lambda: store)
    with pytest.raises(HTTPException) as caught:
        await chat.patch_lsr_rows(req, _user=SimpleNamespace())
    assert caught.value.status_code == 409
    current = before_get(original["job_id"])
    assert current["accepted_rows"] == original["accepted_rows"]
    assert store.chat_review_context(current["job_id"]).get("message") != req.review_instruction
    if race == "running":
        assert current["status"] == "running"
    else:
        assert current["status"] == "complete" and current["remaining"] == []


def test_pending_hint_intersects_exact_ids_and_preserves_nullable_and_unassigned_scope():
    job = {"job_id":"own", "status":"paused", "identity":{"session_id":"s","attachment_id":"a"},
        "remaining":["S!R2","S!R9"], "retry_state_sha256":"a"*64,
        "accepted_rows":[{"source_row":"S!R2","operation_id":"closed"},
                         {"source_row":"S!R2","operation_id":"open"},
                         {"source_row":"S!R9","operation_id":"other"}],
        "task_context":{"pending_research_operation_ids":["open","other"],
                        "pending_research_locators":["S!R2","S!R9"],"pending_research_unassigned_locators":[]}}
    resume = {"job_id":"own","session_id":"s","question":"Original task",
              "research_locators":["S!R2","S!R100"],"research_operation_ids":["closed","open","other"]}
    before = deepcopy((job,resume))
    result = page.lsr_gap_retry_reopen_payload(resume,job,review_instruction="Hint")
    assert result["reopen_locators"] == ["S!R2"] and result["research_operation_ids"] == ["open"]
    assert result["question"] == "Original task" and result["review_instruction"] == "Hint"
    assert (job,resume) == before
    resume["research_operation_ids"] = []
    assert page.lsr_gap_retry_reopen_payload(resume,job,review_instruction="Hint") is None
    job["task_context"]["pending_research_unassigned_locators"] = ["S!R2"]
    assert page.lsr_gap_retry_reopen_payload(resume,job,review_instruction="Hint")["research_operation_ids"] == []


class Widget:
    def __init__(self,value=""):
        self.value=value
        self.updates=0
    def update(self): self.updates+=1
    def set_text(self,value): pass
    def set_visibility(self,value): pass


def ui_handler(*, failure=None, change=None):
    tree = ast.parse(Path(page.__file__).read_text(encoding="utf-8"))
    names = {"_resume_lsr_packets", "_refine_lsr_rows", "_repack_lsr_from_ui", "_register_artifact_downloads"}
    nodes = [item for item in ast.walk(tree) if isinstance(item,(ast.AsyncFunctionDef,ast.FunctionDef)) and item.name in names]
    composer=Widget("Engineer hint\nexact wording")
    job={"job_id":"own","status":"complete","identity":{"session_id":"s","attachment_id":"a"},
         "remaining":[],"accepted_rows":[],"held_packet":{},"task_context":{},
         "retry_state_sha256":"a"*64,"retry_document_revision_id":"rev_own"}
    resume={"job_id":"own","session_id":"s","attachment_id":"a","question":"Original task",
            "research_locators":["S!R2"],"research_operation_ids":["open"]}
    posts,sends,notices=[],[],[]
    scope={"session_id":"s"}
    attachment={"id":"a"}
    sending={"v":False}
    gate=asyncio.Event()
    async def get(_path):
        if change=="wait": await gate.wait()
        if change=="new_text": composer.value="New text typed while awaiting the server"
        if change=="session": scope["session_id"]="other"
        if change=="attachment": attachment["id"]="other"
        if change=="sending": sending["v"]=True
        if change=="stale": job["retry_document_revision_id"]="rev_new"
        if change=="get_none": return None
        return deepcopy(job)
    async def post(path,payload):
        posts.append(deepcopy(payload))
        if change=="post_session": scope["session_id"]="other"
        if path=="/api/chat/repack-lsr":
            if failure: return None
            job.update(retry_document_rows_current=True,retry_document_revision_id="rev_refreshed")
            return {"model_called":False,"harvested":{"artifact":{"artifact_kind":"lsr_workbook",
                "revision_id":"rev_refreshed","result_readiness":deepcopy(resume),"resume":deepcopy(resume)}}}
        return None if failure else {"model_called":False,"job":job}
    async def send(question,**kwargs):
        sends.append({"question":question,**kwargs})
        page.consume_lsr_resume_input(composer,kwargs["composer_snapshot"])
    namespace={"_sending":sending,"_lsr_resume_inflight":{"v":False},"chat_input":composer,
        "state":scope,"attach_state":attachment,"_lsr_card_state":{"artifact":{"revision_id":"rev_own","result_readiness":resume}},
        "_notify":lambda text,**kwargs:notices.append(text),"api_get":get,"api_post":post,"_do_send":send,
        "merge_lsr_resume_payload":page.merge_lsr_resume_payload,
        "lsr_explicit_resume_reopen_payload":page.lsr_explicit_resume_reopen_payload,
        "lsr_gap_retry_reopen_payload":page.lsr_gap_retry_reopen_payload,
        "format_lsr_resume_display":page.format_lsr_resume_display,"last_api_error_text":lambda text:text,
        "resolve_lsr_position_selectors":page.resolve_lsr_position_selectors,
        "artifact_workbook_files":lambda _artifact:[],"_file_artifacts":{},
        "_register_file_artifact":lambda *args,**kwargs:None,"_last_estimator_resume":{},
        "lsr_readiness_card_spec":lambda _ready:{"file_action":True,"actions":["resume"]},
        "_smeta_approval_payloads":{},"_smeta_approval_cards":set(),"_rebuild_files_artifacts_panel":lambda:None,
        "_attachment_visible_text":lambda pending:("Source","Source",None),
        "attach_title":Widget(),"attach_chip":Widget(),"attach_strip":Widget()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),"<actual-ui-handler>","exec"),namespace)
    return SimpleNamespace(run=namespace["_resume_lsr_packets"],resume=resume,composer=composer,
        posts=posts,sends=sends,notices=notices,gate=gate,namespace=namespace,job=job)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None,"new_text"])
async def test_actual_handler_captures_hint_before_await_and_consumes_only_that_text(change):
    ui=ui_handler(change=change)
    await ui.run(ui.resume)
    assert len(ui.posts)==len(ui.sends)==1
    assert ui.posts[0]["review_instruction"]=="Engineer hint\nexact wording"
    assert ui.posts[0]["research_operation_ids"]==["open"]
    assert ui.sends[0]["question"]=="Original task"
    assert "Engineer hint\nexact wording" in ui.sends[0]["display_question"]
    assert ui.sends[0]["resume_binding"]==("s","a")
    assert ui.composer.value==("" if change is None else "New text typed while awaiting the server")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["session","attachment","sending","stale"])
async def test_actual_handler_rejects_stale_or_changed_scope_without_consuming_hint(change):
    ui=ui_handler(change=change)
    await ui.run(ui.resume)
    assert not ui.posts and not ui.sends
    assert ui.composer.value=="Engineer hint\nexact wording"


@pytest.mark.asyncio
async def test_actual_handler_failed_patch_and_double_click_preserve_one_owned_send():
    failed=ui_handler(failure=True)
    await failed.run(failed.resume)
    assert len(failed.posts)==1 and not failed.sends and failed.composer.value=="Engineer hint\nexact wording"
    ui=ui_handler(change="wait")
    first=asyncio.create_task(ui.run(ui.resume))
    await asyncio.sleep(0)
    await ui.run(ui.resume)
    assert not ui.posts and not ui.sends
    ui.gate.set()
    await first
    assert len(ui.posts)==len(ui.sends)==1
    assert ui.namespace["_lsr_resume_inflight"]["v"] is False


@pytest.mark.asyncio
async def test_session_change_after_patch_leaves_the_hint_durable_without_sending_to_another_chat():
    ui=ui_handler(change="post_session")
    await ui.run(ui.resume)
    assert len(ui.posts)==1 and not ui.sends and ui.composer.value=="Engineer hint\nexact wording"


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", ["", "Engineer hint\nexact wording"])
async def test_active_packet_resume_keeps_existing_no_hint_path_and_bounds_new_hint_to_remaining(hint):
    ui=ui_handler()
    ui.composer.value=hint
    ui.job.update(status="paused",remaining=["S!R2"],held_packet={"locators":["S!R2"]})
    ui.resume["research_operation_ids"]=[]
    await ui.run(ui.resume)
    assert len(ui.sends)==1
    if hint:
        assert len(ui.posts)==1 and ui.posts[0]["reopen_locators"]==["S!R2"]
        assert ui.posts[0]["research_operation_ids"]==[]
    else:
        assert not ui.posts


@pytest.mark.asyncio
async def test_empty_fresh_gap_scope_does_not_dispatch_the_hint_as_a_document_review():
    ui=ui_handler()
    ui.resume["research_locators"]=[]
    ui.resume["research_operation_ids"]=[]
    await ui.run(ui.resume)
    assert not ui.posts and not ui.sends and ui.composer.value=="Engineer hint\nexact wording"


@pytest.mark.asyncio
async def test_actual_native_result_after_scoped_hint_revises_only_the_requested_identity(tmp_path,monkeypatch):
    from tests import test_model_rag_sheet_evidence_reads as fixture
    from tests.test_vor_native_terminal_workflow_962 import _lsr_rows
    from proxy.services.openai_compatible_transport_service import InferenceResponse

    run=await fixture._run_sheet(tmp_path,monkeypatch,reads=False,
        query_declaration=json.dumps({"artifact_kind":"lsr","queries":["Literal resource search"]}),
        final_answer=json.dumps({"artifact_kind":"lsr","rows":_lsr_rows()}))
    store=WorkbookResearchJobService()
    parent=store.get(run.result["retrieval_trace"]["workbook_research_job"]["job_id"])
    old=deepcopy(parent["accepted_rows"])
    request=inspect.getclosurevars(run.resume_same_request).nonlocals["request"].req
    fresh=store.get(parent["job_id"],include_retry_token=True)
    monkeypatch.setattr(chat,"WorkbookResearchJobService",lambda:store)
    await chat.patch_lsr_rows(chat.LsrPatchRequest(session_id=parent["identity"]["session_id"],job_id=parent["job_id"],
        attachment_id=parent["identity"]["attachment_id"],question=request.question,reopen_locators=[old[1]["source_row"]],
        research_operation_ids=[old[1]["operation_id"]],preserve_accepted=True,repack=False,
        review_instruction="Check only the open resource description",expected_retry_state=fresh["retry_state_sha256"]),_user=SimpleNamespace())
    revised={**old[1],"expected_revision":old[1]["revision"],"title":"Explicit model revised description"}
    revised["supply_resource_match"] = fixture._supply_resource_match(
        revised["title"], revised["resource_code"], revised["evidence_refs"])
    native=fixture._native("build_lsr_workbook",attachment_id=parent["identity"]["attachment_id"],decisions=[revised])
    run.responses.extend([
        InferenceResponse(text=json.dumps({"artifact_kind":"lsr","queries":["Literal resource search"]}),tool_calls=(),finish_reason="stop",usage={}),
        InferenceResponse(text="",tool_calls=(native,),finish_reason="tool_calls",usage={"completion_tokens":120})])
    result=await run.resume_same_request()
    current=store.get(result["retrieval_trace"]["workbook_research_job"]["job_id"])
    assert current["accepted_rows"][0]==old[0]
    assert current["accepted_rows"][1]["operation_id"]==old[1]["operation_id"]
    assert current["accepted_rows"][1]["revision"]==old[1]["revision"]+1
    assert current["accepted_rows"][1]["title"]==revised["title"]
    assert current["task_context"]["price_basis"]==parent["task_context"]["price_basis"]
    assert "Check only the open resource description" in str(run.requests[-1].messages)
    assert not result["retrieval_trace"].get("chat_refinement")
    assert not store.pending_research_operation_ids(current)


@pytest.mark.asyncio
@pytest.mark.parametrize("narrower", [False, True])
async def test_an_empty_retry_retains_the_literal_hint_only_within_its_original_operation_scope(tmp_path,monkeypatch,narrower):
    store, original = baseline(tmp_path,shared=3)
    monkeypatch.setattr(chat,"WorkbookResearchJobService",lambda:store)
    first = request_for(store,original)
    first.research_operation_ids = [row["operation_id"] for row in original["accepted_rows"][1:3]]
    await chat.patch_lsr_rows(first,_user=SimpleNamespace())
    second = request_for(store,original,hint="")
    if not narrower: second.research_operation_ids = first.research_operation_ids
    await chat.patch_lsr_rows(second,_user=SimpleNamespace())
    restarted = WorkbookResearchJobService(store.db_path)
    assert restarted.chat_review_context(original["job_id"])["message"] == first.review_instruction
    event = restarted.list_events(original["job_id"],"locators_reopened")[-1]["payload"]
    assert event["chat_review"]["instruction_origin"] == "retained_user_scope"
    assert {row["operation_id"] for row in event["prior_rows"]} == set(second.research_operation_ids)
    assert restarted.get(original["job_id"])["accepted_rows"] == original["accepted_rows"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["sibling", "unassigned", "other_source", "expanded", "document_note"])
async def test_empty_retry_does_not_apply_an_old_hint_to_unrelated_operations(tmp_path,monkeypatch,change):
    store, original = baseline(tmp_path)
    monkeypatch.setattr(chat,"WorkbookResearchJobService",lambda:store)
    first=request_for(store,original)
    await chat.patch_lsr_rows(first,_user=SimpleNamespace())
    if change=="document_note":
        store.reopen_locators(original["job_id"],[SOURCE],preserve_accepted=True,
            operation_ids=first.research_operation_ids,
            chat_review={"message":first.review_instruction,"decision_author":"user","review_scope":"document",
                         "request_sha256":hashlib.sha256(first.question.encode()).hexdigest()})
    second=request_for(store,original,hint="")
    if change=="sibling": second.research_operation_ids=[original["accepted_rows"][0]["operation_id"]]
    if change=="unassigned": second.research_operation_ids=[]
    if change in {"other_source","expanded"}:
        other=original["accepted_rows"][-1]
        second.reopen_locators=([SOURCE] if change=="expanded" else [])+[other["source_row"]]
        second.research_operation_ids=([first.research_operation_ids[0]] if change=="expanded" else [])+[other["operation_id"]]
    await chat.patch_lsr_rows(second,_user=SimpleNamespace())
    assert store.chat_review_context(original["job_id"])["message"] != first.review_instruction


@pytest.mark.parametrize("change", ["decision_revision", "rows_replaced", "packet_revision", "destructive_reopen", "no_op_reopen", "no_op_packet", "search_cache"])
def test_progress_binds_the_card_to_packaged_operation_revisions_not_the_latest_get_token(tmp_path,change):
    store,original=baseline(tmp_path)
    old=original["accepted_rows"][1]
    assert store.get(original["job_id"],include_retry_token=True)["retry_document_rows_current"] is True
    if change=="decision_revision":
        store.record_revision(original["job_id"],operation_id=old["operation_id"],decision={**old,"title":"New authored title"})
    elif change=="rows_replaced":
        store.replace_accepted_rows(original["job_id"],[{**old,"title":"New authored title"}])
    elif change in {"packet_revision","no_op_packet"}:
        if change=="packet_revision":
            store.reopen_locators(original["job_id"],[SOURCE],preserve_accepted=True,operation_ids=[old["operation_id"]])
        store.record_packet(original["job_id"],sheet="Sheet",packet_locators=[SOURCE],
            accepted_rows=[{**old,**({"title":"New authored title","expected_revision":old["revision"]} if change=="packet_revision" else {})}],
            evidence=[],remaining=[])
    elif change=="destructive_reopen": store.reopen_locators(original["job_id"],[SOURCE])
    elif change=="no_op_reopen": store.reopen_locators(original["job_id"],["Unassigned!R99"])
    else: store.record_search_cache(original["job_id"],{"Another query":[]})
    progress=store.get(original["job_id"],include_retry_token=True)
    if change=="packet_revision":
        assert progress["accepted_rows"][1]["revision"]==old["revision"]+1
    assert progress["retry_document_revision_id"]=="rev_before_955"
    assert progress["retry_document_rows_current"] is (change in {"no_op_reopen","no_op_packet","search_cache"})
    assert "retry_document_rows_current" not in store.get(original["job_id"])
    if not progress["retry_document_rows_current"]:
        with pytest.raises(ValueError,match="Сохранённые решения новее файла"):
            page.lsr_gap_retry_reopen_payload({"job_id":original["job_id"],"session_id":original["identity"]["session_id"],
                "research_locators":[SOURCE],"research_operation_ids":[old["operation_id"]]},progress)
    store.record_packaging(original["job_id"],tool="build_lsr_workbook",revision_id="current_revision",draft=False)
    assert store.get(original["job_id"],include_retry_token=True)["retry_document_rows_current"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False,True])
async def test_stale_card_repackages_saved_rows_once_without_model_retry_or_consuming_the_hint(failure):
    ui=ui_handler(failure=failure)
    ui.job["retry_document_rows_current"]=False
    await ui.run(ui.resume)
    assert not ui.sends and len(ui.posts)==1
    assert ui.posts[0]["decisions"]==[] and "reopen_locators" not in ui.posts[0]
    assert ui.composer.value=="Engineer hint\nexact wording"
    card=ui.namespace["_lsr_card_state"]["artifact"]
    assert card["revision_id"]==("rev_own" if failure else "rev_refreshed")
    assert ui.namespace["_lsr_resume_inflight"]["v"] is False


@pytest.mark.asyncio
async def test_explicit_refine_preserves_its_selected_scope_instead_of_the_old_gap_card():
    ui=ui_handler()
    ui.resume["row_projection"]=[{"position_no":1,"locator":"S!R8","operation_id":"selected_closed"}]
    ui.job.update(status="paused",remaining=["S!R2"],
        accepted_rows=[{"source_row":"S!R2","operation_id":"old_gap"},{"source_row":"S!R8","operation_id":"selected_closed"}],
        task_context={"pending_research_locators":["S!R2"],"pending_research_operation_ids":["old_gap"]})
    await ui.namespace["_refine_lsr_rows"](ui.resume,"1")
    assert len(ui.posts)==len(ui.sends)==1
    assert ui.posts[0]["reopen_locators"]==["S!R8"] and ui.posts[0]["research_operation_ids"] is None
    assert ui.posts[0]["review_instruction"]=="Engineer hint\nexact wording"
    assert ui.sends[0]["question"]=="Original task"


@pytest.mark.asyncio
async def test_stale_repack_keeps_its_result_out_of_a_new_chat():
    ui=ui_handler(change="post_session")
    ui.job["retry_document_rows_current"]=False
    await ui.run(ui.resume)
    assert len(ui.posts)==1 and not ui.sends
    assert ui.namespace["_lsr_card_state"]["artifact"]["revision_id"]=="rev_own"
    assert ui.composer.value=="Engineer hint\nexact wording"


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["running","get_none","foreign_job","foreign_session"])
async def test_stale_repack_rejects_a_running_foreign_or_unavailable_job_before_any_post(condition):
    ui=ui_handler(change="get_none" if condition=="get_none" else None)
    ui.job["retry_document_rows_current"]=False
    if condition=="running": ui.job["status"]="running"
    if condition=="foreign_job": ui.job["job_id"]="other"
    if condition=="foreign_session": ui.job["identity"]["session_id"]="other"
    await ui.run(ui.resume)
    assert not ui.posts and not ui.sends and ui.composer.value=="Engineer hint\nexact wording"


@pytest.mark.parametrize("event_type", ["packet_checkpoint","rows_replaced","locators_reopened"])
def test_legacy_mutation_without_a_noop_proof_requires_a_saved_row_repack(tmp_path,event_type):
    store,job=baseline(tmp_path)
    with store._connect() as conn:
        store._append_event(conn,job["job_id"],event_type,{})
    assert store.get(job["job_id"],include_retry_token=True)["retry_document_rows_current"] is False
