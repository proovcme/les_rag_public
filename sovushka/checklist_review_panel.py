"""Operator UI for evidence-led PD/RD checklist review."""

from __future__ import annotations

from urllib.parse import quote

from nicegui import ui

from sovushka.checklist_review_view import evidence_lines, format_item_row, summary_chips
from sovushka.state import (
    add_log,
    api_get,
    api_get_bytes,
    api_post,
    last_api_error_text,
    state,
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

_API = "/api/checklist-review"


def _dataset_options() -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("name") or item.get("id"))
        for item in (state.get("datasets") or [])
        if isinstance(item, dict) and item.get("id")
    }


def _summary_tone(key: str) -> str:
    return {
        "yes": "ok",
        "no": "error",
        "manual_required": "warn",
        "unknown": "muted",
        "human_confirmed": "ok",
    }.get(key, "muted")


def build_checklist_review_card() -> None:
    """Render setup, evidence status and explicit engineer decisions."""

    current: dict[str, object] = {"result": None, "dataset_id": ""}
    templates_cache: list[dict] = []
    selected_item = {"id": ""}

    with panel(variant="raised", classes="sov-checklist"):
        with ui.row().classes("sov-checklist__head"):
            section_heading(
                "Проверка проекта по чек-листу",
                "Код собирает формальные признаки и ссылки. Итоговое инженерное решение "
                "остаётся за моделью и человеком.",
            )
            refresh_button = action_button(
                icon="o_refresh",
                icon_only=True,
                aria_label="Обновить перечни и датасеты",
                variant="quiet",
            )

        with ui.element("section").classes("sov-checklist__setup"):
            template_select = select_field(
                {},
                label="Перечень проверки",
                aria_label="Перечень проверки",
                classes="sov-checklist__field",
            )
            dataset_select = select_field(
                {},
                label="Комплект ПД или РД",
                aria_label="Комплект проектной документации",
                clearable=True,
                classes="sov-checklist__field",
            )
            source_select = select_field(
                {},
                label="ТЗ, СТУ и изыскания",
                aria_label="Дополнительные источники",
                clearable=True,
                multiple=True,
                classes="sov-checklist__field",
            )
            discipline_select = select_field(
                {"": "Все разделы"},
                value="",
                label="Раздел",
                aria_label="Раздел проекта",
                classes="sov-checklist__field",
            )

        with ui.row().classes("sov-checklist__run"):
            run_button = action_button(
                "Начать проверку",
                icon="o_fact_check",
                variant="primary",
            )
            status_label = ui.label(
                "Выберите перечень и комплект документов."
            ).classes("sov-checklist__status")

        chips_box = ui.row().classes("sov-checklist__summary")

        with ui.row().classes("sov-checklist__reports") as download_box:
            ui.label("Отчёт").classes("sov-checklist__reports-label")
            xlsx_button = action_button(
                "Excel", icon="o_grid_on", compact=True, variant="secondary"
            )
            html_button = action_button(
                "HTML", icon="o_description", compact=True, variant="secondary"
            )
            json_button = action_button(
                "Данные", icon="o_data_object", compact=True, variant="quiet"
            )
        download_box.set_visibility(False)

        columns = [
            {"name": "item_no", "label": "№", "field": "item_no", "sortable": True},
            {
                "name": "discipline",
                "label": "Раздел",
                "field": "discipline",
                "sortable": True,
            },
            {
                "name": "criterion_short",
                "label": "Что проверяется",
                "field": "criterion_short",
            },
            {
                "name": "status_label",
                "label": "Evidence-статус",
                "field": "status_label",
                "sortable": True,
            },
            {
                "name": "evidence_count",
                "label": "Источники",
                "field": "evidence_count",
                "sortable": True,
            },
            {
                "name": "human_answer_label",
                "label": "Решение инженера",
                "field": "human_answer_label",
                "sortable": True,
            },
        ]
        table = ui.table(
            columns=columns,
            rows=[],
            row_key="item_id",
            pagination=25,
        ).classes("sov-checklist__table").props(
            'dense wrap-cells flat aria-label="Пункты проверки проекта"'
        )
        table.set_visibility(False)

        with ui.dialog() as details_dialog:
            with ui.card().classes(
                "sov-ui-panel sov-ui-panel--raised sov-checklist-dialog"
            ):
                criterion_label = ui.label("").classes("sov-checklist-dialog__title")
                meta_label = ui.label("").classes("sov-checklist-dialog__meta")
                ui.separator()
                section_heading(
                    "Основания в документах",
                    "Только найденные фрагменты с проверяемой ссылкой.",
                )
                evidence_box = ui.column().classes("sov-checklist-dialog__evidence")
                with ui.expansion(
                    "Техническая проверка",
                    icon="o_rule",
                ).classes("sov-checklist-dialog__details").props("dense"):
                    system_note = ui.label("").classes("sov-checklist-dialog__note")
                ui.separator()
                section_heading(
                    "Решение инженера",
                    "Оно не выводится автоматически из evidence-статуса.",
                )
                human_note = text_field(
                    label="Комментарий к решению",
                    clearable=True,
                    classes="sov-checklist-dialog__input",
                )

                async def save_decision(answer: str) -> None:
                    result = current.get("result")
                    dataset_id = str(current.get("dataset_id") or "")
                    if not isinstance(result, dict) or not dataset_id or not selected_item["id"]:
                        return
                    response = await api_post(
                        f"{_API}/{quote(dataset_id, safe='')}/runs/"
                        f"{quote(str(result.get('run_id') or ''), safe='')}/items/"
                        f"{quote(selected_item['id'], safe='')}/decision",
                        {
                            "human_answer": answer,
                            "human_note": str(human_note.value or "").strip(),
                        },
                    )
                    if not isinstance(response, dict):
                        ui.notify(last_api_error_text("Решение не сохранено"), type="negative")
                        return
                    details_dialog.close()
                    ui.notify("Решение сохранено", type="positive")
                    await reload_run()

                with ui.row().classes("sov-checklist-dialog__actions"):
                    action_button(
                        "Не относится",
                        on_click=lambda: save_decision("not_required"),
                        variant="quiet",
                    )
                    action_button(
                        "Есть замечание",
                        on_click=lambda: save_decision("no"),
                        variant="danger",
                    )
                    action_button(
                        "Подтверждено",
                        on_click=lambda: save_decision("yes"),
                        variant="primary",
                    )

        def find_item(item_id: str) -> dict | None:
            result = current.get("result")
            if not isinstance(result, dict):
                return None
            return next(
                (
                    item
                    for item in result.get("items", [])
                    if item.get("item_id") == item_id
                ),
                None,
            )

        def open_item(item_id: str) -> None:
            item = find_item(item_id)
            if item is None:
                return
            row = format_item_row(item)
            selected_item["id"] = row["item_id"]
            criterion_label.text = row["criterion_full"] or "Критерий не указан"
            meta_label.text = (
                f"№ {row['item_no']} · {row['discipline']} · "
                f"{row['status_label']} · источников: {row['evidence_count']}"
            )
            evidence_box.clear()
            with evidence_box:
                refs = evidence_lines(item)
                if refs:
                    for line in refs:
                        ui.label(line).classes("sov-checklist-dialog__source")
                else:
                    render_feedback_state(
                        "empty",
                        detail="Подтверждающий фрагмент пока не найден.",
                    )
            system_note.text = row["model_note"] or "Технических деталей нет."
            human_note.value = row["human_note"]
            details_dialog.open()

        table.on(
            "rowClick",
            lambda event: open_item(
                str((event.args or [None, {}, None])[1].get("item_id", ""))
            ),
        )

        def render(result: dict) -> None:
            chips_box.clear()
            with chips_box:
                for chip in summary_chips(result.get("summary") or {}):
                    status_badge(
                        f"{chip['label']}: {chip['value']}",
                        _summary_tone(str(chip["key"])),
                    )
            table.rows = [
                format_item_row(item) for item in result.get("items") or []
            ]
            table.update()
            table.set_visibility(bool(table.rows))
            download_box.set_visibility(True)

        async def reload_run() -> None:
            result = current.get("result")
            dataset_id = str(current.get("dataset_id") or "")
            if not isinstance(result, dict) or not dataset_id:
                return
            response = await api_get(
                f"{_API}/{quote(dataset_id, safe='')}/runs/"
                f"{quote(str(result.get('run_id') or ''), safe='')}"
            )
            if isinstance(response, dict):
                current["result"] = response
                render(response)

        def refresh_disciplines() -> None:
            selected = str(template_select.value or "")
            disciplines = next(
                (
                    item.get("disciplines") or []
                    for item in templates_cache
                    if item.get("name") == selected
                ),
                [],
            )
            discipline_select.options = {
                "": "Все разделы",
                **{name: name for name in disciplines},
            }
            if discipline_select.value not in discipline_select.options:
                discipline_select.value = ""
            discipline_select.update()

        async def refresh() -> None:
            response = await api_get(f"{_API}/templates")
            if isinstance(response, dict):
                templates_cache[:] = [
                    item
                    for item in response.get("templates") or []
                    if isinstance(item, dict) and not item.get("error")
                ]
                template_select.options = {
                    str(item.get("name")): (
                        f"{item.get('title') or item.get('name')} · "
                        f"{item.get('items_count', 0)} пунктов"
                    )
                    for item in templates_cache
                    if item.get("name")
                }
                if (
                    template_select.value not in template_select.options
                    and template_select.options
                ):
                    template_select.value = next(iter(template_select.options))
                template_select.update()
                refresh_disciplines()
            options = _dataset_options()
            dataset_select.options = options
            source_select.options = options
            dataset_select.update()
            source_select.update()

        async def run() -> None:
            if not template_select.value or not dataset_select.value:
                ui.notify(
                    "Выберите перечень проверки и комплект документов",
                    type="warning",
                )
                return
            run_button.props("loading")
            status_label.text = "Собираю формальные признаки и источники…"
            response = await api_post(
                f"{_API}/{quote(str(dataset_select.value), safe='')}/run",
                {
                    "template": template_select.value,
                    "source_dataset_ids": list(source_select.value or []),
                    "discipline": discipline_select.value or None,
                },
            )
            run_button.props(remove="loading")
            if not isinstance(response, dict):
                status_label.text = last_api_error_text("Проверка не выполнена")
                ui.notify(status_label.text, type="negative")
                return
            current.update(result=response, dataset_id=str(dataset_select.value))
            total = int((response.get("summary") or {}).get("total") or 0)
            status_label.text = (
                f"Проверено пунктов: {total}. Откройте строку и изучите основания."
            )
            render(response)
            add_log(f"[НОРМКОНТРОЛЬ] evidence-проверка: {total} пунктов")

        async def download(fmt: str) -> None:
            result = current.get("result")
            dataset_id = str(current.get("dataset_id") or "")
            if not isinstance(result, dict) or not dataset_id:
                return
            blob = await api_get_bytes(
                f"{_API}/{quote(dataset_id, safe='')}/runs/"
                f"{quote(str(result.get('run_id') or ''), safe='')}/download?fmt={fmt}"
            )
            if blob:
                ui.download(blob[0], blob[1] or f"проверка_пд_рд.{fmt}")
            else:
                ui.notify(last_api_error_text("Отчёт не подготовлен"), type="negative")

        template_select.on("update:model-value", lambda _event: refresh_disciplines())
        refresh_button.on("click", refresh)
        run_button.on("click", run)
        xlsx_button.on("click", lambda: download("xlsx"))
        html_button.on("click", lambda: download("html"))
        json_button.on("click", lambda: download("json"))
        ui.timer(0.2, refresh, once=True)
