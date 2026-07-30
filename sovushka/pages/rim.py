"""Conversational RIM estimate workspace."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from uuid import uuid4

from nicegui import app, ui

from sovushka.state import (
    api_get,
    api_get_bytes,
    api_post,
    api_post_file_form,
    last_api_error_text,
)
from sovushka.uikit.components import (
    action_button,
    panel,
    render_feedback_state,
    section_heading,
    select_field,
    status_badge,
    text_field,
)


_SESSION_KEY = "les_rim_session_id"
_STATUS_LABELS = {
    "new": "Новая",
    "file_received": "Файл получен",
    "awaiting_vor_approval": "Проверка ВОР",
    "norm_mapping": "Подбор норм",
    "awaiting_mapping_decisions": "Решения по нормам",
    "mapping_globally_reviewed": "Global review",
    "mapping_locked": "Mapping заблокирован",
    "combinations_ready": "Сценарии готовы",
    "priced_partial": "Стоимость частичная",
    "priced_draft": "Черновик ЛСР",
    "awaiting_final_lock": "Финальная проверка",
    "priced_final": "Финальная ЛСР",
}


def _human_source_ref(value: object) -> str:
    """Render a compact source locator while preserving raw provenance in storage."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    path, separator, locator = raw.partition("#")
    filename = Path(path).name
    if re.fullmatch(r"[0-9a-fA-F]{32,}\.[A-Za-z0-9]+", filename):
        filename = ""
    fields: dict[str, str] = {}
    if separator:
        for item in locator.split(";"):
            key, equals, field_value = item.partition("=")
            if equals and key and field_value:
                fields[key.strip().casefold()] = field_value.strip()
    parts = []
    if filename:
        parts.append(filename)
    if fields.get("sheet"):
        parts.append(f"лист «{fields['sheet']}»")
    if fields.get("row"):
        parts.append(f"строка {fields['row']}")
    elif fields.get("page"):
        parts.append(f"страница {fields['page']}")
    if parts:
        return " · ".join(parts)
    return filename or raw


def _human_norm_source(row: dict[str, object]) -> str:
    """Prefer the normative edition and code over an internal store locator."""
    edition = str(row.get("normative_base_version") or "").strip()
    code = str(row.get("norm_code") or "").strip()
    if edition and code:
        return f"{edition} · {code}"
    if code and str(row.get("norm_source_ref") or "").strip():
        return f"Структурированная ФСНБ · {code}"
    return _human_source_ref(row.get("norm_source_ref"))


def _progress_codes_display(row: dict[str, object], key: str, count_key: str) -> str:
    cards = [
        card
        for card in (row.get(key) or [])
        if isinstance(card, dict) and str(card.get("norm_code") or "")
    ]
    codes = [str(card["norm_code"]) for card in cards[:2]]
    if int(row.get(count_key) or 0) > len(codes):
        codes.append("…")
    count = int(row.get(count_key) or 0)
    return (f"{count} · " + ", ".join(codes)).rstrip(" ·")


def _progress_result_display(row: dict[str, object]) -> str:
    decision = row.get("decision")
    detail = str(next(iter(row.get("blockers") or []), ""))
    if not detail and isinstance(decision, dict):
        detail = str(decision.get("reason") or "")
    if len(detail) > 160:
        detail = detail[:157].rstrip() + "…"
    return " · ".join(
        value
        for value in [str(row.get("stage_label") or ""), detail]
        if value
    )


def _status_tone(status: str) -> str:
    if status == "priced_final":
        return "ok"
    if status in {"priced_partial", "awaiting_mapping_decisions", "awaiting_vor_approval"}:
        return "warn"
    if "blocked" in status:
        return "blocked"
    return "muted"


async def _upload_content(event) -> tuple[bytes, str]:
    upload = getattr(event, "file", None)
    if upload is not None and hasattr(upload, "read"):
        content = await upload.read()
        filename = getattr(upload, "name", "") or getattr(event, "name", "")
    else:
        raw = getattr(event, "content", None)
        if raw is None or not hasattr(raw, "read"):
            raise ValueError("Не удалось прочитать выбранный файл")
        value = raw.read()
        content = await value if inspect.isawaitable(value) else value
        filename = getattr(event, "name", "")
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not content:
        raise ValueError("Файл пуст")
    return content, (filename or "source.xlsx")


def build_rim() -> None:
    """Build the RIM workbench inside the lazy application panel."""
    current: dict[str, object] = {
        "session": None,
        "vor": [],
        "mapping": [],
        "mapping_progress": [],
        "mapping_progress_refreshing": False,
        "requirements": [],
    }

    with ui.column().classes("w-full sov-rim-page"):
        with panel(variant="raised", classes="sov-rim-hero"):
            with ui.row().classes("sov-rim-hero__head"):
                section_heading(
                    "РИМ-смета",
                    "Qwen предлагает и спрашивает. Код проверяет, считает и сохраняет трассу. "
                    "Сметчик блокирует решения.",
                )
                with ui.row().classes("sov-rim-hero__actions"):
                    refresh_button = action_button(
                        "Обновить",
                        icon="o_refresh",
                        compact=True,
                        variant="secondary",
                    )
                    new_button = action_button(
                        "Новая сессия",
                        icon="o_add",
                        compact=True,
                        variant="primary",
                    )
            session_select = select_field(
                {},
                label="Сохранённая сессия",
                aria_label="Открыть сохранённую РИМ-сессию",
                classes="sov-rim-session-select",
            )
            with ui.row().classes("sov-rim-status-strip"):
                state_badges = ui.row().classes("sov-rim-status-strip__badges")
                session_meta = ui.label("Сессия ещё не создана").classes(
                    "sov-rim-status-strip__meta"
                )

        with panel(variant="plain", classes="sov-rim-intake"):
            section_heading(
                "Исходные условия",
                "Файл сохраняется без изменений; параметры входят в аудит каждой ревизии.",
            )
            with ui.element("section").classes("sov-rim-intake__fields"):
                project_field = text_field(
                    label="Проект",
                    placeholder="Код или название проекта",
                    classes="sov-rim-field",
                )
                region_field = text_field(
                    label="Регион",
                    placeholder="77",
                    classes="sov-rim-field",
                )
                period_field = text_field(
                    label="Период цен",
                    placeholder="2026-Q2",
                    classes="sov-rim-field",
                )
                pricebook_field = text_field(
                    label="Ценовая книга",
                    placeholder="Не выбрана",
                    classes="sov-rim-field",
                )
                source_kind = select_field(
                    {
                        "auto": "Определить",
                        "vor": "Утверждённая ВОР",
                        "specification": "Спецификация",
                    },
                    value="auto",
                    label="Тип файла",
                    classes="sov-rim-field",
                )
            upload_status = ui.label(
                "Создайте сессию и загрузите XLSX или CSV."
            ).classes("sov-rim-intake__status")

            async def upload_source(event) -> None:
                session = current.get("session")
                if not isinstance(session, dict):
                    ui.notify("Сначала создайте сессию", type="warning")
                    return
                try:
                    content, filename = await _upload_content(event)
                except ValueError as error:
                    ui.notify(str(error), type="negative")
                    return
                upload_status.set_text(f"Импортирую «{filename}»…")
                response = await api_post_file_form(
                    f"/api/rim/sessions/{session['session_id']}/vor/import",
                    content,
                    filename,
                    data={
                        "source_kind": source_kind.value,
                        "expected_parent_revision_id": session["head_revision_id"],
                    },
                )
                if not isinstance(response, dict):
                    upload_status.set_text(last_api_error_text("Импорт не выполнен"))
                    ui.notify(last_api_error_text("Импорт не выполнен"), type="negative")
                    return
                upload_status.set_text(f"Файл «{filename}» сохранён новой ревизией.")
                ui.notify("Исходный файл импортирован", type="positive")
                await refresh()

            ui.upload(
                auto_upload=True,
                on_upload=upload_source,
                label="Загрузить ВОР или спецификацию",
            ).props("flat accept=.xlsx,.xlsm,.csv").classes("w-full sov-rim-upload")

        with panel(variant="raised", classes="sov-rim-dialog"):
            with ui.row().classes("sov-rim-dialog__head"):
                section_heading(
                    "Диалог по текущему решению",
                    "Один вопрос за ход; короткий ответ остаётся связан с открытым вопросом.",
                )
                dialog_state = status_badge("Ожидание", "muted")
            question_box = ui.column().classes("sov-rim-question")
            dialog_log = ui.column().classes("sov-rim-dialog__log")
            with ui.row().classes("sov-rim-composer"):
                message_field = text_field(
                    label="Сообщение сметчику",
                    placeholder="Например: кабель прокладывается в лотке",
                    classes="sov-rim-composer__field",
                )
                send_button = action_button(
                    "Отправить",
                    icon="o_arrow_upward",
                    variant="primary",
                )

        with panel(variant="plain", classes="sov-rim-workspace"):
            section_heading(
                "Рабочая область",
                "Показываются источники, причины, статусы, ревизии и блокировки.",
            )
            with ui.tabs().props("dense no-caps").classes("sov-rim-tabs") as tabs:
                tab_vor = ui.tab("ВОР", icon="o_format_list_numbered")
                tab_mapping = ui.tab("Кандидаты ГЭСН", icon="o_account_tree")
                tab_review = ui.tab("Проверка", icon="o_rule")
                tab_requirements = ui.tab("Недостающие данные", icon="o_report_problem")
                tab_lsr = ui.tab("Черновики ЛСР", icon="o_table_view")
                tab_final = ui.tab("Финализация", icon="o_lock")

            with ui.tab_panels(tabs, value=tab_vor, animated=True).classes(
                "sov-rim-tab-panels"
            ):
                with ui.tab_panel(tab_vor):
                    vor_summary = ui.label("ВОР ещё не создана.").classes(
                        "sov-rim-panel-summary"
                    )
                    vor_table = ui.table(
                        columns=[
                            {"name": "order_no", "label": "№", "field": "order_no"},
                            {"name": "section_name", "label": "Раздел", "field": "section_name"},
                            {"name": "work_name", "label": "Работа", "field": "work_name"},
                            {"name": "unit", "label": "Ед.", "field": "unit"},
                            {"name": "quantity", "label": "Количество", "field": "quantity"},
                            {
                                "name": "source_display",
                                "label": "Источник",
                                "field": "source_display",
                            },
                            {"name": "status", "label": "Статус", "field": "status"},
                        ],
                        rows=[],
                        row_key="work_id",
                        pagination=25,
                    ).props('dense wrap-cells flat aria-label="Черновик ВОР"').classes(
                        "sov-rim-table"
                    )

                with ui.tab_panel(tab_mapping):
                    mapping_summary = ui.label("Кандидаты ещё не подобраны.").classes(
                        "sov-rim-panel-summary"
                    )
                    mapping_progress_summary = ui.label(
                        "Живой прогресс Qwen появится после первого шага поиска."
                    ).classes("sov-rim-panel-summary")
                    mapping_progress_table = ui.table(
                        columns=[
                            {"name": "work_name", "label": "Строка ВОР", "field": "work_name"},
                            {"name": "source_display", "label": "Источник", "field": "source_display"},
                            {"name": "scope_display", "label": "Каталог", "field": "scope_display"},
                            {"name": "candidate_display", "label": "Кандидаты", "field": "candidate_display"},
                            {"name": "opened_display", "label": "Карточки", "field": "opened_display"},
                            {"name": "result_display", "label": "Текущий результат", "field": "result_display"},
                        ],
                        rows=[],
                        row_key="work_id",
                        pagination=10,
                    ).props(
                        'dense wrap-cells flat aria-label="Живой прогресс подбора норм Qwen"'
                    ).classes("sov-rim-table")
                    mapping_table = ui.table(
                        columns=[
                            {"name": "work_id", "label": "ВОР", "field": "work_id"},
                            {"name": "norm_code", "label": "Шифр", "field": "norm_code"},
                            {"name": "norm_title", "label": "Норма", "field": "norm_title"},
                            {"name": "norm_unit", "label": "Измеритель", "field": "norm_unit"},
                            {"name": "selection_status", "label": "Решение", "field": "selection_status"},
                            {"name": "reason", "label": "Причина", "field": "reason"},
                            {
                                "name": "norm_source_display",
                                "label": "Источник нормы",
                                "field": "norm_source_display",
                            },
                        ],
                        rows=[],
                        row_key="mapping_row_id",
                        pagination=25,
                        selection="single",
                    ).props(
                        'dense wrap-cells flat aria-label="Соответствия ВОР и ГЭСН"'
                    ).classes("sov-rim-table")
                    with ui.element("section").classes("sov-rim-mapping-edit"):
                        mapping_status_field = select_field(
                            {
                                "candidate": "Кандидат",
                                "selected": "Выбрано",
                                "accepted": "Принято",
                                "rejected": "Отклонено",
                                "conflict": "Спорно",
                            },
                            value="accepted",
                            label="Новое решение",
                            classes="sov-rim-field",
                        )
                        mapping_reason_field = text_field(
                            label="Основание решения",
                            classes="sov-rim-field",
                        )
                        save_mapping_button = action_button(
                            "Сохранить правку",
                            icon="o_save",
                            variant="primary",
                        )
                    with ui.row().classes("sov-rim-actions"):
                        export_mapping_button = action_button(
                            "Выгрузить XLSX",
                            icon="o_download",
                            compact=True,
                            variant="secondary",
                        )
                        mapping_upload_status = ui.label("").classes(
                            "sov-rim-panel-summary"
                        )

                    async def upload_mapping(event) -> None:
                        session = current.get("session")
                        if not isinstance(session, dict):
                            return
                        try:
                            content, filename = await _upload_content(event)
                        except ValueError as error:
                            ui.notify(str(error), type="negative")
                            return
                        response = await api_post_file_form(
                            f"/api/rim/sessions/{session['session_id']}/mapping/import",
                            content,
                            filename,
                            data={
                                "expected_parent_revision_id": session["head_revision_id"]
                            },
                        )
                        if not isinstance(response, dict):
                            ui.notify(last_api_error_text("Mapping XLSX не импортирован"), type="negative")
                            return
                        mapping_upload_status.set_text("XLSX принят новой immutable-ревизией.")
                        await refresh()

                    ui.upload(
                        auto_upload=True,
                        on_upload=upload_mapping,
                        label="Импортировать исправленный mapping XLSX",
                    ).props("flat accept=.xlsx").classes("w-full sov-rim-upload")

                with ui.tab_panel(tab_review):
                    review_summary = ui.label(
                        "Global review флагирует конфликты, но не исправляет решения."
                    ).classes("sov-rim-panel-summary")
                    review_issues = ui.column().classes("sov-rim-issue-list")
                    with ui.row().classes("sov-rim-actions"):
                        review_button = action_button(
                            "Запустить global review",
                            icon="o_fact_check",
                            variant="secondary",
                        )
                        lock_note = text_field(
                            label="Комментарий сметчика к mapping lock",
                            classes="sov-rim-lock-note",
                        )
                        lock_button = action_button(
                            "Заблокировать mapping",
                            icon="o_lock",
                            variant="primary",
                        )

                with ui.tab_panel(tab_requirements):
                    requirement_summary = ui.label(
                        "Блокирующие пробелы появятся после расчёта."
                    ).classes("sov-rim-panel-summary")
                    requirement_table = ui.table(
                        columns=[
                            {"name": "kind", "label": "Тип", "field": "kind"},
                            {"name": "work_id", "label": "ВОР", "field": "work_id"},
                            {"name": "resource_code", "label": "Ресурс", "field": "resource_code"},
                            {"name": "description", "label": "Что требуется", "field": "description"},
                            {"name": "status", "label": "Статус", "field": "status"},
                            {"name": "finality_policy", "label": "Влияние", "field": "finality_policy"},
                        ],
                        rows=[],
                        row_key="requirement_id",
                        pagination=25,
                    ).props('dense wrap-cells flat aria-label="Недостающие данные"').classes(
                        "sov-rim-table"
                    )

                with ui.tab_panel(tab_lsr):
                    lsr_summary = ui.label(
                        "Сценарий и расчёт доступны после mapping lock."
                    ).classes("sov-rim-panel-summary")
                    scenario_reason = text_field(
                        label="Почему выбранные нормы совместимы в одном сценарии",
                        classes="sov-rim-scenario-reason",
                    )
                    with ui.row().classes("sov-rim-actions"):
                        scenario_button = action_button(
                            "Создать сценарий",
                            icon="o_schema",
                            variant="secondary",
                        )
                        calculate_button = action_button(
                            "Рассчитать черновик",
                            icon="o_calculate",
                            variant="primary",
                        )
                        draft_export_button = action_button(
                            "Скачать черновик XLSX",
                            icon="o_download",
                            variant="quiet",
                        )

                with ui.tab_panel(tab_final):
                    final_summary = ui.label(
                        "Финальный lock доступен только без открытых блокирующих requirements."
                    ).classes("sov-rim-panel-summary")
                    final_note = text_field(
                        label="Комментарий к финальной проверке",
                        classes="sov-rim-lock-note",
                    )
                    with ui.row().classes("sov-rim-actions"):
                        finalize_button = action_button(
                            "Финальная блокировка",
                            icon="o_verified_user",
                            variant="primary",
                        )
                        final_export_button = action_button(
                            "Скачать финальный XLSX",
                            icon="o_download",
                            variant="secondary",
                        )

        async def create_session() -> None:
            response = await api_post(
                "/api/rim/sessions",
                {
                    "project_id": str(project_field.value or "").strip(),
                    "region_code": str(region_field.value or "").strip(),
                    "price_period": str(period_field.value or "").strip(),
                    "pricebook_id": str(pricebook_field.value or "").strip(),
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Сессия не создана"), type="negative")
                return
            app.storage.user[_SESSION_KEY] = response["session_id"]
            ui.notify("Новая РИМ-сессия создана", type="positive")
            await refresh()

        async def send_message() -> None:
            session = current.get("session")
            if not isinstance(session, dict):
                ui.notify("Сначала создайте сессию", type="warning")
                return
            text = str(message_field.value or "").strip()
            send_button.disable()
            dialog_state.set_text("Qwen работает")
            with dialog_log:
                ui.label(text or "Продолжить текущий шаг").classes(
                    "sov-rim-dialog__message sov-rim-dialog__message--user"
                )
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/agent/turn",
                {"message": text},
            )
            send_button.enable()
            if not isinstance(response, dict):
                dialog_state.set_text("Ошибка")
                ui.notify(last_api_error_text("Ход Qwen не выполнен"), type="negative")
                return
            with dialog_log:
                ui.label(str(response.get("message") or "Шаг завершён.")).classes(
                    "sov-rim-dialog__message sov-rim-dialog__message--assistant"
                )
            message_field.value = ""
            dialog_state.set_text("Шаг завершён")
            await refresh()

        async def save_mapping_edit() -> None:
            session = current.get("session")
            rows = list(current.get("mapping") or [])
            selected = list(mapping_table.selected or [])
            if not isinstance(session, dict) or len(selected) != 1:
                ui.notify("Выберите одну строку mapping", type="warning")
                return
            row_id = str(selected[0].get("mapping_row_id") or "")
            for row in rows:
                if str(row.get("mapping_row_id") or "") == row_id:
                    row["selection_status"] = mapping_status_field.value
                    row["reason"] = str(mapping_reason_field.value or "").strip()
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/mapping/candidates",
                {
                    "mapping_rows": rows,
                    "created_by": "user",
                    "change_note": "Правка в UI",
                    "expected_parent_revision_id": session["head_revision_id"],
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Правка не сохранена"), type="negative")
                return
            ui.notify("Создана новая mapping-ревизия", type="positive")
            await refresh()

        async def run_review() -> None:
            session = current.get("session")
            if not isinstance(session, dict):
                return
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/mapping/global-review",
                {
                    "mapping_rows": list(current.get("mapping") or []),
                    "created_by": "user",
                    "expected_parent_revision_id": session["head_revision_id"],
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Global review не выполнен"), type="negative")
                return
            await refresh()
            tabs.set_value(tab_review)

        async def lock_mapping() -> None:
            session = current.get("session")
            if not isinstance(session, dict):
                return
            conflicts = list((await api_get(
                f"/api/rim/sessions/{session['session_id']}/mapping"
            ) or {}).get("professional_conflicts") or [])
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/mapping/lock",
                {
                    "review_note": str(lock_note.value or "").strip(),
                    "accepted_conflict_ids": [
                        str(item.get("conflict_id") or "")
                        for item in conflicts
                        if str(item.get("severity") or "") != "blocking"
                    ],
                    "expected_parent_revision_id": session["head_revision_id"],
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Mapping lock не создан"), type="negative")
                return
            await refresh()

        async def create_scenario() -> None:
            session = current.get("session")
            if not isinstance(session, dict):
                return
            selections = [
                {"mapping_row_id": row["mapping_row_id"]}
                for row in (current.get("mapping") or [])
                if row.get("selection_status") in {"selected", "accepted"}
                and row.get("selection_kind") not in {"covered_by", "unbound"}
            ]
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/combinations/generate",
                {
                    "expected_parent_revision_id": session["head_revision_id"],
                    "created_by": "user",
                    "scenarios": [
                        {
                            "scenario_id": uuid4().hex,
                            "title": "Основной",
                            "authored_by": "user",
                            "compatibility_reason": str(scenario_reason.value or "").strip(),
                            "selections": selections,
                        }
                    ],
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Сценарий не создан"), type="negative")
                return
            app.storage.user["les_rim_scenario_id"] = (
                response.get("session", {}).get("current_scenario_revision_id") or ""
            )
            await refresh()

        async def calculate() -> None:
            session = current.get("session")
            if not isinstance(session, dict):
                return
            scenario_set = await api_get(
                f"/api/rim/sessions/{session['session_id']}/combinations"
            )
            scenarios = list((scenario_set or {}).get("scenarios") or [])
            if not scenarios:
                ui.notify("Сначала создайте сценарий", type="warning")
                return
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/combinations/calculate",
                {
                    "scenario_id": scenarios[0]["scenario_id"],
                    "expected_parent_revision_id": session["head_revision_id"],
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Расчёт не выполнен"), type="negative")
                return
            await refresh()

        async def download(path: str, fallback: str) -> None:
            blob = await api_get_bytes(path)
            if blob is None:
                ui.notify(last_api_error_text("XLSX недоступен"), type="negative")
                return
            ui.download(blob[0], blob[1] or fallback)

        async def finalize() -> None:
            session = current.get("session")
            if not isinstance(session, dict):
                return
            response = await api_post(
                f"/api/rim/sessions/{session['session_id']}/finalize",
                {
                    "review_note": str(final_note.value or "").strip(),
                    "expected_parent_revision_id": session["head_revision_id"],
                },
            )
            if not isinstance(response, dict):
                ui.notify(last_api_error_text("Финализация заблокирована"), type="negative")
                return
            await refresh()

        async def refresh_mapping_progress(session_id: str = "") -> None:
            if bool(current.get("mapping_progress_refreshing")):
                return
            active_session = current.get("session")
            resolved_session_id = session_id or (
                str(active_session.get("session_id") or "")
                if isinstance(active_session, dict)
                else ""
            )
            if not resolved_session_id:
                return
            current["mapping_progress_refreshing"] = True
            try:
                progress = (
                    await api_get(
                        f"/api/rim/sessions/{resolved_session_id}/mapping/progress"
                    )
                    or {}
                )
                latest_session = current.get("session")
                if not isinstance(latest_session, dict) or str(
                    latest_session.get("session_id") or ""
                ) != resolved_session_id:
                    return
                current["mapping_progress"] = [
                    {
                        **row,
                        "scope_display": ", ".join(
                            "/".join(
                                [
                                    *[
                                        str(value)
                                        for value in (scope.get("base_types") or [])
                                    ],
                                    *[
                                        str(value)
                                        for value in (scope.get("collections") or [])
                                    ],
                                ]
                            )
                            for scope in (row.get("scopes") or [])
                            if isinstance(scope, dict)
                        ),
                        "candidate_display": _progress_codes_display(
                            row, "candidates", "candidate_count"
                        ),
                        "opened_display": _progress_codes_display(
                            row, "opened_cards", "opened_count"
                        ),
                        "result_display": _progress_result_display(row),
                    }
                    for row in (progress.get("rows") or [])
                ]
                mapping_progress_table.rows = current["mapping_progress"]
                mapping_progress_table.update()
                progress_summary = dict(progress.get("summary") or {})
                if progress.get("active"):
                    mapping_progress_summary.set_text(
                        "Сохранено по строкам: "
                        f"{int(progress_summary.get('completed_rows') or 0)}/"
                        f"{int(progress_summary.get('total_rows') or 0)} · "
                        f"осталось: {int(progress_summary.get('remaining_rows') or 0)} · "
                        f"checkpoint {str(progress.get('checkpoint_updated_at') or '')}"
                    )
                else:
                    mapping_progress_summary.set_text(
                        "Активного checkpoint нет: показан финальный immutable mapping ниже."
                    )
            finally:
                current["mapping_progress_refreshing"] = False

        async def refresh() -> None:
            sessions_payload = await api_get("/api/rim/sessions?limit=100")
            sessions = (
                list(sessions_payload.get("sessions") or [])
                if isinstance(sessions_payload, dict)
                else []
            )
            session_options = {
                str(item.get("session_id") or ""): (
                    f"{item.get('project_id') or 'Без проекта'} · "
                    f"{_STATUS_LABELS.get(str(item.get('display_state') or ''), item.get('display_state') or 'новая')} · "
                    f"{str(item.get('session_id') or '')[:8]}"
                )
                for item in sessions
                if str(item.get("session_id") or "")
            }
            session_select.options = session_options
            session_select.update()
            session_id = str(app.storage.user.get(_SESSION_KEY) or "").strip()
            if session_id not in session_options:
                session_id = ""
            if session_options and not session_id:
                session_id = next(iter(session_options))
                app.storage.user[_SESSION_KEY] = session_id
            session_select.value = session_id or None
            session_select.update()
            if not session_id:
                state_badges.clear()
                with state_badges:
                    status_badge("Новая", "muted")
                return
            session = await api_get(f"/api/rim/sessions/{session_id}")
            if not isinstance(session, dict):
                app.storage.user[_SESSION_KEY] = ""
                render_feedback_state("error", detail=last_api_error_text("Сессия недоступна"))
                return
            current["session"] = session
            project_field.value = session.get("project_id") or ""
            region_field.value = session.get("region_code") or ""
            period_field.value = session.get("price_period") or ""
            pricebook_field.value = session.get("pricebook_id") or ""
            state_badges.clear()
            with state_badges:
                status = str(session.get("display_state") or "new")
                status_badge(_STATUS_LABELS.get(status, status), _status_tone(status))
                if session.get("mapping_status") == "mapping_locked":
                    status_badge("Mapping lock", "ok")
                if int(session.get("open_requirement_count") or 0):
                    status_badge(
                        f"Пробелов: {session['open_requirement_count']}", "blocked"
                    )
            session_meta.set_text(
                f"{session_id[:8]} · ревизия {str(session.get('head_revision_id') or '')[:8]} · "
                f"{session.get('region_code') or 'регион не задан'} · "
                f"{session.get('price_period') or 'период не задан'}"
            )
            question_box.clear()
            question = session.get("pending_question")
            if isinstance(question, dict):
                with question_box:
                    ui.label(str(question.get("text") or "")).classes(
                        "sov-rim-question__title"
                    )
                    ui.label(str(question.get("reason") or "")).classes(
                        "sov-rim-question__reason"
                    )
                    options = list(question.get("options") or [])
                    if options:
                        ui.label("Выберите вариант или напишите свой ответ:").classes(
                            "sov-rim-question__options"
                        )
                        with ui.row().classes("sov-rim-question__choices"):
                            for option in options:
                                value = str(option)

                                async def answer_option(
                                    selected: str = value,
                                ) -> None:
                                    message_field.value = selected
                                    await send_message()

                                action_button(
                                    value,
                                    compact=True,
                                    variant="secondary",
                                ).on_click(answer_option)
                dialog_state.set_text("Нужен ответ")
            else:
                with question_box:
                    ui.label("Открытого вопроса нет.").classes(
                        "sov-rim-question__reason"
                    )
                dialog_state.set_text("Готово")

            vor = await api_get(f"/api/rim/sessions/{session_id}/vor") or {}
            mapping = await api_get(f"/api/rim/sessions/{session_id}/mapping") or {}
            current["vor"] = [
                {
                    **row,
                    "source_display": _human_source_ref(row.get("source_ref")),
                }
                for row in (vor.get("rows") or [])
            ]
            current["mapping"] = [
                {
                    **row,
                    "norm_source_display": _human_norm_source(row),
                }
                for row in (mapping.get("mapping_rows") or [])
            ]
            current["requirements"] = list(session.get("requirements") or [])
            vor_table.rows = current["vor"]
            vor_table.update()
            vor_summary.set_text(
                f"Строк: {len(current['vor'])} · ошибок: "
                f"{sum(item.get('severity') == 'blocking' for item in (vor.get('issues') or []))}"
            )
            mapping_table.rows = current["mapping"]
            mapping_table.selected = []
            mapping_table.update()
            mapping_summary.set_text(
                f"Кандидатов: {len(current['mapping'])} · выбрано: "
                f"{sum(row.get('selection_status') in {'selected', 'accepted'} for row in current['mapping'])}"
            )
            await refresh_mapping_progress(session_id)
            conflicts = list(mapping.get("professional_conflicts") or [])
            review_issues.clear()
            with review_issues:
                if not conflicts:
                    render_feedback_state("empty", detail="Конфликты пока не зафиксированы.")
                for issue in conflicts:
                    tone = "blocked" if issue.get("severity") == "blocking" else "warn"
                    with ui.row().classes("sov-rim-issue"):
                        status_badge(str(issue.get("code") or "issue"), tone)
                        ui.label(str(issue.get("reason") or "")).classes(
                            "sov-rim-issue__text"
                        )
            review_summary.set_text(
                f"Конфликтов: {len(conflicts)} · блокирующих: "
                f"{sum(item.get('severity') == 'blocking' for item in conflicts)}"
            )
            requirement_table.rows = current["requirements"]
            requirement_table.update()
            requirement_summary.set_text(
                f"Открыто: {sum(item.get('status') == 'open' for item in current['requirements'])}"
            )
            lsr_summary.set_text(
                f"Сценарии: {session.get('scenario_status')} · стоимость: "
                f"{session.get('pricing_status')}"
            )
            final_summary.set_text(
                "Финал доступен."
                if session.get("pricing_status") == "priced_draft"
                else "Сначала закройте mapping, расчёт и блокирующие requirements."
            )

        async def switch_session(event) -> None:
            session_id = str(event.value or "").strip()
            if not session_id or session_id == str(
                app.storage.user.get(_SESSION_KEY) or ""
            ).strip():
                return
            app.storage.user[_SESSION_KEY] = session_id
            await refresh()

        new_button.on_click(create_session)
        refresh_button.on_click(refresh)
        session_select.on_value_change(switch_session)
        send_button.on_click(send_message)
        save_mapping_button.on_click(save_mapping_edit)
        review_button.on_click(run_review)
        lock_button.on_click(lock_mapping)
        scenario_button.on_click(create_scenario)
        calculate_button.on_click(calculate)
        finalize_button.on_click(finalize)
        export_mapping_button.on_click(
            lambda: download(
                f"/api/rim/sessions/{current['session']['session_id']}/mapping/export",
                "mapping.xlsx",
            )
            if isinstance(current.get("session"), dict)
            else None
        )
        draft_export_button.on_click(
            lambda: download(
                f"/api/rim/sessions/{current['session']['session_id']}/export?kind=draft",
                "lsr_draft.xlsx",
            )
            if isinstance(current.get("session"), dict)
            else None
        )
        final_export_button.on_click(
            lambda: download(
                f"/api/rim/sessions/{current['session']['session_id']}/export?kind=final",
                "lsr_final.xlsx",
            )
            if isinstance(current.get("session"), dict)
            else None
        )
        ui.timer(0.1, refresh, once=True)
        ui.timer(5.0, refresh_mapping_progress)
