import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from proxy.routers import chat as chat_router
from proxy.services import chat_evidence_application_service
from proxy.services.context_governor_service import ContextKind
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
    _smeta_clarification_prompt,
    _smeta_conflict_ui,
    _smeta_decision_label,
    _smeta_artifact_rows,
    _smeta_progress_phase_label,
    _smeta_progress_text,
    _smeta_rows_markdown,
    _runtime_guard_reason_label,
    artifact_workbook_files,
    format_answer_timing_line,
    format_chat_request_clock,
    workbook_chat_filename,
    should_skip_chat_resource_gate,
    _preserved_attachment,
)
from proxy.routers.chat import ChatRequest, _attachment_source_label, _question_with_attachment


def test_chat_has_no_special_smeta_mode():
    modes = getattr(chat_page, "visible_chat_modes", lambda: ("smeta",))()

    assert "smeta" not in modes


def test_chat_timing_uses_backend_wall_clock_and_generation():
    requested = datetime(2026, 8, 2, 18, 9, 11, tzinfo=timezone.utc).isoformat()

    assert format_chat_request_clock(requested).endswith("21:09")
    assert format_answer_timing_line(
        requested_at=requested,
        elapsed_sec=50,
        latency_phases={"wall_total": 42.2, "generation": 28.0},
    ).endswith("ответ 42с · модель 28с")


def test_workbook_chat_filename_never_exposes_path_or_generic_artifact():
    assert workbook_chat_filename({
        "filename": "LSR_demo_2026-09-01_2147.xlsx",
    }) == "LSR_demo_2026-09-01_2147.xlsx"
    assert workbook_chat_filename({
        "filename": "C:/private/workbook.xlsx",
        "artifact_kind": "vor_workbook",
    }) == "VOR.xlsx"
    assert workbook_chat_filename({"filename": "artifact.xlsx"}) == "LSR.xlsx"


def test_artifact_workbook_files_preserves_all_distinct_downloads():
    files = artifact_workbook_files({
        "download_url": "/api/artifacts/lsr/download",
        "filename": "LSR_demo.xlsx",
        "files": [
            {
                "download_url": "/api/artifacts/lsr/download",
                "filename": "LSR_demo.xlsx",
                "artifact_kind": "lsr_workbook",
            },
            {
                "download_url": "/api/artifacts/vor/download",
                "filename": "VOR_demo.xlsx",
                "artifact_kind": "vor_workbook",
            },
        ],
    })

    assert files == [
        {
            "download_url": "/api/artifacts/lsr/download",
            "filename": "LSR_demo.xlsx",
            "artifact_kind": "lsr_workbook",
        },
        {
            "download_url": "/api/artifacts/vor/download",
            "filename": "VOR_demo.xlsx",
            "artifact_kind": "vor_workbook",
        },
    ]


def test_smeta_artifact_rows_uses_exact_finished_draft_rows_without_decision_fallback():
    rows = _smeta_artifact_rows({
        "draft_rows": [{
            "work_id": "42",
            "source_row": 42,
            "title": "Кабель",
            "quantity": 12,
            "unit": "м",
            "norm_code": "CUSTOM-NORM-A",
            "analogue": "Аналог Qwen",
        }],
    })

    assert rows == [{
        "work_id": "42",
        "source_row": 42,
        "title": "Кабель",
        "quantity": 12,
        "unit": "м",
        "norm_code": "CUSTOM-NORM-A",
        "analogue": "Аналог Qwen",
    }]


def test_chat_session_id_survives_ui_reopen(monkeypatch):
    from sovushka import state as sov_state

    storage = SimpleNamespace(user={})
    monkeypatch.setattr(sov_state, "app", SimpleNamespace(storage=storage))
    previous = sov_state.state.get("session_id")
    try:
        assert sov_state.persist_session_id("session-stable") == "session-stable"
        sov_state.state["session_id"] = "temporary"
        assert sov_state.ensure_session_id() == "session-stable"
        assert sov_state.state["session_id"] == "session-stable"
    finally:
        sov_state.state["session_id"] = previous


def test_chat_request_accepts_explicit_multi_document_scope_and_response_length():
    req = ChatRequest(
        question="сравни документы",
        target_files=["NS/ПЗ.pdf", "NS/Схемы.pdf", "NS/ПЗ.pdf"],
        response_length="detailed",
    )
    assert req.target_files == ["NS/ПЗ.pdf", "NS/Схемы.pdf"]
    assert req.response_length == "detailed"


def test_chat_request_accepts_explicit_selected_sources_only_capability():
    assert ChatRequest(question="q", selected_sources_only=True).selected_sources_only is True
    assert ChatRequest(question="q").selected_sources_only is None


def test_ai_plain_markdown_is_rendered_as_markdown_widget():
    source = inspect.getsource(chat_page.build_chat)

    assert "ui.markdown(_link_visible_sources(_disp, srcs or [], meta)).classes" in source
    assert "ui.markdown(_link_visible_sources(" in source


def test_chat_links_source_markers_to_anchored_drawer_rows_and_shows_three_counts():
    source = inspect.getsource(chat_page.build_chat)

    assert "link_source_markers" in source
    assert 'id=source-{i}' in source
    assert "source_count_labels" in source
    assert 'meta.get("source_counts")' in source


def test_chat_exposes_and_sends_selected_sources_only_switch():
    source = inspect.getsource(chat_page.build_chat)

    assert "Только выбранные источники" in source
    assert 'payload["selected_sources_only"]' in source


def test_smeta_operator_sees_live_tool_and_rrf_telemetry():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "sov-smeta-operator-log" in source
    assert 'phase == "retrieval"' in source
    assert "model_wait_ms" in source
    assert "unique_queries_count" in source
    assert "RRF" in source
    assert 'event == "smeta_row"' in source
    assert "sov-smeta-live-table" in source
    assert "smeta_live_rows[work_id] = row" in source
    assert '_show_artifact(' in source
    assert 'Артефакт обновляется после каждой завершённой строки.' in source
    assert ".sov-smeta-live-table" in styles
    assert "font-variant-numeric: tabular-nums" in styles
    assert "Авточерновик" in source
    assert "Проверил — зафиксировать" in source
    assert "Разобрать замечания" in source
    assert "Подготовить уточнение" in source
    assert "Принять текущую привязку норм" in source
    assert "on_click=review_smeta_mapping" in source
    assert "asyncio.create_task(_lock_smeta_mapping" not in source
    assert "Артефакт старого формата: прикрепите исходный файл повторно" in source
    assert "accepted_conflict_ids" in source
    assert ".sov-smeta-approval" in styles


def test_smeta_ui_localizes_machine_progress_and_resource_guard():
    assert _smeta_progress_phase_label("mapping_retry") == "Исправление решения"
    assert _smeta_progress_phase_label("future_internal_phase") == "Этап расчёта"
    assert _smeta_progress_text(
        "Смета: модель исправляет решение — invalid unbound_evidence"
    ) == "Смета: модель исправляет решение — недостаточно обоснований для отсутствия нормы"
    assert _smeta_progress_text("Смета: модель фиксирует mapping") == (
        "Смета: модель фиксирует привязку норм"
    )
    assert _runtime_guard_reason_label("ram_free_gb=1.4 < 2.0") == (
        "свободная память 1,4 ГБ ниже порога 2,0 ГБ"
    )


def test_smeta_final_artifact_includes_unfinished_rows_from_authoritative_lsr():
    rows = _smeta_artifact_rows({
        "rim_trace": {
            "positions": [
                {
                    "work_id": "w1",
                    "name": "Шкаф",
                    "qty": 2,
                    "unit": "шт.",
                    "code": "MISSING",
                }
            ],
            "sections": [
                {
                    "positions": [
                        {
                            "work_id": "w2",
                            "name": "Кабель",
                            "qty": 100,
                            "unit": "м",
                            "code": "ГЭСНм08-02-412-01",
                        }
                    ]
                }
            ],
        }
    })

    assert rows == [
        {
            "work_id": "w1",
            "title": "Шкаф",
            "quantity": 2,
            "unit": "шт.",
            "norm_code": "",
            "decision": "unbound",
        },
        {
            "work_id": "w2",
            "title": "Кабель",
            "quantity": 100,
            "unit": "м",
            "norm_code": "ГЭСНм08-02-412-01",
            "decision": "ГЭСНм08-02-412-01",
        },
    ]
    markdown = _smeta_rows_markdown(rows)
    assert "| 1 | Шкаф | 2 шт. | Норма не привязана |" in markdown
    assert "| 2 | Кабель | 100 м | ГЭСНм08-02-412-01 |" in markdown
    assert "for msg in reversed(state.get(\"chat_history\", []))" in inspect.getsource(
        chat_page.build_chat
    )


def test_chat_ui_has_new_chat_model_chip_answer_badge_and_wrapping_tables():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "Новый чат" in source
    assert "sov-new-chat-btn" in source
    assert "model_chip = ui.label(\"МОДЕЛЬ —\")" in source
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
    assert "ensure_session_id()" in source
    assert "Сессия восстановлена." in source
    assert "persist_session_id(_new_session_id())" in source


def test_chat_ui_can_stop_only_the_active_answer_stream():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert '"Остановить диалог"' in source
    assert "def _stop_active_dialog()" in source
    assert 'task.cancel()' in source
    assert "except asyncio.CancelledError:" in source
    assert "Диалог остановлен пользователем." in source
    assert 'stop_dialog_btn.set_visibility(True)' in source
    assert 'stop_dialog_btn.set_visibility(False)' in source
    assert ".sov-stop-dialog-btn" in styles


def test_chat_stream_keeps_reader_position_until_they_return_to_the_tail():
    source = inspect.getsource(chat_page.build_chat)

    assert 'ui.scroll_area(on_scroll=_track_chat_scroll)' in source
    assert 'remaining = event.vertical_size - event.vertical_position - event.vertical_container_size' in source
    assert '_chat_follow_tail["v"] = remaining <= 48' in source
    assert 'def _scroll_chat_to_tail(*, force: bool = False)' in source
    sse_handler = source[source.index('def _on_sse(event: str, payload) -> None:'):source.index('completed = False')]
    assert '_scroll_chat_to_tail()' in sse_handler
    assert 'chat_scroll.scroll_to(percent=1)' not in sse_handler


def test_chat_ui_consumes_tool_progress_and_canonical_artifact_download():
    source = inspect.getsource(chat_page.build_chat)
    helper = inspect.getsource(chat_page._preserved_attachment)

    assert 'elif event == "tool_progress":' in source
    assert 'stream_state["got_progress"] = True' in source
    assert 'should_retry_unstreamed_chat(' in source
    assert artifact_workbook_files({
        "download_url": "/api/artifacts/rev-1/download",
        "filename": "LSR_demo.xlsx",
    })[0]["download_url"] == "/api/artifacts/rev-1/download"
    assert 'retry.get("attachment_id")' in helper


def test_chat_ui_mode_guidance_is_compact_and_input_focused():
    guidance = chat_page.CHAT_MODE_GUIDANCE

    assert set(guidance) == {"search", "agent", "estimator", "engineer"}
    for item in guidance.values():
        assert item["title"]
        assert item["description"]
        assert item["data_hint"]
        assert 1 <= len(item["examples"]) <= 3


def test_chat_ui_primary_surface_uses_progressive_disclosure():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")
    uikit = Path("sovushka/uikit/tokens.py").read_text(encoding="utf-8")

    assert '<span class="sov-chat-title sov-acronym-title">С.О.В.У.Ш.К.А.</span>' in source
    assert "С.О.В.У.Ш.К.А. · Чат" not in source
    assert "Умная, Шаблонизированная, " in source
    assert "Классифицированная, Автоматизированная" in source
    assert 'class="sov-owl-mark"' in source
    assert "technical_status.set_visibility(False)" in source
    assert 'with ui.expansion("Примеры запросов", icon="o_lightbulb", value=False)' in source
    assert '"sov-mode-guidance-disclosure"' in source
    assert 'classes("sov-mode-guide")' in source
    assert 'classes("sov-mode-example")' in source
    assert "select_field(" in source
    assert 'classes="sov-mode-select"' in source
    assert "on_change=lambda event: _set_mode(str(event.value))" in source
    assert "lambda _event, example=_example: _fill_prompt(str(example))" in source
    assert '"Настройки ответа"' in source
    assert 'aria_label="Настройки ответа"' in source
    assert 'response_length_select = ui.select(' in source
    assert '"response_length": str(response_length_select.value or "standard")' in source
    assert 'aria_label="Действия чата"' in source
    assert 'classes="sov-mobile-chat-menu"' in source
    for label in ("История", "Артефакты"):
        assert f'"{label}"' in source
    assert 'ui.menu_item("Новый чат"' not in source
    assert 'ui.menu_item(\n                                    "Документы"' not in source
    assert ".sov-mobile-chat-menu" in uikit
    assert ".sov-topbar-icon-action {\n    display: none !important;" in uikit
    assert 'aria-label="Дополнительные действия"' not in source
    assert '"Максимум (полный анализ)": "Проведи максимально подробный анализ.' not in source
    assert 'if key == "text":' in source
    assert "_set_artifacts_visible(False)" in source
    assert ".sov-mode-guide" in styles
    assert ".sov-mode-example" in styles
    assert 'classes("sov-composer-footer")' in source
    assert 'aria_label="Отправить"' in source
    assert 'props("rows=1 autogrow borderless")' in source
    assert ".sov-composer-footer" in uikit
    assert ".sov-mode-guidance-disclosure" in uikit
    assert ".sov-mode-guidance-disclosure {\n  width: 100%;" in uikit
    assert "padding-right: 420px" not in uikit
    assert "Shift+Enter — перенос строки" not in source
    assert "background: transparent" in uikit
    assert "min-height: var(--sov-ui-hit)" in uikit
    assert "scale: .96" in styles
    assert "max-width: 1440px" in styles


def test_chat_file_picker_uses_task_language_and_compact_uikit_surface():
    source = inspect.getsource(chat_page.build_chat)
    uikit = Path("sovushka/uikit/tokens.py").read_text(encoding="utf-8")

    for label in (
        "Добавить файл",
        "Задать вопрос по файлу",
        "Сверить таблицу",
        "Сохранить в базе ЛЕС",
        "Выбрать файл",
    ):
        assert label in source
    assert "attach_mode = ui.radio(" in source
    assert "attach_mode = ui.toggle(" not in source
    assert 'classes("sov-attach-dialog")' in source
    assert '"sov-attach-mode-detail"' in source
    assert '"sov-chat-file-picker"' in source
    assert 'max_files=1' in source
    assert ".sov-attach-dialog" in uikit
    assert ".sov-chat-file-picker" in uikit


def test_instrumenty_has_no_competing_prompt_controls():
    source = inspect.getsource(instrumenty_page.build_instrumenty)

    assert "_render_prompt_editor" not in source
    assert "/api/prompts" not in source
    assert "Системные промпты" not in source


def test_instrumenty_refresh_buttons_bind_after_handlers_exist():
    source = inspect.getsource(instrumenty_page.build_instrumenty)

    assert "ui.button(\"ОБНОВИТЬ\", on_click=_refresh)" not in source
    assert "_refresh_prompts" not in source
    assert source.index("async def _refresh") < source.index("refresh_btn.on(\"click\", _refresh)")


def test_volk_buttons_and_grid_events_bind_after_handlers_exist():
    source = inspect.getsource(volk_page.build_volk)

    assert "async def load_keys" in source
    assert "async def create_key" in source
    assert "async def toggle_key" in source
    assert "on_click=load_keys" in source
    assert "on_click=create_key" in source
    assert "sov-access-key-row" in source
    assert "ui.table(" not in source
    assert ".style(" not in source


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
    assert "status_timer = ui.timer(5.0, _refresh_status)" in source
    assert 'api_get("/api/runtime/dispatcher/reindex/status")' in source
    assert 'api_get("/api/runtime/dispatcher/status")' not in source
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


def test_dataset_name_defaults_to_pasted_folder_basename():
    assert samovar_page._dataset_name_from_path(
        r"C:\Users\Oleg\Documents\RAG\ИЦ Рабочая документация\ИЦ Рабочая документация"
    ) == "ИЦ Рабочая документация"
    assert samovar_page._dataset_name_from_path("/srv/rag/Project A/") == "Project A"
    assert samovar_page._dataset_name_from_path("") == ""


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


def test_selected_dataset_ids_stay_in_model_owned_scope_without_deterministic_final():
    source = inspect.getsource(chat_router._run_chat)

    assert 'req.dataset_ids = _scope_snap["resolved_dataset_ids"]' in source


def test_chat_defaults_to_plain_ai_and_always_sends_explicit_scope():
    source = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")

    assert '"scope_type": "none"' in source
    assert '"label": "Без источников"' in source
    assert 'scope_state["scope_type"] = "none"' in source
    assert 'scope_state["scope_type"] = "all"' in source
    assert 'payload["scope"] = {"scope_type": scope_state["scope_type"]' in source
    assert 'if scope_state["scope_type"] != "all":' not in source


def test_router_does_not_infer_document_scope_for_plain_ai_chat():
    source = inspect.getsource(chat_router._run_chat)

    assert "document_grounding_enabled(" in source
    assert '_scope_snap["scope_type"], req.dataset_ids' in source
    assert 'scope_source = "none"' in source
    assert "effective_dataset_filter = explicit_dataset_filter(" in source
    assert 'use_semantic_cache = False' in source


def test_chat_ui_does_not_request_semantic_answer_validation():
    source = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")

    assert '"validation_enabled": True' not in source


def test_answer_shows_actual_model_connection_and_dataset_scope():
    source = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")

    assert 'meta.get("model_connection")' in source
    assert "ДАТАСЕТЫ" in source
    assert 'trace.get("source_scope")' in source
    assert "_det_channels" not in source
    assert "can_return_deterministic_final" not in source
    assert "maybe_handle_glossary_query" not in source


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


def test_attachment_payload_keeps_read_pdf_without_extracted_text():
    assert _attachment_chat_payload(
        {"id": "read_pdf_123", "mode": "read", "name": "ВОР.pdf"}
    ) == {
        "attachment_id": "read_pdf_123",
        "attachment_context": "Файл: ВОР.pdf\n\n",
    }


def test_failed_document_run_restores_the_exact_sent_attachment():
    sent = {
        "id": "read_0123456789ab",
        "name": "source.xlsx",
        "mode": "read",
        "rows": 5,
    }

    assert _preserved_attachment(
        {
            "attachment_retry": {
                "preserved": True,
                "id": "read_0123456789ab",
                "name": "source.xlsx",
                "mode": "read",
            }
        },
        sent,
    ) == sent
    assert _preserved_attachment({}, sent) == {}
    assert '"attachment_retry"' not in inspect.getsource(chat_router._run_chat)


def test_smeta_clarification_prompt_keeps_questions_and_operator_owned_assumptions():
    prompt = _smeta_clarification_prompt(
        {
            "open_items": [
                {
                    "work_id": "vor-0004",
                    "title": "Кабель U/UTP Cat.6A",
                    "quantity": 4,
                    "unit": "шт.",
                },
                {
                    "work_id": "vor-0005",
                    "title": "Кабель оптический OM4",
                    "quantity": 400,
                    "unit": "м.п",
                },
            ]
        },
        "Прокладка в металлическом лотке; количество Cat.6A дано бухтами по 500 м.",
    )

    assert "задай один короткий уточняющий вопрос" in prompt
    assert "ДОПУЩЕНИЕ" in prompt
    assert "vor-0004: Кабель U/UTP Cat.6A — 4 шт." in prompt
    assert "vor-0005: Кабель оптический OM4 — 400 м.п" in prompt
    assert "Прокладка в металлическом лотке" in prompt


def test_smeta_clarification_prompt_does_not_invent_missing_assumptions():
    prompt = _smeta_clarification_prompt({"open_items": []})

    assert "[не указаны — выбери явное ДОПУЩЕНИЕ или задай один вопрос]" in prompt
    assert "Не оставляй строку пустой" in prompt
    assert "существенно меняет применимость нормы/стоимость" in prompt


def test_smeta_machine_decisions_are_localized_for_operator_ui():
    assert _smeta_decision_label("unbound") == "Норма не привязана"
    assert _smeta_decision_label("bind") == "Норма привязана"
    assert _smeta_decision_label("ГЭСНм10") == "ГЭСНм10"


def test_smeta_conflict_codes_are_localized_at_ui_boundary():
    assert _smeta_conflict_ui({
        "code": "unbound_search_intent_narrow",
        "claim": "Unbound is based on one intent",
    }) == (
        "Узкий поиск нормы",
        "Норма оставлена без привязки после слишком узкого поиска. Расширьте варианты или примите решение явно.",
    )
    assert _smeta_conflict_ui({"code": "new_machine_code", "claim": "Raw English"})[1] == (
        "Проверьте условия выбора нормы перед фиксацией."
    )


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
        self.__class__.last_url = url
        self.__class__.last_json = json
        return _FakeLlmResponse()


@pytest.mark.asyncio
async def test_free_mode_injects_session_memory(monkeypatch):
    monkeypatch.setattr(
        chat_router,
        "_effective_model_connection_mode",
        lambda: chat_router.CanonicalRouteMode.LEGACY,
    )
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
    assert _FakeAsyncClient.last_url == "http://llm/chat"
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
    assert '("inventory", project_inventory_prompt)' in source
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


def test_chat_prompt_uses_canonical_typed_context_order():
    source = inspect.getsource(
        chat_evidence_application_service._execute_chat_evidence_application
    )

    assert [kind.value for kind in ContextKind] == [
        "profile_prefix",
        "tool_shortlist",
        "request",
        "evidence",
        "source_map",
        "tool_exchange",
        "checkpoint",
        "working_memory",
        "dialogue",
    ]
    assert "working_memory=answer_working_memory" in source
    assert "evidence=[" in source
    assert "source_map=(() if model_driven_retrieval else answer_source_map)" in source
    assert "tool_exchange=answer_tool_exchange" in source
    assert "dialogue=[session_block] if session_block else []" in source


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
    assert "/api/rag/documents?dataset_id=" in source
    assert "registry.get(\"documents\")" in source
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


def test_scope_selector_uses_human_cards_and_visible_selection_count():
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "sov-scope-option-card" in source
    assert "display_name" in source
    assert "Выбрано:" in source
    assert "Применить выбор" in source
    assert ".sov-scope-option-card" in styles
    assert ".sov-scope-file-badge" in styles
    assert ".sov-scope-file-ask" in styles


def test_chat_history_restores_saved_file_artifacts():
    source = inspect.getsource(chat_page.build_chat)

    assert '_register_artifact_downloads(msg.get("meta"))' in source
    assert "def _clear_file_artifacts" in source
    assert "_clear_file_artifacts()" in source


def test_chat_sources_use_stable_links_and_consolidated_artifact():
    source = inspect.getsource(chat_page.build_chat)

    assert "citation_sources" in source
    assert '(meta or {}).get("source_map")' in source
    assert "Источники и цитаты" in source
    assert "Источники ответа" in source
    assert "_show_sources_artifact" in source
    assert 'if not isinstance(meta.get("source_map"), list)' in source


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
    assert "12,3 с" in labels
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


def test_operator_status_chips_show_long_answer_time_in_minutes():
    chips = _operator_status_chips(
        "MODEL_OUTPUT",
        {"latency_phases": {"total": 183.381}},
        [],
    )

    assert [chip["label"] for chip in chips] == ["3 мин 3 с"]


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
