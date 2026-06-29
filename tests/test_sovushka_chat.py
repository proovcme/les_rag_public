import inspect
from pathlib import Path

import pytest

from proxy.routers import chat as chat_router
from sovushka.pages import chat as chat_page
from sovushka.pages import instrumenty as instrumenty_page
from sovushka.pages.chat import (
    _attachment_chat_payload,
    _attachment_user_suffix,
    _attachment_visible_text,
    _chat_profile_operator_summary,
    _dataset_profile_operator_summary,
    _operator_status_chips,
    _operator_technical_chips,
    should_skip_chat_resource_gate,
)
from proxy.routers.chat import ChatRequest, _attachment_source_label, _question_with_attachment


def test_ai_plain_markdown_is_rendered_as_markdown_widget():
    source = inspect.getsource(chat_page.build_chat)

    assert "ui.markdown(_format_sources_as_quotes(_disp)).classes(\"sov-chat-message-text sov-chat-md\")" in source
    assert "ui.markdown(_format_sources_as_quotes(_bubble_text(str(text or \"\"), _mode)))" in source


def test_chat_ui_has_new_chat_model_chip_answer_badge_and_wrapping_tables():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "Новый чат" in source
    assert "sov-new-chat-btn" in source
    assert "model_chip = ui.label(\"MODEL -\")" in source
    assert "_refresh_active_model_chip" in source
    assert "api_get(\"/api/status\")" in source
    assert "_render_model_badge(meta)" in source
    assert "versions" in source and "d.get(\"versions\")" in source
    assert 'pagination={"rowsPerPage": 0}' in source
    assert ".sov-model-chip" in styles
    assert ".sov-model-badge" in styles
    assert ".sov-table-scroll .q-table__bottom { display: none !important; }" in styles
    assert "sov-artifact-table" in source
    assert "table-layout: auto" in styles
    assert "overflow-wrap: break-word" in styles
    assert "overflow-x: auto" in styles
    assert "Do not start a second long /api/chat" in source
    assert "serr = stream_state[\"error\"] or {}" in source


def test_instrumenty_has_editable_prompt_controls():
    source = inspect.getsource(instrumenty_page.build_instrumenty)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "_render_prompt_editor" in source
    assert "api_patch(f\"/api/prompts/" in source
    assert "api_delete(f\"/api/prompts/" in source
    assert "sov-prompt-editor" in source
    assert ".sov-prompt-editor" in styles


def test_chat_attachment_upload_uses_nicegui_file_api_not_stale_content_api():
    source = inspect.getsource(chat_page.build_chat)
    attach_block = source[source.index("async def _do_attach"):source.index("def _clear_attachment")]

    assert "on_upload=_do_attach" in source
    assert "lambda e: asyncio.create_task(_do_attach(e))" not in source
    assert "upload = getattr(e, \"file\", None)" in attach_block
    assert "await upload.read()" in attach_block
    assert "e.content.read()" not in attach_block


def test_smeta_table_question_skips_resource_gate():
    assert should_skip_chat_resource_gate("посчитай общую стоимость по всем строкам сметы")


def test_mail_question_skips_resource_gate():
    assert should_skip_chat_resource_gate("найди последнее письмо про Dropbox")


def test_general_normative_question_keeps_resource_gate():
    assert not should_skip_chat_resource_gate("какая минимальная ширина эвакуационного выхода")


def test_attachment_payload_scopes_quick_and_index_files():
    assert _attachment_chat_payload({"id": "attach_abc", "mode": "quick"}) == {
        "dataset_ids": ["attach_abc"]
    }
    assert _attachment_chat_payload({"id": "ds-1", "mode": "index"}) == {
        "dataset_ids": ["ds-1"]
    }


def test_attachment_payload_passes_read_context():
    assert _attachment_chat_payload(
        {"id": "read_1", "mode": "read", "name": "ТЗ.docx", "text": "Текст файла"}
    ) == {
        "attachment_context": "Файл: ТЗ.docx\n\nТекст файла"
    }


def test_attachment_source_label_uses_filename():
    assert _attachment_source_label("Файл: ТЗ.docx\n\nТекст файла") == "attachment:ТЗ.docx"
    assert _attachment_source_label("Текст без имени") == "attachment"


def test_explicit_tool_modes_can_receive_read_attachment_context():
    req = ChatRequest(question="сделай смету", mode="smeta", attachment_context="Файл: ТЗ.docx\n\nПлощадь 1200 м²")
    text = _question_with_attachment(req)
    assert "сделай смету" in text
    assert "Контекст прикреплённого файла" in text
    assert "Площадь 1200 м²" in text


class _FakeLlmResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "ответ"}}]}


class _FakeAsyncClient:
    last_json = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers=None, json=None):
        self.__class__.last_json = json
        return _FakeLlmResponse()


@pytest.mark.asyncio
async def test_free_mode_injects_session_memory(monkeypatch):
    monkeypatch.setattr(
        chat_router,
        "_llm_runtime",
        lambda: chat_router.LlmRuntime("openai-compatible", "http://127.0.0.1:9", "http://llm/chat", "m", "", False),
    )
    monkeypatch.setattr(chat_router, "session_memory", lambda session_id, **kwargs: "ПАМЯТЬ СЕССИИ")
    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)

    answer = await chat_router._run_free_mode(ChatRequest(question="продолжи", session_id="s1"))
    prompt = _FakeAsyncClient.last_json["messages"][1]["content"]
    assert "ПАМЯТЬ СЕССИИ" in prompt
    assert prompt.index("ПАМЯТЬ СЕССИИ") < prompt.index("продолжи")
    assert answer.endswith("ответ")


@pytest.mark.asyncio
async def test_attachment_mode_injects_session_memory(monkeypatch):
    monkeypatch.setattr(
        chat_router,
        "_llm_runtime",
        lambda: chat_router.LlmRuntime("openai-compatible", "http://127.0.0.1:9", "http://llm/chat", "m", "", False),
    )
    monkeypatch.setattr(chat_router, "session_memory", lambda session_id, **kwargs: "ПАМЯТЬ СЕССИИ")
    monkeypatch.setattr(chat_router.httpx, "AsyncClient", _FakeAsyncClient)

    answer = await chat_router._run_attachment_mode(
        ChatRequest(question="что изменилось?", session_id="s1", attachment_context="Файл: a.txt\n\nТекст")
    )
    prompt = _FakeAsyncClient.last_json["messages"][1]["content"]
    assert "ПАМЯТЬ СЕССИИ" in prompt
    assert prompt.index("ПАМЯТЬ СЕССИИ") < prompt.index("Контекст прикреплённого файла")
    assert answer == "ответ"


def test_attachment_visible_text_makes_next_request_obvious():
    title, detail, chat = _attachment_visible_text(
        {"name": "ТЗ.docx", "mode": "read", "chars": 1234}
    )
    assert "следующему сообщению" in title
    assert "В чат" in detail and "ТЗ.docx" in detail
    assert "Модель увидит" in chat

    title, detail, chat = _attachment_visible_text(
        {"name": "ВОР.xlsx", "mode": "quick", "rows": 42}
    )
    assert "следующему сообщению" in title
    assert "Таблица" in detail and "42" in detail
    assert "временный датасет" in chat


def test_attachment_suffix_persists_context_in_user_message():
    text = _attachment_user_suffix(
        {"id": "read_1", "mode": "read", "name": "ТЗ.docx", "text": "abc", "chars": 3}
    )
    assert text == "📎 Прикреплён файл: ТЗ.docx · В чат · 3 симв."

    text = _attachment_user_suffix(
        {"id": "tmp_table", "mode": "quick", "name": "ВОР.xlsx", "rows": 12}
    )
    assert text == "📎 Прикреплена таблица: ВОР.xlsx · Таблица · 12 строк"


def test_chat_no_longer_auto_hijacks_project_summary():
    source = inspect.getsource(chat_router._run_chat)

    assert "deterministic_project_summary" not in source
    assert "is_project_summary_query(req.question)" not in source
    assert "format_project_summary" not in source


def test_chat_adds_metadb_inventory_context_without_project_summary_hijack():
    source = inspect.getsource(chat_router._run_chat)

    assert "is_project_inventory_query(req.question)" in source
    assert "format_project_inventory_prompt" in source
    assert "format_project_inventory_context" in source
    assert "КАРТА РЕЕСТРА ДАТАСЕТА" in source
    assert "project_inventory_artifact_text" in source
    assert "Полный реестр файлов доступен отдельным артефактом/project_inventory" in source
    assert "без markdown-таблиц" in source
    assert "generation_budget = max(generation_budget, 2048)" in source
    assert "Опись файлов датасета (MetaDB documents)" in source
    assert "inventory_requested = bool" in source
    assert "study_requested or inventory_requested" in source
    assert "inventory_has_files" in source
    assert "broad_project_inventory_fast_path" in source
    assert "source_map+project_inventory_artifact" in source
    assert 'validation_context = ""' in source
    assert 'response["project_inventory"] = project_inventory_payload or {}' in source
    assert 'response["notebook_artifact"]' in source
    assert 'LES_NOTEBOOK_STUDY_ARTIFACT_VISIBLE' in source
    assert 'if project_inventory_prompt:' in source
    assert '"title": "Реестр файлов"' in source
    assert "Не выводи наружу служебные слова" in source
    assert "evidence, dataset, датасет" in source


def test_chat_ui_renders_clickable_project_inventory_artifact():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "_inventory_file_rows_from_meta" in source
    assert "project_inventory" in source
    assert "artifact.get(\"project_inventory\")" in source
    assert "payload[\"target_file\"] = target_file" in source
    assert "_pending_target_file[\"v\"] = target" in source
    assert "расскажи, что в файле" in source
    assert "Спросить по файлу" in source
    assert "target_file=" in source
    assert "has_inventory = bool(_inventory_file_rows_from_meta(meta))" in source
    assert "artifact_shell.visible or _inventory_file_rows_from_meta(meta)" in source
    assert "\"Реестр файлов\"" in source
    assert "INDEXED" in source and "PENDING" in source and "ERROR" in source
    assert "chunk_count" in source and "чанков" in source
    assert ".sov-inventory-file-row" in styles
    assert ".sov-inventory-status-indexed" in styles
    assert ".sov-inventory-ask-btn" in styles


def test_chat_ui_shows_selected_dataset_files_panel():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "scope_files_panel" in source
    assert "_refresh_scope_files_panel" in source
    assert "/api/notebooks/{_q(dsid, safe='')}/memory" in source
    assert "Файлы выбранной области" in source
    assert "Файлы датасета" in source
    assert "_ask_about_scope_file" in source
    assert "_pending_target_file[\"v\"] = target" in source
    assert "Спросить строго по файлу" in source
    assert "content_layers" in source
    assert "document_role" in source
    assert "base_name.startswith(\".\")" in source
    assert "base_name.startswith(\"_les_\")" in source
    assert ".sov-scope-files-panel" in styles
    assert ".sov-scope-file-chip" in styles
    assert ".sov-scope-file-badge" in styles
    assert ".sov-scope-file-ask" in styles


def test_operator_status_chips_hide_internal_trace_from_first_layer():
    meta = {
        "query_route": {"channel": "table", "kot": {"dataset_filter": "NTD_FIRE", "confidence": 0.8}},
        "retrieval_trace": {"mode": "hybrid", "quality_status": "good"},
        "cache": "miss",
        "validation": {"enabled": True},
        "latency_phases": {"total": 12.34},
        "scenario": {"id": "table_query", "label": "Табличный расчёт"},
        "answer_contract": {"id": "tool_result_v1", "label": "Результат инструмента", "tables": "required"},
        "answer_contract_check": {"status": "warn", "missing": ["answer"]},
        "workflow_plan": {
            "schema": "workflow_plan_v1",
            "workflow_id": "table_query",
            "status": "needs_data",
            "finality": "not_final",
            "missing_inputs": ["structured_rows"],
            "next_actions": ["Выбрать табличный датасет"],
        },
    }

    chips = _operator_status_chips("VERIFIED", meta, ["a", "b"])
    labels = [c["label"] for c in chips]

    assert "2 источн." in labels
    assert "Проверено" not in labels
    assert "Таблица" not in labels
    assert "Табличный расчёт" not in labels
    assert "Табличный контракт" not in labels
    assert "Контракт: замечания" not in labels
    assert "Ход: нужны данные" not in labels
    assert "Не финал" not in labels
    assert "12.3с" not in labels
    assert all("KOT" not in label and "CACHE" not in label for label in labels)

    tech = _operator_technical_chips(meta)
    assert "KOT NTD_FIRE 0.8" in tech
    assert "CACHE MISS" in tech
    assert "CONTRACT_CHECK WARN" in tech
    assert "MISSING answer" in tech
    assert "SCENARIO table_query" in tech
    assert "CONTRACT tool_result_v1" in tech
    assert "WORKFLOW table_query" in tech
    assert "WF_STATUS needs_data" in tech
    assert "WF_FINALITY not_final" in tech
    assert "WF_MISSING structured_rows" in tech
    assert "WF_ACTION Выбрать табличный датасет" in tech


def test_dataset_and_chat_profile_operator_summaries_are_human_readable():
    ds = {
        "name": "Пожарные нормы",
        "dataset_id": "ds-fire",
        "document_count": 3,
        "chunk_count": 120,
        "keywords": ["эвакуац", "лестниц"],
        "profile_path": "storage/datasets/ds-fire/_les_dataset_profile.json",
        "deep": {
            "norm_refs": ["СП 1.13130", "ФЗ 123"],
            "content_keywords": ["выход", "коридор"],
            "table_signal_chunks": 7,
        },
    }
    chat = {
        "turn_count": 4,
        "last_status": "VERIFIED",
        "effective_dataset_filter": "NTD_FIRE",
        "blockers": ["нет PDF проекта"],
        "assumptions": ["принята высота 3 м"],
    }

    ds_lines = _dataset_profile_operator_summary(ds)
    chat_lines = _chat_profile_operator_summary(chat)

    assert "Пожарные нормы: 3 файлов, 120 чанков" in ds_lines[0]
    assert any("СП 1.13130" in line for line in ds_lines)
    assert any("Табличный сигнал" in line for line in ds_lines)
    assert "Ходов: 4" in chat_lines[0]
    assert any("нет PDF проекта" in line for line in chat_lines)
