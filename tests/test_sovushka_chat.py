import inspect
from pathlib import Path

import pytest

from proxy.routers import chat as chat_router
from proxy.services import chat_evidence_application_service
from proxy.routers import datasets as datasets_router
from sovushka.pages import chat as chat_page
from sovushka.pages import instrumenty as instrumenty_page
from sovushka.pages import samovar as samovar_page
from sovushka.pages import volk as volk_page
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


def test_chat_request_accepts_explicit_multi_document_scope_and_response_length():
    req = ChatRequest(
        question="сравни документы",
        target_files=["NS/ПЗ.pdf", "NS/Схемы.pdf", "NS/ПЗ.pdf"],
        response_length="detailed",
    )
    assert req.target_files == ["NS/ПЗ.pdf", "NS/Схемы.pdf"]
    assert req.response_length == "detailed"


def test_ai_plain_markdown_is_rendered_as_markdown_widget():
    source = inspect.getsource(chat_page.build_chat)

    assert "ui.markdown(_format_sources_as_quotes(_disp)).classes(\"sov-chat-message-text sov-chat-md\")" in source
    assert "ui.markdown(_format_sources_as_quotes(_bubble_text(str(text or \"\"), _mode)))" in source


def test_smeta_operator_sees_live_tool_and_rrf_telemetry():
    source = inspect.getsource(chat_page.build_chat)

    assert "sov-smeta-operator-log" in source
    assert 'phase == "retrieval"' in source
    assert "model_wait_ms" in source
    assert "unique_queries_count" in source
    assert "RRF" in source


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


def test_chat_ui_mode_guidance_is_compact_and_input_focused():
    guidance = chat_page.CHAT_MODE_GUIDANCE

    assert set(guidance) == {"text", "rag", "smeta", "doc_review"}
    for item in guidance.values():
        assert item["title"]
        assert item["description"]
        assert item["data_hint"]
        assert 1 <= len(item["examples"]) <= 3


def test_chat_ui_primary_surface_uses_progressive_disclosure():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert '<div class="sov-chat-title">Чат</div>' in source
    assert "Документы, расчёты и проверка" in source
    assert "technical_status.set_visibility(False)" in source
    assert 'classes("sov-mode-guide")' in source
    assert 'classes("sov-mode-example")' in source
    assert "lambda _event, mm=_m: _set_mode(mm)" in source
    assert "lambda _event, example=_example: _fill_prompt(str(example))" in source
    assert 'icon="o_more_horiz"' in source
    assert 'ui.expansion("Команды"' in source
    assert 'if key == "text":' in source
    assert "_set_artifacts_visible(False)" in source
    assert ".sov-mode-guide" in styles
    assert ".sov-mode-example" in styles
    assert 'classes("sov-composer-footer")' in source
    assert ".sov-composer-footer" in styles
    assert "Shift+Enter — перенос строки" not in source
    assert "position: absolute" in styles
    assert "padding-right: 386px" in styles
    assert "background: transparent" in styles
    assert "width: auto" in styles
    assert "min-height: 40px" in styles
    assert "scale: .96" in styles
    assert "max-width: 1440px" in styles


def test_instrumenty_has_editable_prompt_controls():
    source = inspect.getsource(instrumenty_page.build_instrumenty)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "_render_prompt_editor" in source
    assert "api_patch(f\"/api/prompts/" in source
    assert "api_delete(f\"/api/prompts/" in source
    assert "sov-prompt-editor" in source
    assert ".sov-prompt-editor" in styles


def test_instrumenty_refresh_buttons_bind_after_handlers_exist():
    source = inspect.getsource(instrumenty_page.build_instrumenty)

    assert "ui.button(\"ОБНОВИТЬ\", on_click=_refresh)" not in source
    assert "ui.button(\"ОБНОВИТЬ\", on_click=_refresh_prompts)" not in source
    assert source.index("async def _refresh_prompts") < source.index("refresh_prompts_btn.on(\"click\", _refresh_prompts)")
    assert source.index("async def _refresh") < source.index("refresh_btn.on(\"click\", _refresh)")


def test_volk_buttons_and_grid_events_bind_after_handlers_exist():
    source = inspect.getsource(volk_page.build_volk)

    assert "on_click=_volk_load" not in source
    assert "on_click=_volk_create" not in source
    assert source.index("async def _volk_load") < source.index("refresh_btn.on(\"click\", _volk_load)")
    assert source.index("async def _volk_create") < source.index("create_btn.on(\"click\", _volk_create)")
    assert source.index("async def _volk_toggle") < source.index("volk_tbl.on(\"toggle\", _grid_handler(_volk_toggle))")


def test_chat_attachment_upload_uses_nicegui_file_api_not_stale_content_api():
    source = inspect.getsource(chat_page.build_chat)
    attach_block = source[source.index("async def _do_attach"):source.index("def _clear_attachment")]

    assert "on_upload=_do_attach" in source
    assert "lambda e: asyncio.create_task(_do_attach(e))" not in source
    assert "upload = getattr(e, \"file\", None)" in attach_block
    assert "await upload.read()" in attach_block
    assert "e.content.read()" not in attach_block


def test_samovar_parse_actions_keep_nicegui_slot_context():
    source = inspect.getsource(samovar_page.build_samovar)
    legacy_source = inspect.getsource(samovar_page.build_samovar_legacy)

    assert "on_click=_ui_handler(_parse, r)" in source
    assert "ui.timer(5.0, _refresh_status)" in source
    assert "api_post(\"/api/rag/parse-scheduler\", payload)" in source
    assert "_scheduler_payload()" in source
    assert "background': 'true'" in source
    assert "row_batch_limit" in source
    assert "Настройки индексации" in source
    assert "По умолчанию" in source
    assert "_notify(" in source
    assert "sam_grid.on(\"parse\", _grid_handler(_parse_row))" in legacy_source
    assert "asyncio.create_task(_parse(rr))" not in source
    assert "asyncio.create_task(_parse_row(e.args))" not in legacy_source
    start_block = source[source.index("async def _start_all"):source.index("async def _stop_all")]
    assert "/api/runtime/dispatcher/reindex/start" not in start_block


def test_samovar_operator_panel_shows_jobs_memory_and_ocr_queue():
    source = inspect.getsource(samovar_page.build_samovar)
    adapter_source = Path("backend/qdrant_adapter.py").read_text(encoding="utf-8")

    assert "Оператор индекса" in source
    assert "лёгкие" in source
    assert "сканы" in source
    assert "/api/indexing-mode" in source
    assert "/api/jobs/summary?limit=40" in source
    assert "Осталось {eta}" in source
    assert "complexity='needs_ocr'" in adapter_source
    assert "pipeline='markdown_needs_ocr'" in adapter_source


def test_parse_batch_endpoint_can_create_background_job():
    source = inspect.getsource(datasets_router.parse_dataset_batch)

    assert "background: bool = False" in source
    assert "\"rag_parse_batch\"" in source
    assert "state.job_service.create" in source
    assert "asyncio.create_task(_run())" in source
    assert "await assert_parse_admission(state)" in source
    assert "\"status\": \"queued\"" in source


def test_selected_dataset_ids_preempt_glossary_deterministic_final():
    source = inspect.getsource(chat_router._run_chat)

    assert "_selected_scope_filter" in source
    assert "__selected_dataset__" in source
    assert "req.dataset_ids or _scope_snap.get(\"resolved_dataset_ids\")" in source
    assert "dataset_filter=_selected_scope_filter" in source
    assert "dataset_filter=req.dataset_filter or \"\", candidate=_cand" not in source


def test_notebook_study_uses_ready_navigation_without_query_time_artifact_fanout():
    source = inspect.getsource(chat_router._run_chat) + inspect.getsource(
        chat_evidence_application_service._execute_chat_evidence_application
    )

    assert "_prepare_notebook_reader_memory" in source
    assert "dataset_reader_prepare" in source
    assert "inventory_requested or study_requested" in source
    assert '"reason": "model_first_single_rrf"' in source
    assert "LES_NOTEBOOK_STUDY_ARTIFACT_VISIBLE" not in source
    assert "build_notebook_study_pack(" not in source
    assert "used_for_notebook_study" in source
    assert "question=req.question" in source
    assert "dataset_brief_for_model_v1" in source


@pytest.mark.asyncio
async def test_prepare_notebook_reader_memory_runs_or_schedules(monkeypatch):
    calls = []

    monkeypatch.setattr(chat_router, "_env_bool", lambda name, default=False: True)
    monkeypatch.setattr(chat_router, "_env_int", lambda name, default, **_kw: default)
    monkeypatch.setattr(chat_router, "_env_float", lambda name, default, **_kw: 0.01)
    monkeypatch.setattr(chat_router, "get_typed_dataset_memory", lambda dataset_id: {
        "dataset_id": dataset_id,
        "reader_status": "bootstrap",
    })

    async def slow_reader(dataset_id, **_kw):
        calls.append(dataset_id)
        import asyncio
        await asyncio.sleep(0.05)
        return {"dataset_id": dataset_id, "reader_status": "model"}

    monkeypatch.setattr(chat_router, "run_dataset_reader_pass", slow_reader)
    monkeypatch.setattr(chat_router, "schedule_dataset_reader_pass", lambda dataset_id, **_kw: {
        "scheduled": True,
        "dataset_id": dataset_id,
    })

    result = await chat_router._prepare_notebook_reader_memory(["ds-1"])

    assert result["schema"] == "dataset_reader_prepare_v1"
    assert calls == ["ds-1"]
    assert result["datasets"][0]["status"] == "scheduled_after_timeout"
    assert result["datasets"][0]["scheduled"]["scheduled"] is True


def test_samovar_pending_means_waiting_not_active_parsing():
    assert samovar_page._computed_index_status(total=10, indexed=2, pending=8) == "WAITING"
    assert samovar_page._computed_index_status(total=10, indexed=2, pending=8, active=True) == "PARSING"


def test_samovar_stale_contract_failure_becomes_actionable_when_runtime_is_ready():
    assert samovar_page._operator_queue_notice(
        pending=8,
        last_status="FAILED",
        last_message="index contract missing: expected=x actual=none",
        contract_compatible=True,
    ) == ("ГОТОВ К ПРОДОЛЖЕНИЮ · 8 файлов ждут · нажмите «Пуск»", "ready")

    blocked = samovar_page._operator_queue_notice(
        pending=8,
        last_status="FAILED",
        last_message="index contract missing: expected=x actual=none",
        contract_compatible=False,
    )
    assert blocked == ("ОСТАНОВЛЕНО · 8 файлов ждут · локальный индекс не подготовлен; перезапустите ЛЕС", "error")


def test_samovar_document_layer_labels_are_human_readable():
    item = {
        "content_layers": ["tables", "calculations", "technical_docs"],
        "document_role": "Пояснительная записка",
    }

    assert samovar_page._doc_layer_labels(item)[:4] == [
        "Пояснительная записка",
        "таблицы",
        "расчёты",
        "техничка",
    ]


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
        {"id": "read_123456abcdef", "mode": "read", "name": "ТЗ.docx", "text": "Текст файла"}
    ) == {
        "attachment_id": "read_123456abcdef",
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
    source = inspect.getsource(chat_router._run_chat) + inspect.getsource(
        chat_evidence_application_service._execute_chat_evidence_application
    )

    assert "is_project_inventory_query(req.question)" in source
    assert "format_project_inventory_prompt" in source
    assert "format_project_inventory_context" in source
    assert 'retrieval_trace["project_inventory"]' in source
    assert 'f"{project_inventory_prompt}\\n\\n"' in source
    assert "project_inventory_artifact_text" in source
    assert 'response["project_inventory"] = project_inventory_payload or {}' in source
    assert "generation_budget = max(generation_budget, 2048)" not in source
    assert "Опись файлов датасета (MetaDB documents)" in source
    assert "inventory_requested = bool" in source
    assert "study_requested or inventory_requested" in source
    assert "inventory_has_files" in source
    assert "broad_project_inventory_fast_path" in source
    assert "source_map+project_inventory_artifact" in source
    assert 'validation_context = ""' in source
    assert 'response["project_inventory"] = project_inventory_payload or {}' in source
    assert 'response["notebook_artifact"]' in source
    assert '"reason": "model_first_single_rrf"' in source
    assert "LES_NOTEBOOK_STUDY_ARTIFACT_VISIBLE" not in source
    assert 'if project_inventory_prompt:' in source
    assert '"title": "Реестр файлов"' in source
    assert 'retrieval_trace["prompt_layers"]' in source
    assert '"inventory_navigation"' in source


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


def test_chat_history_restores_saved_file_artifacts():
    source = inspect.getsource(chat_page.build_chat)

    assert '_register_artifact_downloads(msg.get("meta"))' in source
    assert "def _clear_file_artifacts" in source
    assert "_clear_file_artifacts()" in source


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
