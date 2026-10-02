import asyncio
import inspect
from datetime import datetime, timedelta, timezone
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


def test_explicit_continue_reopens_unresolved_terminal_packets_only():
    current = {"job_id": "own-job", "identity": {"session_id": "own-chat", "attachment_id": "source"},
               "remaining": ["АР!R14", "АР!R15", "ВК!R8"],
               "accepted_rows": [{"source_row": "АР!R13", "title": "Закрытая работа"}],
               "held_packet": {"terminal_packets": [{"locators": ["АР!R13", "АР!R14", "АР!R15"]}],
                               "reopened_locators": ["АР!R15"]}}
    payload = chat_page.lsr_explicit_resume_reopen_payload(
        {"job_id": "own-job", "session_id": "own-chat", "question": "Собери ЛСР"}, current)
    assert payload["reopen_locators"] == ["АР!R14"]
    assert payload["attachment_id"] == "source" and payload["repack"] is False
    assert current["remaining"] == ["АР!R14", "АР!R15", "ВК!R8"]
    assert current["accepted_rows"][0]["source_row"] == "АР!R13"


def test_explicit_continue_preserves_active_native_read_cursor():
    current = {"job_id": "j", "identity": {"session_id": "s"}, "remaining": ["Лист!R4"],
               "held_packet": {"locators": ["Лист!R4"], "model_read_pending": True}}
    assert chat_page.lsr_explicit_resume_reopen_payload({"job_id": "j", "session_id": "s"}, current) is None
    assert current["held_packet"]["model_read_pending"] is True


def test_explicit_continue_does_not_reopen_during_detached_generation():
    current = {"job_id": "j", "status": "running", "identity": {"session_id": "s"},
               "remaining": ["Лист!R4"], "held_packet": {
                   "terminal_model_result_saved": True, "locators": ["Лист!R4"]}}
    with pytest.raises(ValueError, match="уже выполняется"):
        chat_page.lsr_explicit_resume_reopen_payload({"job_id": "j", "session_id": "s"}, current)
    assert current["remaining"] == ["Лист!R4"]


@pytest.mark.parametrize("resume", [{"job_id": "other", "session_id": "s"},
                                    {"job_id": "j", "session_id": "other"}])
def test_explicit_continue_rejects_foreign_job_or_session(resume):
    with pytest.raises(ValueError):
        chat_page.lsr_explicit_resume_reopen_payload(resume, {
            "job_id": "j", "identity": {"session_id": "s"}, "remaining": ["Лист!R4"],
            "held_packet": {"terminal_model_result_saved": True, "locators": ["Лист!R4"]}})


def test_lsr_position_numbers_resolve_through_delivered_revision():
    projection = [
        {"position_no": 14, "locator": "ВК!R104", "operation_id": "install"},
        {"position_no": 15, "locator": "ВК!R104", "operation_id": "supply"},
        {"position_no": 16, "locator": "АР!R7"},
    ]
    assert chat_page.resolve_lsr_position_selectors("14, 15;16", projection) == ["ВК!R104", "АР!R7"]
    assert chat_page.resolve_lsr_position_selectors("АР!R7", projection) == ["АР!R7"]
    with pytest.raises(ValueError, match="номер не найден"):
        chat_page.resolve_lsr_position_selectors("104", projection)
    with pytest.raises(ValueError, match="неоднозначен"):
        chat_page.resolve_lsr_position_selectors("14", projection + [{"position_no": 14, "locator": "ВК!R105"}])


def test_readiness_preserves_current_position_projection():
    rows = [{"position_no": 17, "locator": "СКС!R80"}]
    assert chat_page.lsr_readiness_card_spec({"row_projection": rows})["row_projection"] == rows
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
    format_job_ready_eta_line,
    format_lsr_resume_display,
    format_detached_stream_notice,
    format_in_progress_assembly_notice,
    format_paused_assembly_notice,
    format_workbook_assembly_notice,
    format_workbook_session_sys_notice,
    format_workbook_phase_label,
    merge_lsr_resume_payload,
    merge_chat_pending_progress,
    history_ai_is_pending,
    history_row_is_in_progress,
    completed_history_chat_payload,
    follow_detached_chat_history,
    fetch_active_workbook_research,
    hydrate_chat_pending_from_workbook,
    read_active_workbook_research,
    should_render_local_chat_pending,
    is_nicegui_slot_error,
    operator_background_ui_error,
    workbook_assembly_is_paused,
    workbook_assembly_is_running,
    workbook_chat_filename,
    workbook_job_to_pending_progress,
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


def test_chat_bubble_clock_always_includes_date():
    moscow = timezone(timedelta(hours=3))
    clock = format_chat_request_clock("2026-08-02T21:09:11+03:00", tz=moscow)
    assert clock == "02.08.2026 21:09"


def test_history_clock_converts_sqlite_utc_to_local_calendar():
    moscow = timezone(timedelta(hours=3))
    assert format_chat_request_clock("2026-09-01 22:40:37", tz=moscow) == "02.09.2026 01:40"
    assert format_chat_request_clock("2026-09-01T22:09:13", tz=moscow) == "02.09.2026 01:09"


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


def test_chat_request_accepts_comparative_acceptance_variant():
    assert ChatRequest(question="q").comparative_acceptance_variant is None
    assert (
        ChatRequest(question="q", comparative_acceptance_variant="b0_direct").comparative_acceptance_variant
        == "B0_DIRECT"
    )
    with pytest.raises(Exception, match="сравнительной приёмки"):
        ChatRequest(question="q", comparative_acceptance_variant="other")


def test_ai_plain_markdown_is_rendered_as_markdown_widget():
    source = inspect.getsource(chat_page.build_chat)

    assert "ui.markdown(_link_visible_sources(_disp, srcs or [], meta)).classes" in source
    assert "ui.markdown(_link_visible_sources(" in source


def test_chat_links_source_markers_to_anchored_drawer_rows_and_shows_three_counts():
    source = inspect.getsource(chat_page.build_chat)

    assert "link_source_markers" in source
    assert 'id={source_anchor_prefix}-{i}' in source
    assert 'id=source-list-{source_anchor_prefix}-{i}' in source
    assert 'anchor_prefix=_source_anchor_prefix(meta)' in source
    assert 'source_usage(source, i, answer)' in source
    assert 'def _render_rich_body(text: str, srcs: list | None = None, meta: dict | None = None)' in source
    assert '_link_visible_sources(ans, srcs or [], meta)' in source
    assert '_render_rich_body(str(text or ""), srcs or [], meta)' in source
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
    assert 'api_post(f"/api/workbook-research/{job_id}/pause"' in source
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


def test_chat_ui_projects_durable_document_state_into_readiness_card():
    def spec_for(document: dict | None) -> dict:
        return chat_page.lsr_readiness_card_spec({
            "dimensions": {
                "file": {"ready": document is not None and document.get("state") == "ready"},
                "coverage": {"complete": True},
                "norms": {"complete": True},
                "prices": {"complete": True},
            },
            "actions": [],
            "document": document,
        })

    ready = spec_for({
        "state": "ready",
        "label": "Файл готов",
        "note": "Последняя ревизия сохранена и доступна для скачивания.",
        "download_url": "/api/artifacts/rev-final/download",
    })
    assert ready["document"] == {
        "state": "ready",
        "label": "Файл готов",
        "note": "Последняя ревизия сохранена и доступна для скачивания.",
        "download_url": "/api/artifacts/rev-final/download",
        "tone": "ok",
    }
    # A finished document stays out of the repair-action list.
    assert ready["actions"] == []

    pending = spec_for({
        "state": "pending",
        "label": "Файл не готов",
        "note": "Задание завершено, но итоговый файл не сохранён.",
        "download_url": "",
    })
    assert pending["document"]["state"] == "pending"
    assert pending["document"]["tone"] == "warn"
    assert pending["document"]["download_url"] == ""

    # Readiness without a durable projection still renders a card.
    assert spec_for(None)["document"]["state"] == "none"


def test_chat_ui_splits_lsr_readiness_and_rebuilds_without_model():
    source = inspect.getsource(chat_page.build_chat)
    spec = chat_page.lsr_readiness_card_spec({
        "dimensions": {
            "file": {"ready": False, "action": "Пересоберите файл без модели."},
            "coverage": {
                "complete": False,
                "gap_count": 1,
                "action": "Закройте покрытие исходника.",
                "gaps": [{"locator": "СКС!R3", "action": "Укажите роль строки СКС!R3."}],
            },
            "norms": {
                "complete": False,
                "gap_count": 1,
                "action": "Продолжите незакрытые строки.",
                "gaps": [{"locator": "СКС!R3", "action": "Модель должна выбрать норму для строки СКС!R3."}],
            },
            "prices": {"complete": False, "gap_count": 1, "action": "Задайте цены."},
        },
        "actions": [
            {"id": "repack", "label": "Пересобрать файл"},
            {"id": "resume", "label": "Продолжить незакрытые строки"},
            {"id": "refine", "label": "Уточнить выбранные строки"},
            {"id": "enter_data", "label": "Внести подтверждённые данные"},
        ],
        "continue_action": "Источники сохранены.",
        "technical_complete": False,
        "estimate_complete": False,
    })

    assert spec["file_tone"] == "error"
    assert spec["coverage_tone"] == "warn"
    assert spec["norms_tone"] == "warn"
    assert spec["prices_tone"] == "warn"
    assert spec["gap_locators"] == ["СКС!R3"]
    assert "/api/chat/repack-lsr" in source
    assert "/api/chat/patch-lsr-rows" in source
    assert "Пересобрать файл" in source
    assert "Продолжить незакрытые строки" in source
    assert "Уточнить выбранные строки" in source
    assert "Внести подтверждённые данные" in source
    assert "status_badge(spec[\"file_label\"]" in source
    assert "status_badge(spec[\"coverage_label\"]" in source
    assert "text_field(" in source
    assert "result_readiness" in source
    assert "_rebuild_files_artifacts_panel" in source
    assert "sov-artifacts-scroll" in source
    assert 'label="Номер позиции"' in source
    assert "Что осталось закрыть" in source


def test_chat_ui_shows_latest_workbook_first_and_explains_lsr_fields():
    ordered = chat_page.order_chat_file_artifacts({
        "/old": {"name": "LSR_1452.xlsx", "kind": "xlsx"},
        "/new": {"name": "LSR_1506.xlsx", "kind": "xlsx"},
        "/note": {"name": "note.pdf", "kind": "pdf"},
    })
    source = inspect.getsource(chat_page.build_chat)
    tokens = Path("sovushka/uikit/tokens.py").read_text(encoding="utf-8")

    assert [item[1]["name"] for item in ordered] == [
        "LSR_1506.xlsx",
        "LSR_1452.xlsx",
        "note.pdf",
    ]
    assert ordered[0][2] == "Текущий файл"
    assert ordered[1][2] == "Предыдущая ревизия"
    assert "Новый файл в артефактах" in source
    assert "Продолжаю незакрытые строки" in source
    assert 'placeholder="14, 15, 16"' in source
    assert "resolve_lsr_position_selectors" in source
    assert chat_page.LSR_REFINE_FIELD_HELP
    assert chat_page.LSR_LOCATOR_FIELD_HELP
    assert "notify_in_element" in source
    assert "def _notify(" in source
    assert "format_job_ready_eta_line" in source
    assert "sov-chat-eta" in source
    assert "applied_result" in source
    assert ".sov-artifacts-scroll" in tokens
    assert ".sov-lsr-field-help" in tokens
    assert ".sov-file-card--current" in tokens
    assert ".sov-chat-eta" in tokens


def test_chat_ready_eta_and_slot_error_stay_operator_facing():
    started = datetime(2026, 1, 1, 0, 0, 0)
    now_ts = (started + timedelta(seconds=100)).timestamp()

    assert format_job_ready_eta_line(
        started.isoformat(), 0, 20, running=True, now_ts=now_ts
    ) == ""
    seeded = format_job_ready_eta_line(
        started.isoformat(),
        0,
        52,
        running=True,
        now_ts=now_ts,
        prior_completed=23,
        prior_elapsed_seconds=1500,
    )
    assert seeded.startswith("Результат будет готов примерно через ~")
    line = format_job_ready_eta_line(
        started.isoformat(), 5, 20, running=True, now_ts=now_ts
    )
    assert line.startswith("Результат будет готов примерно через ~")
    assert format_lsr_resume_display(
        {"remaining_locators": ["СКС!R3"] * 52, "catalog_work_count": 75}
    ) == (
        "Продолжаю незакрытые строки: осталось 52, уже принято 23. "
        "Поиск по принятым решениям не повторяется."
    )
    merged = merge_lsr_resume_payload(
        {"job_id": "wrj_1", "question": "Собери ЛСР"},
        {"remaining_locators": ["СКС!R4"], "catalog_work_count": 75},
    )
    assert merged["remaining_locators"] == ["СКС!R4"]
    assert merged["catalog_work_count"] == 75
    assert is_nicegui_slot_error(
        "The current slot cannot be determined because the slot stack for this task is empty."
    )
    assert "Файл собран" in operator_background_ui_error(
        "The current slot cannot be determined because the slot stack for this task is empty."
    )
    assert operator_background_ui_error("disk full") == "disk full"
    chat_src = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    resume_src = chat_src.split("async def _resume_lsr_packets", 1)[1].split(
        "async def _refine_lsr_rows", 1
    )[0]
    assert "ui.notify(" not in resume_src
    assert "_notify(" in resume_src
    assert "Продолжаю незакрытые строки" in resume_src
    assert "force_mode=\"estimator\"" in resume_src
    assert "display_question=" in resume_src
    assert "await send_chat()" not in resume_src
    assert "chat_input.value = question" not in resume_src
    assert "def _notify(" in chat_src
    assert "except Exception as notify_exc:" in chat_src
    apply_src = chat_src.split("def _apply_chat_result", 1)[1].split("stream_state =", 1)[0]
    register_at = apply_src.find("_register_artifact_downloads(meta)")
    live_at = apply_src.find("_render_smeta_live_rows(final=True)")
    assert register_at != -1 and live_at != -1 and register_at < live_at
    notice_src = inspect.getsource(format_in_progress_assembly_notice)
    send_src = inspect.getsource(chat_page.build_chat)
    assert "Соединение прервано после начала сборки" not in notice_src
    assert "Соединение прервано после начала сборки" not in send_src
    assert "format_detached_stream_notice" in chat_src
    assert "format_in_progress_assembly_notice" in chat_src
    assert "should_render_local_chat_pending" in chat_src
    assert "follow_detached_chat_history" in chat_src
    assert "history_ai_is_pending" in chat_src
    assert "Связь с окном чата пропала" not in notice_src
    assert "Связь с окном чата пропала" not in send_src
    assert "Запрос выполняется:" not in send_src


def test_overnight_sse_drop_is_not_a_job_death():
    notice = format_in_progress_assembly_notice()
    source = inspect.getsource(chat_page.build_chat)

    assert notice.startswith("Сборка продолжается")
    assert "Не нажимайте «Продолжить»" in notice
    assert "Связь с окном чата пропала" not in notice
    assert "format_in_progress_assembly_notice" in source
    assert "should_render_local_chat_pending" in source
    assert "Соединение прервано после начала сборки" not in source
    assert "Запрос выполняется:" not in source
    assert history_ai_is_pending({"role": "ai", "crag": "PENDING", "text": ""}) is True
    assert history_ai_is_pending({
        "role": "ai",
        "crag": "UNVALIDATED",
        "text": "готово",
    }) is False
    pending_history = [
        {"role": "user", "text": "Собери ЛСР"},
        {"role": "ai", "crag": "PENDING", "text": ""},
    ]
    assert completed_history_chat_payload(pending_history) is None
    assert should_render_local_chat_pending(
        pending_history,
        {"question": "Собери ЛСР"},
    ) is False
    assert should_render_local_chat_pending(
        [{"role": "user", "text": "Собери ЛСР"}],
        {"question": "Собери ЛСР"},
    ) is True
    assert should_render_local_chat_pending(
        [
            {"role": "ai", "text": "Связь с окном чата пропала, но сборка на сервере продолжается.", "crag": ""},
        ],
        {"question": "Собери ЛСР"},
    ) is False
    assert history_row_is_in_progress({
        "role": "ai",
        "text": "Запрос выполняется: Собери ЛСР, Санкт-Петербург",
        "crag": "",
    }) is True
    merged = merge_chat_pending_progress(
        {"question": "Собери ЛСР"},
        {
            "workbook_research_job_id": "job-1",
            "completed": 24,
            "total": 75,
            "remaining": 51,
            "label": "поиск норм",
        },
    )
    counted = format_in_progress_assembly_notice(merged)
    assert "24/75" in counted
    assert "осталось 51" in counted
    started = datetime(2026, 9, 17, 17, 0, 0)
    now_ts = (started + timedelta(seconds=3600)).timestamp()
    live = format_in_progress_assembly_notice(
        {
            "accepted": 24,
            "total": 75,
            "remaining": 51,
            "phase": "packets",
            "sheet": "СКС",
            "created_at": started.isoformat(sep=" ", timespec="seconds"),
            "started_at": started.isoformat(sep=" ", timespec="seconds"),
            "job_status": "running",
        },
        now_ts=now_ts,
    )
    assert "24/75" in live
    assert "осталось 51" in live
    assert "лист «СКС»: поиск норм" in live
    assert "с начала задачи 1ч 0м" in live
    assert "Результат будет готов примерно через" in live
    assert format_workbook_phase_label("packets", "СКС") == "лист «СКС»: поиск норм"
    assert "fetch_active_workbook_research" in source
    assert "workbook_job_to_pending_progress" in source
    assert "_paint_in_progress_bubble" in source
    done = completed_history_chat_payload([
        {"role": "user", "text": "Собери ЛСР"},
        {
            "role": "ai",
            "text": "ЛСР собрана",
            "crag": "UNVALIDATED",
            "meta": {"artifact": {"filename": "LSR.xlsx"}},
        },
    ])
    assert done is not None
    assert done["answer"] == "ЛСР собрана"
    assert done["artifact"]["filename"] == "LSR.xlsx"
    assert completed_history_chat_payload([
        {
            "role": "ai",
            "text": "ЛСР не создана: после поиска источников таблица строк не получена.",
            "crag": "UNVALIDATED",
        },
        {"role": "user", "text": "Собери ЛСР, Санкт-Петербург, цены 3 квартал 2026"},
        {"role": "ai", "text": "", "crag": "PENDING"},
    ]) is None
    assert completed_history_chat_payload([
        {
            "role": "ai",
            "text": "ЛСР не создана: после поиска источников таблица строк не получена.",
            "crag": "UNVALIDATED",
        },
        {"role": "user", "text": "Собери ЛСР, Санкт-Петербург, цены 3 квартал 2026"},
    ]) is None
    assert "hydrate_chat_pending_from_workbook" in source
    assert "_hydrate_running_workbook_progress" in source
    ng = Path("sovushka_ng.py").read_text(encoding="utf-8")
    assert "reconnect_timeout=43200" in ng
    assert format_detached_stream_notice() == format_in_progress_assembly_notice()


@pytest.mark.asyncio
async def test_follow_detached_chat_history_waits_out_pending():
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        if calls["n"] < 3:
            return [
                {"role": "user", "text": "Собери ЛСР"},
                {"role": "ai", "text": "", "crag": "PENDING"},
            ]
        return [
            {"role": "user", "text": "Собери ЛСР"},
            {
                "role": "ai",
                "text": "ЛСР собрана",
                "crag": "UNVALIDATED",
                "meta": {"artifact": {"filename": "LSR.xlsx"}},
            },
        ]

    payload = await follow_detached_chat_history(
        fetch_history=fetch,
        interval_sec=0,
        timeout_sec=10,
    )
    assert payload is not None
    assert payload["answer"] == "ЛСР собрана"
    assert payload["artifact"]["filename"] == "LSR.xlsx"
    assert calls["n"] == 3

    polls = {"n": 0}

    async def fetch_pending_only():
        return [
            {"role": "user", "text": "Собери ЛСР"},
            {"role": "ai", "text": "", "crag": "PENDING"},
        ]

    async def on_poll(_rows):
        polls["n"] += 1
        return polls["n"] < 2

    still_pending = await follow_detached_chat_history(
        fetch_history=fetch_pending_only,
        on_poll=on_poll,
        interval_sec=0,
        timeout_sec=10,
        clock=lambda: 0 if polls["n"] < 3 else 100,
    )
    assert still_pending is None
    assert polls["n"] >= 1

    stale_calls = {"n": 0}

    async def fetch_old_answer_then_file():
        stale_calls["n"] += 1
        older = {
            "role": "ai",
            "text": "ЛСР не создана: после поиска источников таблица строк не получена.",
            "crag": "UNVALIDATED",
        }
        user = {"role": "user", "text": "Собери ЛСР, Санкт-Петербург"}
        if stale_calls["n"] < 3:
            return [older, user, {"role": "ai", "text": "", "crag": "PENDING"}]
        return [
            older,
            user,
            {
                "role": "ai",
                "text": "ЛСР собрана",
                "crag": "UNVALIDATED",
                "meta": {"artifact": {"filename": "LSR.xlsx"}},
            },
        ]

    async def job_still_running(_rows):
        return stale_calls["n"] < 3

    recovered = await follow_detached_chat_history(
        fetch_history=fetch_old_answer_then_file,
        on_poll=job_still_running,
        interval_sec=0,
        timeout_sec=10,
    )
    assert recovered is not None
    assert recovered["answer"] == "ЛСР собрана"
    assert stale_calls["n"] == 3


@pytest.mark.asyncio
async def test_history_open_restores_running_workbook_bubble():
    async def fetch_job(*, session_id="", job_id=""):
        assert session_id == "session-live"
        assert job_id == ""
        return {
            "job_id": "wrj_sks",
            "identity": {"session_id": "session-live"},
            "status": "running",
            "phase": "packets",
            "sheet": "СКС",
            "created_at": "2026-09-17 14:01:20",
            "accepted_rows": [{"source_row": "СКС!R6", "row_role": "material"}],
            "remaining": [f"СКС!R{n}" for n in range(48, 78)],
            "work_total": 75,
            "status_dimensions": {"remaining": 30, "work_total": 75},
            "held_packet": {
                "locators": ["СКС!R48", "СКС!R49", "СКС!R50"],
                "queries": ["q1", "q2"],
            },
        }

    pending = await hydrate_chat_pending_from_workbook(
        session_id="session-live",
        pending={"job_id": "wrj_other"},
        fetch_job=fetch_job,
        ignore_prior_job_id=True,
    )
    assert pending is not None
    assert pending["job_id"] == "wrj_sks"
    assert pending["total"] == 75
    assert pending["remaining"] == 30
    history = [
        {
            "role": "ai",
            "text": "ЛСР не создана: после поиска источников таблица строк не получена.",
            "crag": "UNVALIDATED",
        },
        {"role": "user", "text": "Собери ЛСР, Санкт-Петербург, цены 3 квартал 2026"},
    ]
    assert should_render_local_chat_pending(history, pending) is True
    notice = format_in_progress_assembly_notice(pending)
    assert "45/75" in notice
    assert "пакет 3 строк" in notice


@pytest.mark.asyncio
async def test_history_switch_clears_old_progress_when_selected_session_has_no_job():
    async def fetch_job(**kwargs):
        assert kwargs["session_id"] == "session-finished" and kwargs["job_id"] == ""
        return None
    assert await hydrate_chat_pending_from_workbook(session_id="session-finished",
        pending={"job_id": "wrj_other", "accepted": 25, "remaining": 39},
        ignore_prior_job_id=True, fetch_job=fetch_job) is None


@pytest.mark.asyncio
async def test_history_selection_rejects_foreign_global_reconnect_job():
    async def fetch_job(**kwargs):
        return {"job_id": "wrj_other", "identity": {"session_id": "session-running"}, "status": "running"}
    assert await hydrate_chat_pending_from_workbook(session_id="session-finished",
        pending={"job_id": "wrj_other"}, ignore_prior_job_id=True, fetch_job=fetch_job) is None


@pytest.mark.asyncio
async def test_selected_history_poll_ignores_foreign_pinned_job_and_keeps_own_job(monkeypatch):
    import sovushka.pages.chat as page
    own = {"job_id": "wrj_own", "identity": {"session_id": "session-selected"}, "status": "running"}
    other = {"job_id": "wrj_other", "identity": {"session_id": "session-other"}, "status": "running"}
    async def getter(path):
        return other if path.endswith("/wrj_other") else {"jobs": [other, own]}
    monkeypatch.setattr(page, "read_active_workbook_research", lambda **kwargs: None)
    fetched = await fetch_active_workbook_research(session_id="session-selected", job_id="wrj_other",
        getter=getter, allow_foreign_session=False)
    assert fetched == own


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_foreign", [False, True])
async def test_selected_history_prefers_latest_finished_document_over_older_paused_step(monkeypatch, allow_foreign):
    import sovushka.pages.chat as page
    old = {"job_id": "wrj_old", "identity": {"session_id": "session-selected"}, "status": "paused",
        "remaining": ["Лист!R3"], "accepted_rows": [{"source_row": "Лист!R2", "row_role": "work"}]}
    latest = {"job_id": "wrj_latest", "identity": {"session_id": "session-selected"}, "status": "complete",
        "continues_job_id": "wrj_old", "document": {"state": "ready", "artifact_kind": "vor_workbook",
        "final_revision_id": "rev_current"}}
    async def getter(path):
        if path.startswith("/api/workbook-research-last?"):
            return {"found": True, "job": latest}
        return {"jobs": []}
    monkeypatch.setattr(page, "read_active_workbook_research", lambda **kwargs: old)
    fetched = await fetch_active_workbook_research(session_id="session-selected", getter=getter,
        allow_foreign_session=allow_foreign)
    assert fetched == latest
    async def fetch_job(**kwargs):
        return fetched
    pending = await hydrate_chat_pending_from_workbook(session_id="session-selected", pending={"job_id": "wrj_old"},
        fetch_job=fetch_job, ignore_prior_job_id=True)
    assert pending["document"]["final_revision_id"] == "rev_current"
    assert "current.xlsx" in format_workbook_session_sys_notice(pending)


def test_selected_history_local_fallback_reads_latest_terminal_state():
    latest = {"job_id": "wrj_latest", "status": "complete", "identity": {"session_id": "session-selected"}}
    old = {"job_id": "wrj_old", "status": "paused", "identity": {"session_id": "session-selected"}}
    class Service:
        def latest(self, *, session_id):
            assert session_id == "session-selected"
            return latest
        def list_open(self, **kwargs):
            return [old]
    assert read_active_workbook_research(session_id="session-selected", service=Service(), prefer_latest=True) == latest
    assert read_active_workbook_research(session_id="session-selected", service=Service()) == old


@pytest.mark.asyncio
async def test_reconnect_progress_uses_workbook_checkpoint(tmp_path):
    from proxy.services.workbook_research_job_service import WorkbookResearchJobService

    service = WorkbookResearchJobService(tmp_path / "meta.db")
    identity = service.identity(
        session_id="session-live",
        attachment_id="read_123456abcdef",
        source_sha256="a" * 64,
        dataset_ids=["smeta"],
        profile_revision_id="factory",
        model_identity="qwen-35b",
        question="Собери ЛСР",
    )
    job = service.begin_or_resume(identity)
    service.record_packet(
        job["job_id"],
        sheet="СКС",
        packet_locators=["СКС!R2"],
        accepted_rows=[
            {"source_row": "СКС!R2", "norm_code": "10-01-001-01", "row_role": "work"},
        ],
        evidence=[],
        remaining=["СКС!R3", "СКС!R4"],
    )
    live = read_active_workbook_research(
        session_id="session-live",
        service=service,
    )
    assert live is not None
    pending = workbook_job_to_pending_progress(live)
    assert pending["accepted"] == 1
    assert pending["total"] == 3
    assert pending["remaining"] == 2
    assert pending["job_id"] == job["job_id"]
    notice = format_in_progress_assembly_notice(pending)
    assert "1/3" in notice
    assert "осталось 2" in notice
    assert "поиск норм" in notice
    sks_roles = workbook_job_to_pending_progress(
        {
            "job_id": "wrj_sks",
            "status": "running",
            "phase": "packets",
            "sheet": "СКС",
            "accepted_rows": [
                {"source_row": "СКС!R6", "row_role": "equipment"},
                {"source_row": "СКС!R7", "row_role": "material"},
            ]
            + [{"source_row": f"СКС!R{n}", "row_role": "material"} for n in range(8, 41)],
            "remaining": [f"СКС!R{n}" for n in range(48, 78)],
            "status_dimensions": {"remaining": 30, "work_total": 75},
            "work_total": 75,
            "packet_locators": ["СКС!R48", "СКС!R49", "СКС!R50"],
            "held_packet": {
                "locators": ["СКС!R48", "СКС!R49", "СКС!R50"],
                "queries": [f"q{n}" for n in range(85)],
            },
        }
    )
    assert sks_roles["accepted"] == 45
    assert sks_roles["remaining"] == 30
    assert sks_roles["total"] == 75
    assert sks_roles["held_queries"] == 85
    assert sks_roles["packet_size"] == 3
    sks_notice = format_in_progress_assembly_notice(sks_roles)
    assert "0/30" not in sks_notice
    assert "35/65" not in sks_notice
    assert "45/75" in sks_notice
    assert "ещё 85 запросов" in sks_notice
    utc_job = workbook_job_to_pending_progress(
        {
            "job_id": "wrj_utc",
            "created_at": "2026-09-17 14:01:20",
            "remaining": ["СКС!R48"],
            "work_total": 75,
            "status_dimensions": {"remaining": 1},
        }
    )
    utc_start = datetime(2026, 9, 17, 14, 1, 20, tzinfo=timezone.utc)
    utc_notice = format_in_progress_assembly_notice(
        utc_job,
        now_ts=(utc_start + timedelta(minutes=110)).timestamp(),
    )
    assert "1ч 50м" in utc_notice
    assert "4ч" not in utc_notice
    live_notice = format_in_progress_assembly_notice(
        {
            "accepted": 45,
            "total": 75,
            "remaining": 30,
            "phase": "packets",
            "sheet": "СКС",
            "created_at": "2026-09-17 14:01:20+00:00",
            "started_at": "2026-09-17 14:01:20+00:00",
            "job_status": "running",
            "packet_size": 3,
            "held_queries": 16,
        }
    )
    assert "45/75" in live_notice
    assert "ещё 16 запросов" in live_notice
    paused_job = workbook_job_to_pending_progress(
        {
            "job_id": "wrj_sks",
            "status": "paused",
            "phase": "packets",
            "sheet": "СКС",
            "accepted_rows": [
                {"source_row": f"СКС!R{n}", "row_role": "material"} for n in range(6, 71)
            ],
            "remaining": [
                "СКС!R3", "СКС!R4", "СКС!R5", "СКС!R12", "СКС!R13", "СКС!R14",
            ] + [f"СКС!R{n}" for n in range(18, 60)],
            "work_total": 75,
            "status_dimensions": {"remaining": 48, "work_total": 75},
        }
    )
    assert paused_job["accepted"] == 27
    assert paused_job["remaining"] == 48
    assert paused_job["total"] == 75
    assert workbook_assembly_is_running(paused_job) is False
    assert workbook_assembly_is_paused(paused_job) is True
    paused_notice = format_workbook_assembly_notice(paused_job)
    assert paused_notice == format_paused_assembly_notice(paused_job)
    assert "Сборка продолжается" not in paused_notice
    assert "27/75" not in paused_notice
    assert "Результат будет готов" not in paused_notice
    assert "не идёт" in paused_notice
    assert "48 из 75" in paused_notice
    assert "черновик" in paused_notice
    assert format_workbook_session_sys_notice(paused_job) == (
        "Первый проход закончен. Сборка сейчас не идёт."
    )
    chat_src = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    assert "format_paused_assembly_notice" in chat_src
    assert "list_open(" in chat_src
    follow_src = chat_src.split("async def _follow_pending_history_if_needed", 1)[1].split(
        "asyncio.create_task(_load_history())", 1
    )[0]
    assert "if job_paused:" in follow_src
    assert "bool(job):" not in follow_src.split("async def _poll_workbook_progress", 1)[1][:900]

    async def getter(path: str):
        if path.startswith("/api/workbook-research-active"):
            return {"jobs": [live], "count": 1}
        if path.endswith(job["job_id"]):
            return live
        return None

    fetched = await fetch_active_workbook_research(
        session_id="session-live",
        getter=getter,
    )
    assert fetched["job_id"] == job["job_id"]


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
    # Пин 28.08 запрещал «Новый чат» в этом меню, потому что кнопка была в
    # топбаре. Замер 812 в узком окне (≤ 900 px) показал, что вместе с
    # `.sov-topbar-icon-action` скрывается и сама кнопка, а меню заменяющее
    # топбар остаётся без «Нового чата» — начать новую сессию было нельзя.
    assert 'ui.menu_item("Новый чат", on_click=lambda: _clear_chat())' in source
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


def test_chat_composer_keeps_status_banner_out_of_the_action_row():
    """Композер не должен ничего накладывать на поле ввода.

    Отчёт заказчика: «Сборка остановилась…» и «Продолжить» легли поверх
    строки ввода и вылезли за рамку. ``.sov-composer`` — авторастущая
    textarea без запаса по высоте, поэтому любой абсолютный слой внутри
    неё накрывает текст, а nowrap-ряд кнопок на узкой ширине уходит за
    левый край рамки. Баннер живёт НАД композером, ряд действий — ПОД
    полем ввода в обычном потоке и переносится.
    """
    source = inspect.getsource(chat_page.build_chat)
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")
    uikit = Path("sovushka/uikit/tokens.py").read_text(encoding="utf-8")

    banner = source.index('classes("sov-lsr-stalled-row items-center")')
    composer = source.index('classes("sov-composer") as composer_box')
    footer = source.index('classes("sov-composer-footer")')
    assert banner < composer < footer

    footer_rule = styles.split(".sov-composer-footer {", 1)[1].split("}", 1)[0]
    assert "position: static" in footer_rule
    assert "position: absolute" not in footer_rule

    actions_rule = uikit.split(".sov-composer-actions {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: wrap" in actions_rule
    assert "flex-wrap: nowrap" not in actions_rule

    banner_rule = styles.split(".sov-lsr-stalled-row {", 1)[1].split("}", 1)[0]
    assert "align-self: center" in banner_rule
    assert "width: calc(100% - 48px)" in banner_rule
    assert "max-width: 1440px" in banner_rule
    assert ".sov-lsr-stalled-row" not in uikit
    assert "flex: 0 1 152px" in uikit


def test_a_new_chat_clears_the_status_the_thread_clear_cannot_reach():
    """«Новый чат» не оставляет ни чужую сборку, ни чужой файл.

    Отчёт заказчика: «В новом чате, да и в целом в чате вот так криво
    отражается все».  Замер 812 на установленной сборке сразу после нажатия
    «Новый чат»: нитка пуста (`messageCount` 0, заголовок «Новый чат»), но над
    полем ввода осталась полоса «Сборка остановилась: сервер не обновляет
    чекпоинт» с кнопкой «Продолжить» от предыдущей задачи (и через +1.5 с тоже),
    а строка вложений держала файл прошлой беседы («attach_probe.xlsx · В чат»).
    Оба виджета нарисованы ВНЕ ``chat_column``, поэтому ``clear()`` их не снимает,
    а ``_paint_in_progress_bubble`` после очистки больше не вызывается — прятать
    надо явно, иначе пустой новый чат открывается чужой сборкой.
    """
    source = inspect.getsource(chat_page.build_chat)

    reset = source.split("def _reset_transient_chat_status", 1)[1].split(
        "def _clear_chat():", 1
    )[0]
    assert "lsr_stalled_row.set_visibility(False)" in reset
    assert "_clear_attachment(notify=False)" in reset
    assert '_pending_target_files["v"] = []' in reset
    assert "_follow_placeholder" in reset

    clear = source.split("def _clear_chat():", 1)[1].split("\n    _sending = ", 1)[0]
    assert "_reset_transient_chat_status()" in clear
    # Порядок — часть контракта: сброс снимает ссылки на пузырь прогресса, а сам
    # пузырь лежит в колонке, которую очищают первой.
    assert clear.index("chat_column.clear()") < clear.index("_reset_transient_chat_status()")
    assert clear.index("persist_chat_pending(None)") < clear.index(
        "_reset_transient_chat_status()"
    )


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


def test_chat_attachment_accepts_supported_xlsm_without_enabling_macro_execution(monkeypatch):
    from proxy.config import rag_upload_suffixes

    monkeypatch.delenv("RAG_UPLOAD_SUFFIXES", raising=False)
    assert ".xlsm" in rag_upload_suffixes()
    source = inspect.getsource(chat_page.build_chat)
    assert "accept=.xlsx,.xlsm,.xls,.csv,.pdf,.docx" in source
    monkeypatch.setenv("RAG_UPLOAD_SUFFIXES", ".pdf,.xlsx")
    assert rag_upload_suffixes() == {".pdf", ".xlsx"}


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

    async def _no_capability_probe(client):
        """Пробу возможностей связанной модели гасим явно.

        ``_refresh_stale_bound_model_capabilities`` читает постоянный реестр
        подключений (``%LOCALAPPDATA%\\LES``), а на стенде заказчика или после
        живого прогона там уже лежит ANSWER-биндинг со стёртым TTL. Тогда
        зонд зовёт ``client.stream`` на фейковом клиенте, и тест памяти
        падает не по своей вине.
        """
        return None

    monkeypatch.setattr(
        chat_router, "_refresh_stale_bound_model_capabilities", _no_capability_probe
    )

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


def test_operator_technical_chips_show_effective_native_growth_budget():
    meta = {"retrieval_trace": {"grouped_model_evidence_pages": [
        {"native_read_growth_budget": {"requested_tokens": 3000, "reserved_tokens": 1200,
                                       "source": "bound_answer_generation_reserve; capped_by_first_whole_group"}},
        {"source_count": 1},
    ]}}
    chips = _operator_technical_chips(meta)
    assert "Резерв чтений: запрос 3000, доступно 1200 токенов" in chips
    assert "Источник резерва: bound_answer_generation_reserve; capped_by_first_whole_group · без перезапуска" in chips
    assert all("Резерв чтений" not in item for item in _operator_technical_chips({}))
    direct = {"retrieval_trace": {"grouped_model_evidence": meta["retrieval_trace"]["grouped_model_evidence_pages"][0]}}
    assert "Резерв чтений: запрос 3000, доступно 1200 токенов" in _operator_technical_chips(direct)


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


def test_workbook_job_is_stalled_requires_running_and_old_checkpoint():
    now_ts = datetime(2026, 9, 21, 21, 0, tzinfo=timezone.utc).timestamp()
    fresh = {"job_status": "running", "updated_at": "2026-09-21 20:51:15"}
    assert not chat_page.workbook_job_is_stalled(fresh, now_ts=now_ts, threshold_sec=1200)
    stale = {"job_status": "running", "updated_at": "2026-09-21 20:21:15"}
    assert chat_page.workbook_job_is_stalled(stale, now_ts=now_ts, threshold_sec=1200)
    done = {"job_status": "complete", "updated_at": "2026-09-21 18:00:00"}
    assert not chat_page.workbook_job_is_stalled(done, now_ts=now_ts, threshold_sec=1200)
    assert not chat_page.workbook_job_is_stalled({"job_status": "running"}, now_ts=now_ts)


def test_lsr_resume_payload_from_job_matches_durable_identity():
    job = {
        "identity": {
            "session_id": "sess-1",
            "attachment_id": "read_8f574357c416",
            "dataset_ids": ["d1", "d2"],
        }
    }
    payload = chat_page.lsr_resume_payload_from_job(job, question="  Собери ЛСР  ")
    assert payload["question"] == "Собери ЛСР"
    assert payload["session_id"] == "sess-1"
    assert payload["attachment_id"] == "read_8f574357c416"
    assert payload["dataset_ids"] == ["d1", "d2"]
    assert payload["mode"] == "estimator"


# --------------------------------------------------------------------------- #
# A finished research must never restart itself (build 806, criterion 2).
# --------------------------------------------------------------------------- #
def test_terminal_job_with_ready_document_serves_the_last_revision() -> None:
    plan = chat_page.terminal_job_repair_plan(
        {
            "job_id": "wrj_1",
            "status": "complete",
            "document": {"state": "ready", "final_revision_id": "rev_final"},
        }
    )

    assert plan["mode"] == "document"
    assert plan["revision_id"] == "rev_final"
    # Showing the file is not "continuing" — nothing may reach the model.
    assert plan["mode"] != "resume"


def test_terminal_job_without_document_repairs_instead_of_researching() -> None:
    plan = chat_page.terminal_job_repair_plan(
        {
            "job_id": "wrj_1",
            "status": "complete",
            "document": {
                "state": "pending",
                "needs_document": True,
                "recovery_reason": "Задание завершено, но финальный файл не собран.",
            },
        }
    )

    assert plan["mode"] == "repack"
    assert plan["reason"] == "Задание завершено, но финальный файл не собран."


def test_draft_of_finished_job_is_repaired_not_reopened() -> None:
    plan = chat_page.terminal_job_repair_plan(
        {"job_id": "wrj_1", "status": "complete", "document": {"state": "draft_only"}}
    )

    assert plan["mode"] == "repack"


def test_open_job_keeps_the_real_continue_path() -> None:
    # ``failed`` stays on the continue path on purpose: the job service lists it
    # among RESUMABLE_STATUSES, so «Продолжить» is the operator's only retry.
    for status in ("running", "paused", "failed", "cancelled"):
        plan = chat_page.terminal_job_repair_plan(
            {"job_id": "wrj_1", "status": status, "document": {"state": "none"}}
        )
        assert plan["mode"] == "resume", status


def test_terminal_job_without_any_document_information_reports_only() -> None:
    # A projection the job never wrote must not invent a repair or a document.
    plan = chat_page.terminal_job_repair_plan({"job_id": "wrj_1", "status": "complete"})

    assert plan["mode"] == "report"


def test_terminal_statuses_are_the_job_service_statuses() -> None:
    from proxy.services.workbook_research_job_service import TERMINAL_STATUSES

    assert set(chat_page.TERMINAL_WORKBOOK_JOB_STATUSES) == set(TERMINAL_STATUSES)
    assert chat_page.workbook_job_is_terminal({"status": "Complete"}) is True
    assert chat_page.workbook_job_is_terminal({"job_status": "paused"}) is False


def test_restored_document_name_keeps_the_revision_identity() -> None:
    name = chat_page.terminal_revision_download_name(
        {"identity": {"source_name": "ВОР.xlsx"}}, "rev_17e60265abcd"
    )

    assert name.startswith("ЛСР")
    assert "17e60265" in name
    assert name.endswith(".xlsx")


def test_restored_vor_name_preserves_kind_without_claiming_quality():
    name = chat_page.terminal_revision_download_name(
        {"document": {"artifact_kind": "vor_workbook", "state": "ready"}}, "rev_current")
    assert name.startswith("ВОР")
    assert "готово" not in name


def test_reconnect_projection_preserves_vor_kind_in_terminal_notice():
    job = {"status": "complete", "document": {
        "state": "ready", "artifact_kind": "vor_workbook",
        "tool": "build_vor_workbook", "final_revision_id": "rev_current"}}
    pending = chat_page.workbook_job_to_pending_progress(job)
    notice = chat_page.format_terminal_assembly_notice(pending)
    assert "ВОР_current.xlsx" in notice
    assert "ЛСР_current.xlsx" not in notice
    assert pending["document"]["tool"] == "build_vor_workbook"


def test_restored_partial_lsr_name_comes_from_its_immutable_revision():
    name = chat_page.terminal_revision_download_name(
        {"document": {"artifact_kind": "lsr_workbook", "state": "ready"}}, "rev_current",
        metadata={"revision_id": "rev_current", "filename": "draft_LSR_Проект.xlsx"})
    assert name == "draft_LSR_Проект.xlsx"


def test_restored_document_does_not_take_another_revisions_name():
    name = chat_page.terminal_revision_download_name(
        {"document": {"artifact_kind": "vor_workbook", "state": "ready"}}, "rev_current",
        metadata={"revision_id": "rev_other", "filename": "Чужая_ЛСР.xlsx"})
    assert name.startswith("ВОР") and "current" in name
    assert "Чужая" not in name


def test_resume_stalled_handler_refuses_a_terminal_job_before_dispatching() -> None:
    """The «Продолжить» gesture must branch on the durable state, not resend."""

    source = inspect.getsource(chat_page)
    handler = source[source.index("async def _resume_stalled_lsr()"):]
    handler = handler[: handler.index("async def _follow_resume_stream")]

    assert "terminal_job_repair_plan(job)" in handler
    assert "_apply_terminal_job_plan" in handler
    # The guard sits before the resend, so a finished job can never reach
    # `/api/chat/stream` through this path.
    assert handler.index("terminal_job_repair_plan") < handler.index("_follow_resume_stream")


def test_reopened_session_restores_the_finished_research_file_state() -> None:
    source = inspect.getsource(chat_page)

    assert "/api/workbook-research-last?session_id=" in source
    loader = source[source.index("async def _load_history()"):]
    loader = loader[: loader.index("async def _fetch_session_history_messages")]
    assert "_restore_last_finished_research()" in loader


# --------------------------------------------------------------------------- #
# Re-entering a FINISHED research must show its file, not a progress bubble.
# Found on the installed build after the customer's ВОР reached its terminal
# job: the durable state said ``complete`` while the restored page still said
# "Сборка продолжается".
# --------------------------------------------------------------------------- #
def _finished_vor_job() -> dict:
    return {
        "job_id": "wrj_vor",
        "status": "complete",
        "phase": "declared_gaps",
        "sheet": "АР",
        "identity": {"session_id": "live-vor", "source_name": "ВОР.xlsx"},
        "accepted_rows": [{"source_row": "СКС!R6", "row_role": "work"}],
        "remaining": [],
        "document": {
            "state": "ready",
            "final_revision_id": "rev_962288fd",
            "draft_revision_id": "rev_2108237a",
            "needs_document": False,
        },
    }


def test_terminal_notice_names_the_last_revision_and_rules_out_a_new_research() -> None:
    notice = chat_page.format_terminal_assembly_notice(_finished_vor_job())

    assert "Последняя ревизия" in notice
    assert "962288fd" in notice
    assert "Сборка продолжается" not in notice
    assert "Новое исследование не запускается" in notice


def test_terminal_notice_for_a_job_without_a_file_offers_the_repair() -> None:
    job = _finished_vor_job()
    job["document"] = {"state": "pending", "needs_document": True}
    notice = chat_page.format_terminal_assembly_notice(job)

    assert "файла пока нет" in notice
    assert "без повторного поиска норм" in notice
    assert "Сборка продолжается" not in notice


def test_terminal_notice_points_at_the_control_that_is_actually_on_screen() -> None:
    """Текст не должен звать на кнопку, которую сборка 808 убрала.

    Для завершённого задания «Продолжить» больше не предлагается: карточка
    даёт «Скачать последнюю ревизию», а при незапакованном файле —
    «Пересобрать файл». Заказчик видел указание на несуществующую кнопку.
    """

    document_notice = chat_page.format_terminal_assembly_notice(_finished_vor_job())
    assert "«Скачать последнюю ревизию»" in document_notice
    assert "«Продолжить»" not in document_notice

    job = _finished_vor_job()
    job["document"] = {
        "state": "pending",
        "needs_document": True,
        "recovery_reason": "Сохранённые решения модели не пересматриваются.",
    }
    repack_notice = chat_page.format_terminal_assembly_notice(job)
    assert "«Пересобрать файл»" in repack_notice
    assert "«Продолжить»" not in repack_notice
    assert ".." not in repack_notice

    # «Продолжить» остаётся единственной выходной жестикуляции для failed:
    # сервис заданий перечисляет его в возобновляемых статусах.
    failed_notice = chat_page.format_terminal_assembly_notice(
        {"job_id": "wrj_f", "status": "failed", "document": {"state": "none"}}
    )
    assert "«Продолжить»" in failed_notice


def test_stopped_research_is_reported_as_stopped_not_as_running() -> None:
    notice = chat_page.format_terminal_assembly_notice(
        {"job_id": "wrj_x", "status": "failed", "document": {"state": "none"}}
    )

    assert "остановлена с ошибкой" in notice
    assert "Сборка продолжается" not in notice


def test_reconnect_bubble_of_a_finished_job_cannot_claim_the_build_is_running() -> None:
    pending = chat_page.workbook_job_to_pending_progress(
        _finished_vor_job(), {"job_id": "wrj_vor"}
    )

    # the durable file state travels with the bubble, so a restored client can
    # tell "finished" from "still assembling" without another request
    assert pending["document"]["final_revision_id"] == "rev_962288fd"
    assert chat_page.workbook_job_is_terminal(pending) is True
    notice = chat_page.format_workbook_assembly_notice(pending)
    assert "Сборка продолжается" not in notice
    assert "962288fd" in notice


def test_session_sys_notice_for_a_finished_job_is_not_the_running_line() -> None:
    pending = chat_page.workbook_job_to_pending_progress(_finished_vor_job(), {})

    assert (
        chat_page.format_workbook_session_sys_notice(pending)
        != "Сборка на сервере продолжается."
    )


def test_an_open_job_still_gets_the_real_progress_bubble() -> None:
    job = _finished_vor_job()
    job["status"] = "running"
    job["remaining"] = ["ОВиК!R12", "ОВиК!R13"]
    pending = chat_page.workbook_job_to_pending_progress(job, {})

    notice = chat_page.format_workbook_assembly_notice(pending)
    assert notice.startswith("Сборка продолжается")


# --------------------------------------------------------------------------- #
# A killed executor leaves its durable row on ``running`` forever. The customer
# re-entered exactly such a session: the bubble promised «Сборка продолжается…
# Файл появится в этой сессии», while the banner above the composer said the
# build had stopped. The bubble now reads the checkpoint age, like the banner.
# --------------------------------------------------------------------------- #
def _zombie_running_job() -> dict:
    return {
        "job_id": "wrj_2d8d71d5",
        "status": "running",
        "phase": "catalog",
        "identity": {"session_id": "acc785r2_1790102794", "source_name": "ВОР.xlsx"},
        "accepted_rows": [],
        "remaining": [],
        "created_at": "2026-09-22 18:46:35",
        "updated_at": "2026-09-22 18:46:35",
        "document": {"state": "none"},
    }


def _stalled_pending() -> dict:
    return chat_page.workbook_job_to_pending_progress(_zombie_running_job(), {})


def test_a_stalled_job_stops_announcing_a_build_that_is_not_happening() -> None:
    now_ts = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc).timestamp()
    pending = _stalled_pending()
    assert chat_page.workbook_job_is_stalled(pending, now_ts=now_ts, threshold_sec=1200)

    notice = chat_page.format_workbook_assembly_notice(pending, now_ts=now_ts)

    assert notice.startswith("Сборка остановилась")
    assert "Сборка продолжается" not in notice
    assert "Не нажимайте «Продолжить»" not in notice
    # the file is not coming, so the bubble must not promise it either
    assert "только после завершения сборки" in notice
    assert not notice.endswith("Файл появится в этой сессии.")
    assert "Ни одна строка ещё не принята" in notice


def test_the_stalled_bubble_points_at_the_row_that_actually_holds_the_button() -> None:
    now_ts = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc).timestamp()
    notice = chat_page.format_workbook_assembly_notice(_stalled_pending(), now_ts=now_ts)

    assert "«Продолжить» в строке над полем ввода" in notice
    assert "под полем ввода" not in notice
    source = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    assert "«Продолжить» под полем ввода" not in source


def test_session_sys_notice_of_a_stalled_job_says_stopped() -> None:
    assert (
        chat_page.format_workbook_session_sys_notice(_stalled_pending())
        == "Сборка остановлена: сервер не обновляет чекпоинт."
    )


def test_a_stalled_bubble_does_not_blink_as_if_the_server_were_working() -> None:
    painter = inspect.getsource(chat_page.build_chat)
    painter = painter[painter.index("def _paint_in_progress_bubble"):]
    painter = painter[: painter.index("def _follow_pending_history_if_needed")]

    # мигающий «▋» над мёртвой сборкой — то же враньё, что и «Сборка
    # продолжается»: интерфейс показывает работу, которой никто не делает
    assert "if running and not stalled:" in painter
    assert "typing=running and not stalled" in painter
    assert "typing=running)" not in painter
    assert "if (running and not stalled) else" in painter


@pytest.mark.asyncio
async def test_a_fresh_chat_never_borrows_another_sessions_running_job() -> None:
    """Пустой чат не имеет права показывать сборку, которую он не запускал.

    Замерено на установленной сборке: новый чат в свежном профиле открывался с
    «Сборка остановилась…» и «Продолжить», потому что без имени сессии UI делал
    `/api/workbook-research-active` без фильтра и получал самую свежую
    running-строку в базе — чужую и мёртвую.
    """

    calls: list[str] = []

    async def getter(path: str):
        calls.append(path)
        return {"jobs": [{"job_id": "wrj_foreign", "status": "running"}], "count": 1}

    assert await fetch_active_workbook_research(session_id="", getter=getter) is None
    assert (
        await fetch_active_workbook_research(
            session_id="", job_id="wrj_lost", getter=getter
        )
        is None
    )
    # потерянный job_id допустимо поискать по имени — но не подменять его чужой
    # сборкой из общего списка
    assert calls == ["/api/workbook-research/wrj_lost?view=progress"]
    assert (
        await fetch_active_workbook_research(
            session_id="session-mine", getter=getter
        )
    )["job_id"] == "wrj_foreign"
    assert calls[-1] == "/api/workbook-research-active?session_id=session-mine&view=progress"


def test_the_sqlite_fallback_also_refuses_to_guess_the_session() -> None:
    class _EveryJobIsMine:
        def list_open(self, *, session_id: str = "", limit: int = 20):
            return [{"job_id": "wrj_foreign", "status": "running"}]

        def get(self, job_id: str):  # pragma: no cover - не должно вызываться
            raise AssertionError("job_id не запрашивался")

    assert read_active_workbook_research(service=_EveryJobIsMine()) is None
    assert read_active_workbook_research(
        session_id="", service=_EveryJobIsMine()
    ) is None


@pytest.mark.asyncio
async def test_a_new_chat_does_not_take_back_the_build_it_just_dismissed(
    monkeypatch,
) -> None:
    """«Новый чат» отказывается и от жив ещё идущей сборки предыдущего чата.

    Мёртвую строку не отдаёт service (замер 812: `checkpoint_age_seconds` против
    `stalled_resume_seconds`). Живую — отдаёт: тот же fallback нужен ночной
    сборке, у которой NiceGUI пересоздал сессию. Значит отказ должен пережить
    очистку pending и запомниться под именем задачи, иначе через пару секунд
    пузырь возвращался в пустой новый чат.
    """

    from sovushka import state as sovushka_state

    live = {
        "job_id": "wrj_live",
        "status": "running",
        "identity": {"session_id": "session-old"},
    }
    other = {
        "job_id": "wrj_other",
        "status": "running",
        "identity": {"session_id": "session-nightly"},
    }

    async def getter(path: str):
        return {"jobs": [live], "count": 1}

    monkeypatch.setattr(sovushka_state, "dismissed_research_jobs", lambda: ["wrj_live"])
    assert (
        await fetch_active_workbook_research(session_id="session-new", getter=getter)
        is None
    )

    async def getter_other(path: str):
        return {"jobs": [other], "count": 1}

    # ночную сборку, от которой не уходили, fallback обязан возвращать
    assert (
        await fetch_active_workbook_research(
            session_id="session-new", getter=getter_other
        )
    )["job_id"] == "wrj_other"

    # а владелец потерянного чата получает свою задачу всегда
    async def getter_owner(path: str):
        return {"jobs": [live], "count": 1}

    assert (
        await fetch_active_workbook_research(
            session_id="session-old", getter=getter_owner
        )
    )["job_id"] == "wrj_live"


def test_the_new_chat_button_releases_the_previous_build_and_the_file(monkeypatch) -> None:
    """Список отказов живёт в `storage.user` и не растёт бесконечно."""

    from sovushka import state as sovushka_state

    storage = monkeypatch_storage(monkeypatch, sovushka_state)

    assert sovushka_state.dismiss_research_job("wrj_a") == ["wrj_a"]
    assert sovushka_state.dismiss_research_job("wrj_a") == ["wrj_a"]
    assert sovushka_state.dismissed_research_jobs() == ["wrj_a"]
    for index in range(30):
        sovushka_state.dismiss_research_job(f"wrj_{index}")
    kept = sovushka_state.dismissed_research_jobs()
    assert len(kept) == 20
    assert kept[-1] == "wrj_29"
    assert "wrj_a" not in kept
    assert storage["les_chat_dismissed_jobs"] == kept

    source = inspect.getsource(chat_page.build_chat)
    clear = source.split("def _clear_chat():", 1)[1].split("\n    _sending = ", 1)[0]
    # отказ фиксируется ДО `persist_chat_pending(None)`: после него имя задачи
    # в состоянии чата уже недоступно
    assert "dismiss_research_job(" in clear
    assert clear.index("dismiss_research_job(") < clear.index("persist_chat_pending(None)")


def monkeypatch_storage(monkeypatch, module) -> dict:
    storage: dict = {}
    monkeypatch.setattr(
        module,
        "app",
        SimpleNamespace(storage=SimpleNamespace(user=storage)),
        raising=False,
    )
    return storage


def test_the_follow_loop_reports_the_durable_file_state_not_a_promise() -> None:
    source = inspect.getsource(chat_page.build_chat)
    at = source.index('"Сборка на сервере завершилась')
    before = source[at - 760: at]

    # the sentence is kept only for a job the projection cannot call terminal;
    # a finished research without a file is routed to the repair plan instead
    assert "workbook_job_is_terminal(pending)" in before
    assert "format_terminal_assembly_notice(pending)" in before


def test_a_live_job_keeps_the_counting_bubble_and_the_dont_touch_hint() -> None:
    now_ts = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc).timestamp()
    pending = _stalled_pending()
    pending["updated_at"] = "2026-09-25 11:58:02"
    pending["accepted"] = 41
    pending["total"] = 318

    notice = chat_page.format_workbook_assembly_notice(pending, now_ts=now_ts)

    assert notice.startswith("Сборка продолжается")
    assert "41/318" in notice
    assert "Не нажимайте «Продолжить», пока задача идёт." in notice


def test_load_history_serves_a_finished_job_and_starts_no_follow_task() -> None:
    source = inspect.getsource(chat_page.build_chat)
    loader = source[source.index("async def _load_history()"):]
    loader = loader[: loader.index("async def _fetch_session_history_messages")]

    assert "workbook_job_is_terminal(job)" in loader
    assert "persist_chat_pending(None)" in loader
    assert "format_terminal_assembly_notice(job)" in loader
    branch = loader[loader.index("if job and workbook_job_is_terminal(job):"):]
    branch = branch[: branch.index("if job:\n            persist_chat_pending(")]
    # the finished document is bound AFTER the history render (rendering clears
    # the artifact panel), and no polling task is created for a terminal job
    assert branch.index("_render_chat_history(") < branch.index("_apply_terminal_job_plan")
    assert "asyncio.create_task" not in branch
    assert "return" in branch


def test_load_history_restores_last_finished_file_after_history_render() -> None:
    source = inspect.getsource(chat_page.build_chat)
    loader = source[source.index("async def _load_history():"):]
    loader = loader[: loader.index("async def _fetch_session_history_messages")]
    no_active_job = loader[loader.index("if job:\n            persist_chat_pending("):]

    assert no_active_job.index("_render_chat_history(") < no_active_job.index(
        "await _restore_last_finished_research()"
    )


def test_progress_polling_stops_as_soon_as_the_research_turns_terminal() -> None:
    source = inspect.getsource(chat_page.build_chat)
    poll = source[source.index("async def _poll_workbook_progress"):]
    poll = poll[: poll.index("first = await _fetch_session_history_messages")]

    assert "workbook_job_is_terminal" in poll
    assert poll.index("workbook_job_is_terminal") < poll.index("workbook_assembly_is_running")


def test_follow_task_bails_out_before_waiting_on_a_finished_job() -> None:
    source = inspect.getsource(chat_page.build_chat)
    follow = source[source.index("async def _follow_pending_history_if_needed"):]
    follow = follow[: follow.index("payload = await follow_detached_chat_history")]

    assert "workbook_job_is_terminal" in follow


def test_readiness_card_points_a_finished_job_at_its_file() -> None:
    """The card's document action downloads the revision; it never re-runs."""

    source = inspect.getsource(chat_page.build_chat)
    document_branch = source[source.index('elif kind == "document"'):]
    document_branch = document_branch[: document_branch.index("fields[\"refine\"]")]

    assert "_download_last_lsr_revision" in document_branch
    assert "_resume_lsr_packets" not in document_branch
    assert 'spec.get("document")' in document_branch


def test_last_revision_download_falls_back_to_the_saved_files() -> None:
    source = inspect.getsource(chat_page.build_chat)
    helper = source[source.index("async def _download_last_lsr_revision"):]
    helper = helper[: helper.index("def _rows_from_spreadsheet")]

    assert "artifact_workbook_files(artifact)" in helper
    # A finished job whose file vanished is repaired, not re-searched.
    assert "без повторного поиска норм" in helper
    assert "_download_file_artifact(url" in helper


def _basis_readiness(basis: dict, *, prices_complete: bool = False) -> dict:
    """Readiness payload shaped like ``build_lsr_result_readiness`` output."""

    return {
        "dimensions": {
            "file": {"ready": True},
            "coverage": {"complete": True},
            "norms": {"complete": True},
            "prices": {
                "complete": prices_complete,
                "gap_count": 0 if prices_complete else 2,
                "action": (
                    "Цены закрыты по выбранным ресурсам."
                    if prices_complete
                    else "Задайте цены."
                ),
                "basis": basis,
            },
        },
        "actions": [],
    }


def test_price_basis_prompt_keeps_a_resolved_basis_out_of_the_card():
    assert (
        chat_page.lsr_price_basis_prompt({"match": "exact"}, books=("sankt-peterburg_2kv2026",))[
            "visible"
        ]
        is False
    )
    assert (
        chat_page.lsr_price_basis_prompt(
            {"match": "confirmed_alternative", "actual_book": "sankt-peterburg_2kv2026"},
            books=("sankt-peterburg_2kv2026",),
        )["visible"]
        is False
    )
    assert chat_page.lsr_price_basis_prompt(None, books=())["visible"] is False


def test_price_basis_prompt_shows_a_continued_basis_with_its_source():
    """§ 7: a basis this turn never named is still an effective basis to show."""

    prompt = chat_page.lsr_price_basis_prompt(
        {
            "match": "exact",
            "actual_book": "sankt-peterburg_3kv2026",
            "actual_region": "Город Санкт-Петербург",
            "actual_quarter": "3 квартал 2026 г.",
            "inherited_from_document": "rev_c3ba0286",
        },
        books=("sankt-peterburg_2kv2026",),
    )
    assert prompt["visible"] is False
    assert "3 квартал 2026 г." in prompt["confirmed_line"]
    assert "sankt-peterburg_3kv2026" in prompt["confirmed_line"]
    assert "rev_c3ba0286" in prompt["confirmed_line"]
    assert "не выбрана молча" in prompt["confirmed_line"]
    # a basis the turn itself asked for keeps the card quiet, as before
    assert chat_page.lsr_price_basis_prompt(
        {"match": "exact", "actual_book": "sankt-peterburg_3kv2026"},
        books=("sankt-peterburg_3kv2026",),
    )["confirmed_line"] == ""


def test_price_basis_prompt_separates_requested_from_actually_used():
    """An unselected basis is named as the system's pick, never as a decision."""

    basis = {
        "requested": "",
        "requested_region": "",
        "requested_region_origin": "не указан",
        "contradictions": [],
        "actual_book": "sankt-peterburg_2kv2026",
        "actual_region": "Санкт-Петербург",
        "actual_quarter": "2 квартал 2026 г.",
        "match": "unspecified",
        "note": "Ценовая база в запросе и исходнике не указана.",
    }
    prompt = chat_page.lsr_price_basis_prompt(
        basis, books=("sankt-peterburg_2kv2026", "sankt-peterburg_3kv2026")
    )
    text = "\n".join(prompt["lines"])

    assert prompt["visible"] is True
    assert prompt["title"] == "Выберите регион и уровень цен"
    assert prompt["state_label"] == "Ценовая база не выбрана оператором"
    assert "Запрошенная ценовая база: не указана ни в запросе, ни в исходнике." in text
    # The exact identifier stays next to its Russian decoding.
    assert "sankt-peterburg_2kv2026" in text
    assert "Санкт-Петербург · II квартал 2026" in text
    assert "подбор системы по умолчанию, а не ваш выбор" in text
    assert "Смета остаётся черновиком" in text
    assert prompt["books"][0]["flag"] == "system_pick"
    assert "flag" not in prompt["books"][1]
    for phrase in ("подтверждена оператором", "по вашему выбору", "выбранный оператором"):
        assert phrase not in text
    assert prompt["technical"]["match"] == "unspecified"


def test_price_basis_prompt_names_an_absent_quarter_and_applies_nothing():
    """A missing period is stated as missing; no book is offered as a substitute."""

    basis = {
        "requested": "4kv2026",
        "requested_region": "",
        "requested_region_origin": "",
        "contradictions": [],
        "actual_book": "",
        "actual_region": "",
        "actual_quarter": "",
        "match": "no_book",
        "note": "Ценовая книга не применена.",
    }
    prompt = chat_page.lsr_price_basis_prompt(
        basis, books=("sankt-peterburg_2kv2026", "krasnodarskiy-kray_4kv2025")
    )
    text = "\n".join(prompt["lines"])

    assert prompt["state_label"] == "Ценовая книга не применена"
    assert "Ценовая книга не применена: в расчёте только подтверждённые цены и КАЦ." in text
    assert "Запрошенного периода «IV квартал 2026» среди доступных локальных книг нет." in text
    assert "Ни одна книга вместо него не применяется." in text
    # An absent book is never presented as applied.
    assert "Фактически" not in text
    assert all("flag" not in book for book in prompt["books"])
    assert prompt["available_title"] == "Доступные ценовые книги локально — выберите одну:"

    empty = chat_page.lsr_price_basis_prompt(basis, books=())
    assert empty["books"] == []
    assert "Локальных ценовых книг нет." in empty["empty_note"]


def test_price_basis_prompt_shows_city_and_zone_as_different_things():
    """Contradictions between region and period stay visible and get translated."""

    basis = {
        "requested": "Москва, 4 квартал 2026 г.",
        "requested_region": "Москва",
        "requested_region_origin": "параметр расчёта",
        "contradictions": ["регион: Москва, Санкт-Петербург", "период цен: 2:2026, 4:2026"],
        "actual_book": "sankt-peterburg_2kv2026",
        "actual_region": "Санкт-Петербург",
        "actual_quarter": "2 квартал 2026 г.",
        "match": "mismatch",
        "note": "Запрошена одна база, применена другая.",
    }
    prompt = chat_page.lsr_price_basis_prompt(basis, books=("sankt-peterburg_2kv2026",))
    text = "\n".join(prompt["lines"])

    assert prompt["state_label"] == "Ценовая база не совпадает с запросом"
    assert prompt["state_tone"] == "error"
    assert "Регион в запросе: Москва (параметр расчёта)." in text
    assert (
        "Город и ценовая зона — не одно и то же: противоречие показано, а не "
        "разрешено кодом." in text
    )
    assert "Явные источники называют разный регион: Москва, Санкт-Петербург." in text
    assert "не та, что запрошена" in text
    assert "применена вместо запрошенной" in prompt["books"][0]["flag_note"]
    # Machine tokens are translated at the UI boundary.
    assert "II квартал 2026, IV квартал 2026" in text
    assert "2:2026" not in text


def test_price_basis_card_shows_a_refused_choice_as_a_refusal():
    """Live 823 evidence, cell ``B3_bap_pdf`` — the card and the note agree.

    The task names Москва III/2026 while the object address inside the PDF names
    Санкт-Петербург. The derivation refuses to pick a side, which is correct; the
    card built from that same payload must then say *why* nothing was applied.
    It may not claim the region was never named, and it may not claim a base is
    absent while ``moskva_3kv2026`` sits in the list it is showing (ADR-16 § 7,
    § 10).
    """

    from proxy.services.lsr_workbook_adapter_service import (
        explicit_estimate_pricebook,
        summarize_lsr_price_basis,
    )

    catalog = ["sankt-peterburg_2kv2026", "sankt-peterburg_3kv2026", "moskva_3kv2026"]
    task = "Собери ЛСР по Москве, цены III квартала 2026"
    source = (
        "Ведомость объёмов работ\n"
        "Объект: г. Санкт-Петербург, Выборгский район, ул. Парадная, д. 1"
    )
    choice = explicit_estimate_pricebook(
        question_text=task, source_text=source, source_name="bap.pdf",
        pricebooks=catalog,
    )
    basis = summarize_lsr_price_basis(
        question_text=task,
        pricebook=None,
        requested_region=choice["requested_region"],
        available_books=choice["available_books"],
        basis_binding=choice["basis_binding"],
        basis_refusal=choice["refusal"],
        basis_candidates=choice["matching_books"],
        basis_contradictions=(
            ["регион: " + ", ".join(choice["contradicting_regions"])]
            if choice["contradicting_regions"]
            else []
        ),
    )
    prompt = chat_page.lsr_price_basis_prompt(basis, books=catalog)
    text = "\n".join(prompt["lines"])

    assert prompt["visible"] is True
    assert prompt["state_label"] == "Ценовая книга не применена"
    assert "Явные источники называют разный регион: Москва, Санкт-Петербург." in text
    assert "Регион в запросе не назван" not in text
    assert "среди доступных локальных книг нет" not in text
    assert "не найдена" not in prompt["technical"]["note"]
    assert {book["identifier"] for book in prompt["books"]} == set(catalog)


def test_price_basis_choice_is_an_ordinary_chat_formulation():
    book = chat_page.describe_pricebook_identifier("sankt-peterburg_3kv2026")

    assert book["identifier"] == "sankt-peterburg_3kv2026"
    assert book["region"] == "Санкт-Петербург"
    assert book["period"] == "III квартал 2026"
    assert book["label"] == "Санкт-Петербург · III квартал 2026"

    sentence = chat_page.pricebook_chat_formulation(book)
    assert "Пересчитай ЛСР: регион Санкт-Петербург, III квартал 2026" in sentence
    assert "sankt-peterburg_3kv2026" in sentence
    assert "Регион и уровень цен подтверждаю явно." in sentence

    unknown = chat_page.describe_pricebook_identifier("some-region_1kv2024")
    assert unknown["region_proven"] is False
    assert unknown["region_note"] == "регион по идентификатору не подтверждён"
    assert "Пересчитай ЛСР по ценовой книге some-region_1kv2024 (I квартал 2024)" in (
        chat_page.pricebook_chat_formulation(unknown)
    )


def test_readiness_spec_keeps_the_price_basis_apart_from_price_gaps():
    """No price gaps does not mean the operator picked a region and a period."""

    basis = {
        "requested": "",
        "requested_region": "",
        "requested_region_origin": "",
        "contradictions": [],
        "actual_book": "sankt-peterburg_2kv2026",
        "actual_region": "Санкт-Петербург",
        "actual_quarter": "2 квартал 2026 г.",
        "match": "unspecified",
        "note": "Применено значение по умолчанию.",
    }
    spec = chat_page.lsr_readiness_card_spec(_basis_readiness(basis, prices_complete=True))

    assert spec["price_basis"] == basis
    assert spec["prices_label"] == "Цены полные"
    prompt = chat_page.lsr_price_basis_prompt(
        spec["price_basis"], books=("sankt-peterburg_2kv2026",)
    )
    assert prompt["visible"] is True
    assert "Смета остаётся черновиком" in "\n".join(prompt["lines"])


def test_pricebook_identifiers_comes_from_the_local_price_service(monkeypatch) -> None:
    """The offered list is the resolver's own visible set, reduced to identifiers."""

    from proxy.services import fgis_price_service

    monkeypatch.setattr(chat_page, "_pricebook_list_cache", (0.0, ()))
    monkeypatch.setattr(
        fgis_price_service,
        "available_pricebooks",
        lambda *args, **kwargs: [
            "data/price_base/sankt-peterburg_3kv2026.parquet",
            "data/price_base/sankt-peterburg_2kv2026.parquet",
            "data/price_base/sankt-peterburg_2kv2026.parquet",
        ],
    )

    assert chat_page.pricebook_identifiers(refresh=True) == (
        "sankt-peterburg_2kv2026",
        "sankt-peterburg_3kv2026",
    )


def test_chat_page_surfaces_the_price_basis_choice_in_the_readiness_card() -> None:
    source = inspect.getsource(chat_page.build_chat)
    block = source[
        source.index("def _render_price_basis_prompt"):
        source.index("def _render_lsr_readiness_card")
    ]
    card = source[source.index("def _render_lsr_readiness_card"):]
    card = card[: card.index("def _render_smeta_approval_card")]

    # Only shared primitives and existing token classes are used here.
    assert "section_heading(" in block
    assert "status_badge(" in block
    assert "action_button(" in block
    assert "render_feedback_state(" in block
    assert 'classes("sov-ui-section-detail")' in block
    assert "sov-ui-source-chip" in block
    assert "sov-lsr-field-help" in block
    assert "w-full gap-1" in block
    assert "Технические детали ценовой базы" in block
    assert "PRICE_BASIS_CHOICE_LABEL" in block
    # The choice goes through the composer, not a bespoke endpoint.
    assert "_prefill_chat_prompt(t)" in block
    assert "api_post" not in block
    assert "api_get" not in block
    prefill = source[
        source.index("def _prefill_chat_prompt"):source.index("def _render_price_basis_prompt")
    ]
    assert 'chat_input.value = str(text or "")' in prefill
    assert "chat_input.update()" in prefill

    assert "lsr_price_basis_prompt(" in card
    assert 'spec.get("price_basis")' in card
    assert "pricebook_identifiers()" in card
    assert "_render_price_basis_prompt(basis_prompt)" in card
    assert 'if basis_prompt["visible"]:' in card
    assert "PRICE_BASIS_CITY_VS_ZONE_NOTE" in card
