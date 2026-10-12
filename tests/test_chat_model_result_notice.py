"""Final response and history render the packaging notice apart from model text."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from sovushka.pages import chat
from sovushka import uikit


class Element:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: self


def production_functions(namespace):
    tree = ast.parse(Path(chat.__file__).read_text(encoding="utf-8"))
    names = {"_apply_chat_result", "_render_model_result_notice", "_finish_ai_placeholder",
             "_render_chat_bubble", "_render_msg"}
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        if node.name == "_apply_chat_result":
            # Execute the real response->meta->saved history->final render boundary;
            # downstream artifact downloads do not participate in notice rendering.
            end = next(i for i, item in enumerate(node.body)
                       if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call)
                       and isinstance(item.value.func, ast.Name)
                       and item.value.func.id == "_finish_ai_placeholder")
            node.body = node.body[:end + 1]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 "<chat-notice-production-functions>", "exec"), namespace)


@pytest.mark.parametrize("status", ["structural_error", "unstructured"])
@pytest.mark.parametrize("trace_only_history", [False, True])
def test_live_notice_survives_history_without_changing_model_answer(monkeypatch, status, trace_only_history):
    rendered = []
    notices = []
    monkeypatch.setattr(uikit, "render_feedback_state",
                        lambda kind, **kwargs: notices.append((kind, kwargs)))
    element = Element()
    namespace = dict(vars(chat))
    namespace.update(
        ui=SimpleNamespace(element=lambda *a: element,
                           markdown=lambda text: rendered.append(text) or element,
                           label=lambda *a: element),
        state={"chat_history": []}, sent_attachment=None, out_mode="text",
        request_started_at="2026-09-11T12:00:00", _t0=0,
        is_smeta_mode=False, ai_placeholder=element, ai_placeholder_label=element,
        _artifact_from_meta=lambda meta: None, _render_rich_body=lambda *a: False,
        _bubble_text=lambda text, mode: text,
        _link_visible_sources=lambda text, *a: text,
    )
    for name in ("_render_model_badge", "_render_dataset_scope_badge", "_render_evidence_header",
                 "_render_source_tags", "_render_suggestions", "_render_excerpts", "_artifact_button",
                 "_render_answer_actions", "_render_answer_timing", "_register_artifact_downloads"):
        namespace[name] = lambda *a, **kw: None
    production_functions(namespace)
    answer = "| Position | Quantity |\n| Cable | 10 |"
    notice = {"status": status, "message": "Книга не собрана: проверьте структуру строк.",
              "errors": ["missing_resource_basis"], "saved": True}
    response = {"answer": answer, "model_result_notice": notice,
                "retrieval_trace": {"model_result_notice": notice}}
    namespace["_apply_chat_result"](response)
    saved = namespace["state"]["chat_history"][0]
    assert saved["text"] == response["answer"] == answer
    assert saved["meta"].get("model_result_notice") == notice
    assert rendered == [answer]
    assert notices == [("error", {"detail": notice["message"]})]
    if trace_only_history:
        del saved["meta"]["model_result_notice"]
    namespace["_render_msg"](saved)
    assert rendered == [answer, answer]
    assert notices == [("error", {"detail": notice["message"]})] * 2


def test_missing_or_invalid_notice_does_not_render_feedback(monkeypatch):
    notices = []
    monkeypatch.setattr(uikit, "render_feedback_state", lambda *a, **kw: notices.append(kw))
    namespace = dict(vars(chat))
    production_functions(namespace)
    render = namespace.get("_render_model_result_notice")
    assert render is not None
    for meta in (None, {}, {"model_result_notice": "bad"},
                 {"model_result_notice": {"status": "structural_error", "message": ""}}):
        render(meta)
    assert notices == []
