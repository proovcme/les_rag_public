"""The UI commits every selected source, never a successful upload prefix."""
import ast
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sovushka.pages import chat as page


class Widget:
    def __init__(self, value=""):
        self.value = value
        self.visible = False
        self.text = ""
        self.reset_count = 0
        self.methods = []
    def set_text(self, value): self.text = value
    def set_visibility(self, value): self.visible = value
    def reset(self): self.reset_count += 1
    def run_method(self, method): self.methods.append(method)
    def update(self): pass
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *_args): pass


class SourceFile:
    def __init__(self, name, content=b"literal", gate=None):
        self.name, self.content, self.gate = name, content, gate
    async def read(self):
        if self.gate: await self.gate.wait()
        if isinstance(self.content, Exception): raise self.content
        return self.content


def controller(*, parent_failure=False, wrong_parent=False, parent_gate=None, storage=None, session_id="chat-a"):
    names = {"_attachment_queue", "_persist_attachment_queues", "_restore_attachment_collection",
        "_clear_attachment", "_show_attached_response", "_begin_attach_upload", "_do_attach_batch",
        "_commit_attachment_collection", "_do_attach", "_remove_attachment_member", "_reject_attach_upload",
        "_apply_loaded_session", "_open_session", "send_chat", "_do_send"}
    tree = ast.parse(Path(page.__file__).read_text(encoding="utf-8"))
    nodes = [item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in names]
    storage = {} if storage is None else storage
    queues = deepcopy(storage.get("les_chat_attachment_queues") or {})
    uploads, posts, notices, rendered = [], [], [], []
    current = {"session_id": session_id, "chat_history": []}
    attach_state = {"id": None, "mode": "", "name": "", "text": ""}
    async def post_file(path, content, name, *, params):
        uploads.append((path, bytes(content), name, deepcopy(params)))
        if content == b"api_failure": return None
        return {"attachment_id": "read_" + str(len(uploads)), "mode": params["mode"], "name": name,
                "text": "literal source preview", "chars": 22, "source_extraction_complete": True}
    async def post(path, data):
        posts.append((path, deepcopy(data)))
        if parent_gate: await parent_gate.wait()
        if parent_failure: return None
        ids = data["attachment_ids"]
        members = [{"attachment_id": value, "member_key": str(index), "original_name": "source"}
                   for index, value in enumerate(ids)]
        if wrong_parent: members = members[:-1]
        return {"attachment_id": "read_parent", "mode": "read", "name": "source collection",
            "text": "server-owned manifest preview", "collection": {"schema": "les.chat-attachment-collection.v1",
                "member_count": len(members), "members": members}}
    async def hydrate(**kwargs): pass
    async def get(path): return []
    namespace = {"Any": object, "Optional": object, "inspect": inspect, "json": json, "asyncio": asyncio,
        "state": current, "attach_state": attach_state, "_attachment_queues": queues,
        "app": SimpleNamespace(storage=SimpleNamespace(user=storage)),
        "_upload_batch_context": ContextVar("test_upload_batch", default=None),
        "new_chat_attachment_queue": page.new_chat_attachment_queue,
        "begin_chat_attachment_batch": page.begin_chat_attachment_batch,
        "chat_attachment_batch_current": page.chat_attachment_batch_current,
        "chat_attachment_commit_ids": page.chat_attachment_commit_ids,
        "chat_attachment_queue_block_reason": page.chat_attachment_queue_block_reason,
        "consume_lsr_resume_input": page.consume_lsr_resume_input,
        "_attachment_visible_text": page._attachment_visible_text,
        "_render_attachment_queue": lambda: None,
        "api_post": post, "api_post_file": post_file, "api_get": get,
        "_hydrate_running_workbook_progress": hydrate, "_render_chat_history": lambda text: None,
        "selected_session_card": {"el": None}, "history_drawer": Widget(),
        "last_api_error_text": lambda message: message, "add_log": lambda message: None,
        "ui": SimpleNamespace(notify=lambda text, **kwargs: notices.append(text)),
        "_notify": lambda text, **kwargs: notices.append(text),
        "_render_msg": rendered.append, "_scroll_chat_to_tail": lambda **kwargs: None,
        "chat_column": Widget(), "attach_status": Widget(), "attach_mode": Widget("read"), "attach_dialog": Widget(),
        "attach_title": Widget(), "attach_chip": Widget(), "attach_strip": Widget(), "attachment_picker": Widget(),
        "_sending": {"v": False}, "chat_input": Widget("Build from all sources")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "<actual-collection-ui>", "exec"), namespace)
    async def batch(files):
        namespace["_begin_attach_upload"](None)
        await namespace["_do_attach_batch"](SimpleNamespace(files=files))
    return SimpleNamespace(ns=namespace, batch=batch, queue=lambda sid="chat-a": namespace["_attachment_queue"](sid),
        state=current, attached=attach_state, storage=storage, uploads=uploads, posts=posts, notices=notices, rendered=rendered)


@pytest.mark.asyncio
async def test_multiple_unicode_sources_wait_for_all_uploads_then_commit_automatically_in_order():
    ui = controller()
    gate = asyncio.Event()
    task = asyncio.create_task(ui.batch([SourceFile("План №1.pdf"), SourceFile("Раздел 'А'.docx"), SourceFile("Объёмы Ω.xlsx", gate=gate)]))
    await asyncio.sleep(0)
    assert ui.attached["id"] is None and not ui.posts
    await ui.ns["send_chat"]()
    assert ui.ns["chat_input"].value == "Build from all sources" and ui.notices
    gate.set()
    await task
    assert ui.posts == [("/api/chat/attachment-collections", {"attachment_ids": ["read_1", "read_2", "read_3"]})]
    assert ui.attached["id"] == "read_parent"
    payload = page._attachment_chat_payload(ui.attached)
    assert payload["attachment_id"] == "read_parent" and "server-owned manifest preview" in payload["attachment_context"]
    assert "question" not in payload and "План №1.pdf" not in payload["attachment_context"]
    persisted = json.dumps(ui.storage, ensure_ascii=False)
    assert "literal source preview" not in persisted and "server-owned manifest preview" not in persisted
    assert "План №1.pdf" in persisted and "read_parent" in persisted


@pytest.mark.asyncio
async def test_single_read_file_keeps_the_existing_id_without_creating_a_parent():
    ui = controller()
    await ui.batch([SourceFile("Один файл.pdf")])
    assert ui.attached["id"] == "read_1" and not ui.posts
    assert page.chat_attachment_queue_block_reason(ui.queue()) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [b"api_failure", ValueError("file read failed")])
async def test_one_failed_file_retains_all_members_and_blocks_prefix_success(failure):
    ui = controller()
    await ui.batch([SourceFile("first.pdf"), SourceFile("failed.docx", failure), SourceFile("last.xlsx")])
    members = ui.queue()["batches"][0]["members"]
    assert [item["name"] for item in members] == ["first.pdf", "failed.docx", "last.xlsx"]
    assert [item["status"] for item in members] == ["ready", "failed", "ready"]
    await ui.ns["_commit_attachment_collection"]()
    assert not ui.posts and ui.attached["id"] is None
    assert page.chat_attachment_queue_block_reason(ui.queue())


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_parent", [False, True])
async def test_parent_failure_or_prefix_response_keeps_the_full_selected_list(wrong_parent):
    ui = controller(parent_failure=not wrong_parent, wrong_parent=wrong_parent)
    await ui.batch([SourceFile("A.pdf"), SourceFile("B.rtf")])
    assert len(ui.posts) == 1 and ui.attached["id"] is None
    assert len(ui.queue()["batches"][0]["members"]) == 2 and ui.queue()["error"]
    assert ui.queue()["committing"] is False


@pytest.mark.asyncio
async def test_begin_guard_blocks_send_before_the_batch_body_is_available():
    ui = controller()
    gate = asyncio.Event()
    task = asyncio.create_task(ui.batch([SourceFile("slow.pdf", gate=gate)]))
    await asyncio.sleep(0)
    assert page.chat_attachment_queue_block_reason(ui.queue())
    await ui.ns["send_chat"]()
    assert ui.ns["chat_input"].value == "Build from all sources" and not ui.posts
    gate.set()
    await task
    assert ui.attached["id"] == "read_1"


@pytest.mark.asyncio
async def test_http_context_keeps_concurrent_batches_in_their_original_chat_and_reserved_order():
    ui = controller()
    gate = asyncio.Event()
    first = asyncio.create_task(ui.batch([SourceFile("first.pdf", gate=gate), SourceFile("second.rtf")]))
    await asyncio.sleep(0)
    ui.state["session_id"] = "chat-b"
    await ui.batch([SourceFile("other.xlsx")])
    assert ui.attached["id"] == "read_1"
    gate.set()
    await first
    assert [item["name"] for item in ui.queue()["batches"][0]["members"]] == ["first.pdf", "second.rtf"]
    assert ui.attached["name"] == "other.xlsx"
    ui.state["session_id"] = "chat-a"
    ui.ns["_restore_attachment_collection"]()
    assert ui.posts[-1][1]["attachment_ids"] == ["read_2", "read_3"]


@pytest.mark.asyncio
async def test_clear_invalidates_late_upload_callbacks_without_clearing_another_chat():
    ui = controller()
    gate = asyncio.Event()
    task = asyncio.create_task(ui.batch([SourceFile("late.pdf", gate=gate)]))
    await asyncio.sleep(0)
    ui.ns["_clear_attachment"]()
    await ui.batch([SourceFile("replacement.pdf")])
    gate.set()
    await task
    assert ui.attached["name"] == "replacement.pdf"
    assert len(ui.queue()["batches"]) == 1 and len(ui.uploads) == 1


@pytest.mark.asyncio
async def test_new_selection_during_parent_commit_cannot_publish_an_old_prefix():
    gate = asyncio.Event()
    ui = controller(parent_gate=gate)
    committing = asyncio.create_task(ui.batch([SourceFile("a.pdf"), SourceFile("b.rtf")]))
    await asyncio.sleep(0)
    await ui.batch([SourceFile("c.docx")])
    assert ui.attached["id"] is None and ui.queue()["committed"] is None
    gate.set()
    await committing
    assert len(ui.posts) == 2 and ui.attached["id"] == "read_parent"
    assert ui.posts[-1][1]["attachment_ids"] == ["read_1", "read_2", "read_3"]
    assert page.chat_attachment_commit_ids(ui.queue()) == ["read_1", "read_2", "read_3"]


@pytest.mark.asyncio
async def test_switching_chat_during_parent_commit_saves_the_original_list_without_polluting_the_new_chat():
    gate = asyncio.Event()
    ui = controller(parent_gate=gate)
    committing = asyncio.create_task(ui.batch([SourceFile("a.pdf"), SourceFile("b.rtf")]))
    await asyncio.sleep(0)
    ui.state["session_id"] = "chat-b"
    ui.ns["_restore_attachment_collection"]()
    gate.set()
    await committing
    assert ui.attached["id"] is None and not ui.state["chat_history"]
    assert ui.queue()["committed"]["attachment_id"] == "read_parent"
    ui.state["session_id"] = "chat-a"
    ui.ns["_restore_attachment_collection"]()
    assert ui.attached["id"] == "read_parent"


@pytest.mark.asyncio
async def test_two_simultaneous_batches_keep_reserved_order_even_when_the_second_finishes_first():
    ui = controller()
    gate = asyncio.Event()
    first = asyncio.create_task(ui.batch([SourceFile("first-a.pdf", gate=gate), SourceFile("first-b.rtf")]))
    await asyncio.sleep(0)
    await ui.batch([SourceFile("second.xlsx")])
    assert not ui.posts and ui.attached["id"] is None
    gate.set()
    await first
    assert ui.posts == [("/api/chat/attachment-collections", {"attachment_ids": ["read_2", "read_3", "read_1"]})]


@pytest.mark.asyncio
async def test_client_rejection_is_visible_and_cannot_silently_commit_a_successful_prefix():
    ui = controller()
    gate = asyncio.Event()
    uploading = asyncio.create_task(ui.batch([SourceFile("accepted.pdf", gate=gate)]))
    await asyncio.sleep(0)
    ui.ns["_reject_attach_upload"](None)
    gate.set()
    await uploading
    assert not ui.posts and ui.attached["id"] is None
    rejected = ui.queue()["batches"][-1]
    assert rejected["status"] == "failed" and rejected["error"]
    ui.ns["_remove_attachment_member"](rejected, None)
    await asyncio.sleep(0)
    assert ui.attached["id"] == "read_1" and not ui.posts


@pytest.mark.asyncio
async def test_separate_page_views_merge_only_the_changed_chat_and_clear_only_that_chat():
    storage = {}
    first = controller(storage=storage, session_id="chat-a")
    second = controller(storage=storage, session_id="chat-b")
    await first.batch([SourceFile("a.pdf")])
    first_saved = deepcopy(storage["les_chat_attachment_queues"]["chat-a"])
    await second.batch([SourceFile("b.pdf")])
    assert storage["les_chat_attachment_queues"]["chat-a"] == first_saved
    await first.batch([SourceFile("a-extra.rtf")])
    latest_first = deepcopy(storage["les_chat_attachment_queues"]["chat-a"])
    second.ns["_persist_attachment_queues"]("chat-b")
    assert storage["les_chat_attachment_queues"]["chat-a"] == latest_first
    second.ns["_clear_attachment"]()
    assert storage["les_chat_attachment_queues"]["chat-a"] == latest_first
    assert storage["les_chat_attachment_queues"]["chat-b"]["batches"] == []
    assert first.queue()["committed"]["text"] == "server-owned manifest preview"


@pytest.mark.asyncio
async def test_remove_source_clears_only_completed_browser_transport_and_preserves_other_sources():
    ui = controller()
    await ui.batch([SourceFile("a.pdf"), SourceFile("b.rtf")])
    other = page.new_chat_attachment_queue()
    ui.ns["_attachment_queues"]["chat-b"] = other
    other_before = deepcopy(other)
    batch = ui.queue()["batches"][0]
    ui.ns["_remove_attachment_member"](batch, 0)
    await asyncio.sleep(0)
    picker = ui.ns["attachment_picker"]
    assert picker.methods == ["removeUploadedFiles"] and picker.reset_count == 0
    assert [member["name"] for member in batch["members"]] == ["b.rtf"]
    assert ui.attached["id"] == "read_2" and ui.queue("chat-b") == other_before
    # An active upload is never removed or aborted by the member action.
    gate = asyncio.Event()
    uploading = asyncio.create_task(ui.batch([SourceFile("c.pdf", gate=gate)]))
    await asyncio.sleep(0)
    ui.ns["_remove_attachment_member"](batch, 0)
    assert picker.methods == ["removeUploadedFiles"] and picker.reset_count == 0
    assert [member["name"] for member in batch["members"]] == ["b.rtf"]
    gate.set()
    await uploading


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["reload_hook", "chat_history"])
async def test_both_history_callbacks_restore_the_target_chat_without_sending_another_chats_attachment(monkeypatch,path):
    from sovushka import state as state_module
    monkeypatch.setattr(state_module,"persist_session_id",lambda sid:sid)
    ui = controller()
    await ui.batch([SourceFile("only-a.pdf")])
    saved_a = deepcopy(ui.queue())
    if path=="reload_hook":
        ui.state["load_session_id"] = "chat-b"
        assert ui.ns["_apply_loaded_session"]() is True
    else:
        await ui.ns["_open_session"]("chat-b")
    assert ui.state["session_id"] == "chat-b" and ui.attached["id"] is None
    assert page._attachment_chat_payload(ui.attached) == {}
    assert ui.queue("chat-a") == saved_a
    ui.state["load_session_id"] = "chat-a"
    assert ui.ns["_apply_loaded_session"]() is True
    assert ui.attached["id"] == "read_1"
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["quick", "index"])
async def test_existing_single_quick_and_index_modes_keep_the_original_transport(mode):
    ui = controller()
    ui.ns["attach_mode"].value = mode
    await ui.batch([SourceFile("table.xlsx")])
    assert not ui.posts and ui.uploads[0][-1] == {"mode": mode}
    assert ui.attached["mode"] == mode and page._attachment_chat_payload(ui.attached) == {"dataset_ids": ["read_1"]}


def test_no_new_fixed_file_count_or_professional_source_summary_is_added():
    source = Path(page.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "upload"
        and any(keyword.arg == "on_multi_upload" for keyword in node.keywords))
    assert not any(keyword.arg == "max_files" for keyword in call.keywords)
    assert any(keyword.arg == "on_begin_upload" for keyword in call.keywords)
    assert any(keyword.arg == "multiple" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
               for keyword in call.keywords)
