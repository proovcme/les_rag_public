"""С.О.В.У.Ш.К.А. — вкладка ИНСТРУМЕНТЫ.

v0.24.0.2: экран оставлен только под служебные источники данных. Оператору здесь нужны не
внутренние скрипты, а понятные папки, статус готовности и безопасная кнопка проверки.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from sovushka.checklist_review_panel import build_checklist_review_card
from sovushka.state import add_log, api_delete, api_get, api_patch, api_post, last_api_error_text
from sovushka.uikit.components import (
    action_button,
    panel,
    section_heading,
    status_badge,
)

_ROOT = Path(__file__).resolve().parents[2]
_SRC_STATUS = {
    "ok": ("Готово", "var(--ok)"),
    "missing_degraded": ("Нужно добавить", "#d6a400"),
    "missing_blocking": ("Блокирует", "var(--err)"),
}
_SRC_TONES = {
    "ok": "ok",
    "missing_degraded": "warn",
    "missing_blocking": "blocked",
}


def _safe_repo_path(rel_path: str) -> Path | None:
    raw = str(rel_path or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = _ROOT / p
    try:
        resolved = p.resolve()
        root = _ROOT.resolve()
    except Exception:
        return None
    if resolved == root or root in resolved.parents:
        return resolved
    return None


async def _open_folder(rel_path: str) -> None:
    path = _safe_repo_path(rel_path)
    if path is None:
        ui.notify("Папка вне рабочего дерева ЛЕС", type="negative")
        return
    if path.is_file():
        path = path.parent
    if not path.exists():
        ui.notify(f"Папки пока нет: {path}", type="warning")
        return
    add_log(f"[ИСТОЧНИКИ] open {path}")
    try:
        subprocess.run(["open", str(path)], check=False, timeout=5)
        ui.notify(f"Открываю: {path.name}", type="positive")
    except Exception as err:  # noqa: BLE001
        ui.notify(f"Не удалось открыть папку: {err}", type="negative")


def _facts_text(item: dict) -> str:
    facts = item.get("facts") or {}
    labels = {
        "base_norms": "норм",
        "seed_norms": "семя",
        "parquet_rows": "строк базы",
        "pricebooks": "файлов цен",
        "price_rows": "строк цен",
        "targets": "проверок",
        "documents": "документов",
        "datasets": "датасетов",
    }
    parts = [f"{name}: {facts[key]}" for key, name in labels.items() if facts.get(key) not in (None, "", 0)]
    if parts:
        return " · ".join(parts)
    files = [f for f in item.get("files") or [] if f.get("exists")]
    if files:
        return "найдено: " + ", ".join(str(f.get("path") or "") for f in files[:2])
    return "данные пока не найдены"


def _folder_text(item: dict) -> str:
    folders = [str(f.get("path") or "") for f in item.get("folders") or [] if f.get("path")]
    if folders:
        return ", ".join(folders[:3])
    dataset = item.get("dataset") or {}
    if dataset.get("documents"):
        return "нормативный RAG-датасет"
    return "папка не задана"


def _required_docs_text(item: dict) -> str:
    req = item.get("required_documents") or {}
    summary = req.get("summary") or {}
    total = int(summary.get("total") or 0)
    if not total:
        return ""
    return (
        f"документы: готово {summary.get('ready', 0)} · "
        f"частично {summary.get('partial', 0)} · "
        f"нет {int(summary.get('missing_blocking') or 0) + int(summary.get('missing_degraded') or 0)}"
    )


def _format_duration(value: object) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {secs} с"
    return f"{secs} с"


def _format_bytes(value: object) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        return "0 Б"
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.1f} {unit}" if unit != "Б" else f"{size} {unit}"
        size /= 1024
    return "0 Б"


def _format_rate(value: object) -> str:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{_format_bytes(max(0, int(rate)))}/с"


def _fgis_progress_text(payload: dict) -> tuple[str, str, float | None, bool]:
    progress = payload.get("progress") or {}
    state = str(progress.get("state") or "idle")
    running = state == "running"
    stage = str(progress.get("stage_label") or "ожидание")
    percent_raw = progress.get("percent")
    try:
        percent = min(100.0, max(0.0, float(percent_raw))) if percent_raw is not None else None
    except (TypeError, ValueError):
        percent = None

    if running:
        completed = progress.get("completed")
        total = progress.get("total")
        counter = f" · {completed}/{total}" if completed is not None and total else ""
        summary = f"ФГИС ЦС: выполняется · {stage}{counter}"
    elif state in {"done", "partial"}:
        raw = payload.get("status") or {}
        prices = raw.get("prices") or {}
        summary = (
            f"ФГИС ЦС: завершено · книг {prices.get('done', 0)}/{prices.get('requested', 0)} · "
            f"строк {prices.get('rows', 0)}"
        )
        percent = 100.0
    elif state == "failed":
        summary = "ФГИС ЦС: ошибка обновления"
    elif state == "interrupted":
        summary = "ФГИС ЦС: обновление прервано"
    else:
        return (
            "ФГИС ЦС: общее обновление ещё не запускалось",
            "Нажмите «Скачать ФГИС ЦС». Обычная кнопка обновления сверху только перечитывает показатели.",
            None,
            False,
        )

    details: list[str] = []
    reason = str(progress.get("reason") or "").strip()
    if reason:
        details.append(reason)
    current = progress.get("current") or {}
    location = " · ".join(
        str(current.get(key) or "").strip()
        for key in ("subject", "zone", "period")
        if str(current.get(key) or "").strip()
    )
    if not location and current.get("collection"):
        location = f"сборник {current.get('collection')}"
        if current.get("prefix"):
            location += f" · отдел {current.get('prefix')}"
    if location:
        details.append(f"Сейчас: {location}")
    raw = payload.get("status") or {}
    gesn_progress = raw.get("gesn_progress") or progress.get("current") or {}
    if isinstance(gesn_progress, dict):
        skipped = gesn_progress.get("otdels_skipped")
        done = gesn_progress.get("otdels_done")
        if skipped or done:
            details.append(
                f"Отделы ГЭСН: новых {int(done or 0)}, пропущено {int(skipped or 0)}"
            )
        if gesn_progress.get("resumed_complete"):
            details.append("Локальный кэш норм полный — сеть ФГИС для ГЭСН не дергаем")
    remaining = progress.get("remaining")
    if remaining is not None:
        unit = "книг" if progress.get("units") == "books" else "сборников"
        details.append(f"Осталось: {remaining} {unit}")
    if progress.get("eta_seconds") is not None:
        details.append(f"Примерно: {_format_duration(progress.get('eta_seconds'))}")
    if progress.get("bytes_downloaded"):
        details.append(f"Скачано: {_format_bytes(progress.get('bytes_downloaded'))}")
    if progress.get("rate_bytes_per_second"):
        details.append(f"Средняя скорость: {_format_rate(progress.get('rate_bytes_per_second'))}")
    age = progress.get("heartbeat_age_seconds")
    if running and age is not None:
        details.append(f"Статус обновлён {_format_duration(age)} назад")
    return summary, " · ".join(details), percent, running


def build_instrumenty():
    """Содержимое вкладки ИНСТРУМЕНТЫ. Вызывать внутри with ui.tab_panel(...)."""
    def _ui_handler(coro_func, *args, **kwargs):
        async def _handler(*_event_args):
            await coro_func(*args, **kwargs)

        return _handler

    with ui.column().classes("w-full sov-tools-page"):
        with panel(variant="raised", classes="sov-tools-hero"):
            with ui.row().classes("sov-tools-hero__row"):
                section_heading(
                    "Инструменты",
                    "Рабочие источники ЛЕС и только те системные промпты, которые подключены к генерации.",
                )
                with ui.row().classes("sov-tools-actions"):
                    refresh_btn = action_button(
                        "Обновить",
                        icon="o_refresh",
                        compact=True,
                        variant="secondary",
                    )
                    fgis_update_btn = action_button(
                        "Обновить ФСНБ",
                        icon="o_cloud_download",
                        compact=True,
                        variant="primary",
                    )

        build_checklist_review_card()

        with panel(variant="plain", classes="sov-tools-section"):
            section_heading(
                "Источники данных",
                "Папки и датасеты, на которых ЛЕС считает сметы и проверяет документацию.",
            )
            summary = ui.label("Загрузка источников…").classes("sov-tools-summary")
            with panel(variant="inset", classes="sov-tools-fgis"):
                with ui.row().classes("sov-tools-fgis__head"):
                    fgis_state_icon = ui.icon("o_schedule").classes("sov-tools-state-icon")
                    fgis_status = ui.label(
                        "ФГИС ЦС: проверка состояния общего обновления…"
                    ).classes("sov-tools-fgis__title")
                fgis_progress = ui.linear_progress(value=0).props("rounded size=6px").classes("w-full")
                fgis_progress.set_visibility(False)
                fgis_detail = ui.label("").classes("sov-tools-detail")
                with ui.row().classes("sov-tools-metrics"):
                    fgis_stage = ui.label("Этап: —").classes("sov-status-pill")
                    fgis_counter = ui.label("Готово: —").classes("sov-status-pill")
                    fgis_volume = ui.label("Скачано: —").classes("sov-status-pill")
                    fgis_eta = ui.label("Осталось: —").classes("sov-status-pill")
                fgis_layers = ui.column().classes("w-full gap-1")
                with ui.expansion("Технический журнал", icon="o_terminal").classes(
                    "w-full sov-tools-disclosure"
                ).props("dense"):
                    fgis_log = ui.log(max_lines=40).classes("w-full sov-tools-log")
                    fgis_log.push("Ожидаем запуск обновления…")
                fgis_log_state = {"seen": set(), "started": False}
            with panel(variant="inset", classes="sov-tools-fgis"):
                with ui.row().classes("sov-tools-fgis__head"):
                    etm_state_icon = ui.icon("o_storefront").classes("sov-tools-state-icon")
                    etm_status = ui.label("ЭТМ: проверка…").classes("sov-tools-fgis__title")
                etm_detail = ui.label(
                    "Коммерческие цены поставщика для КАЦ (read-only Product API)."
                ).classes("sov-tools-detail")
                with ui.row().classes("sov-tools-metrics items-end gap-2"):
                    etm_code_input = ui.input(
                        label="Код ЭТМ",
                        placeholder="9536092",
                    ).classes("w-40")
                    etm_lookup_btn = action_button(
                        "Запросить цену ЭТМ",
                        icon="o_request_quote",
                        compact=True,
                        variant="secondary",
                    )
                etm_lookup_result = ui.label("").classes("sov-tools-detail")
            cards = ui.column().classes("w-full sov-tools-source-list")

        with panel(variant="plain", classes="sov-tools-section sov-tools-prompts"):
            with ui.row().classes("sov-tools-section__head"):
                section_heading(
                    "Системные промпты",
                    "Редактируются только пять реальных генераторов плюс общий характер и тон.",
                )
                refresh_prompts_btn = action_button(
                    "Обновить",
                    icon="o_refresh",
                    compact=True,
                    variant="quiet",
                )
            prompt_summary = ui.label("Проверяю подключения…").classes("sov-tools-summary")
            prompts_box = ui.column().classes("w-full sov-tools-prompt-list")

        async def _process_source(source_id: str) -> None:
            d = await api_post(f"/api/service-sources/{source_id}/process", {})
            if not isinstance(d, dict):
                ui.notify(last_api_error_text("Источник не проверен"), type="negative")
                return
            ui.notify(d.get("message") or "Проверка источника выполнена", type="positive" if d.get("ok") else "warning")
            await _refresh()

        async def _update_gesn_from_fgis() -> None:
            d = await api_post("/api/service-sources/gesn_base/fgis-update", {})
            if not isinstance(d, dict) or not d.get("ok"):
                message = (
                    str(d.get("message") or d.get("reason") or "").strip()
                    if isinstance(d, dict)
                    else ""
                )
                ui.notify(message or last_api_error_text("Обновление ГЭСН не запущено"), type="negative")
                return
            if d.get("started"):
                ui.notify("ГЭСН: запущено скачивание/обновление из ФГИС ЦС", type="positive")
            else:
                ui.notify("ГЭСН: обновление уже выполняется", type="info")
            await _refresh()

        async def _update_all_fgis() -> None:
            d = await api_post("/api/service-sources/fgis/update", {})
            if not isinstance(d, dict) or not d.get("ok"):
                message = (
                    str(d.get("message") or d.get("reason") or "").strip()
                    if isinstance(d, dict)
                    else ""
                )
                ui.notify(message or last_api_error_text("Обновление ФГИС ЦС не запущено"), type="negative")
                return
            if d.get("started"):
                ui.notify(str(d.get("message") or "Обновление ФГИС ЦС запущено"), type="positive")
            else:
                ui.notify("Обновление ФГИС ЦС уже выполняется", type="info")
            await _refresh_fgis_status()

        def _render_source(item: dict) -> None:
            source_status = str(item.get("status") or "")
            label, _color = _SRC_STATUS.get(source_status, (source_status or "Неизвестно", "var(--dim)"))
            folders = [f for f in item.get("folders") or [] if f.get("path")]
            needed = "; ".join(item.get("needed_for") or []) or "служебная работа ЛЕС"
            accepted = ", ".join(item.get("accepted_files") or []) or "поддерживаемые файлы источника"
            required_docs = ((item.get("required_documents") or {}).get("items") or [])
            with panel(variant="inset", classes="sov-tools-source"):
                with ui.row().classes("sov-tools-source__row"):
                    ui.icon("o_folder_copy").classes("sov-tools-source__icon")
                    with ui.column().classes("sov-tools-source__copy"):
                        with ui.row().classes("sov-tools-source__identity"):
                            ui.label(str(item.get("label") or item.get("id") or "Источник")).classes(
                                "sov-tools-source__title"
                            )
                            status_badge(label, _SRC_TONES.get(source_status, "muted"))
                        ui.label(str(item.get("domain") or "Служебный источник")).classes(
                            "sov-tools-source__domain"
                        )
                        ui.label(f"Папка: {_folder_text(item)}").classes("sov-tools-source__line")
                        ui.label(f"Принимает: {accepted}").classes("sov-tools-source__meta")
                        ui.label(f"Нужен для: {needed}").classes("sov-tools-source__meta")
                        action = str(item.get("operator_action") or "").strip()
                        if action:
                            ui.label(action).classes("sov-tools-source__line")
                        ui.label(_facts_text(item)).classes("sov-tools-source__meta")
                        req_text = _required_docs_text(item)
                        if req_text:
                            ui.label(req_text).classes("sov-tools-source__meta sov-tools-source__meta--strong")
                    with ui.row().classes("sov-tools-source__actions"):
                        if folders:
                            action_button(
                                icon="o_folder_open",
                                on_click=_ui_handler(_open_folder, folders[0]["path"]),
                                variant="quiet",
                                compact=True,
                                icon_only=True,
                                aria_label="Открыть папку источника",
                            ).tooltip("Открыть папку источника")
                        action_button(
                            icon="o_play_arrow",
                            on_click=_ui_handler(_process_source, str(item.get("id"))),
                            variant="secondary",
                            compact=True,
                            icon_only=True,
                            aria_label=item.get("process_label") or "Проверить источник",
                        ).tooltip(item.get("process_label") or "Проверить источник")
                        if str(item.get("id") or "") == "gesn_base":
                            action_button(
                                icon="o_cloud_download",
                                on_click=_ui_handler(_update_gesn_from_fgis),
                                variant="secondary",
                                compact=True,
                                icon_only=True,
                                aria_label="Обновить базу ГЭСН",
                            ).tooltip("Скачать/обновить базу ГЭСН из ФГИС ЦС")
                if required_docs:
                    with ui.expansion("Какие документы нужны", icon="o_inventory_2").classes(
                        "w-full sov-tools-disclosure"
                    ).props("dense"):
                        for req in required_docs:
                            req_label, _req_color = _SRC_STATUS.get(
                                req.get("status"),
                                (str(req.get("status") or "?"), "var(--dim)"),
                            )
                            preferred = ", ".join(req.get("preferred_files") or []) or "не задано"
                            accepted_raw = ", ".join(req.get("accepted_files") or []) or "не задано"
                            found = int(req.get("found_preferred_count") or 0) + int(req.get("found_raw_count") or 0)
                            with ui.element("div").classes("sov-tools-required-doc"):
                                with ui.row().classes("sov-tools-required-doc__row"):
                                    with ui.column().classes("sov-tools-required-doc__copy"):
                                        ui.label(str(req.get("label") or req.get("id") or "Документ")).classes(
                                            "sov-tools-required-doc__title"
                                        )
                                        ui.label(f"Предпочтительно: {preferred}").classes(
                                            "sov-tools-source__meta"
                                        )
                                        ui.label(f"Принимается: {accepted_raw}").classes(
                                            "sov-tools-source__meta"
                                        )
                                        if req.get("needed_for"):
                                            ui.label("Нужно для: " + "; ".join(req.get("needed_for") or [])).classes(
                                                "sov-tools-source__line"
                                            )
                                    with ui.column().classes("items-end gap-1"):
                                        status_badge(
                                            req_label,
                                            _SRC_TONES.get(str(req.get("status") or ""), "muted"),
                                        )
                                        ui.label(f"Найдено: {found}").classes("sov-tools-source__meta")

        def _render_prompt_editor(item: dict) -> None:
            key = str(item.get("key") or "")
            title = str(item.get("label") or key)
            overridden = bool(item.get("overridden"))
            runtime_uses = [str(value) for value in item.get("runtime_uses") or []]
            with ui.expansion(title, icon="o_tune").classes(
                "w-full sov-tools-prompt"
            ).props("dense"):
                with ui.row().classes("sov-tools-prompt__meta"):
                    status_badge("Подключён", "ok")
                    ui.label("изменён оператором" if overridden else "встроенный").classes(
                        "sov-tools-source__meta"
                    )
                if runtime_uses:
                    ui.label("Используется: " + " · ".join(runtime_uses)).classes(
                        "sov-tools-prompt__runtime"
                    )
                with ui.column().classes("w-full sov-tools-prompt__editor"):
                    editor = ui.textarea(value=str(item.get("value") or "")).props(
                        "outlined dense autogrow"
                    ).classes("w-full sov-prompt-textarea")
                    with ui.row().classes("sov-tools-prompt__actions"):
                        async def _save_prompt() -> None:
                            d = await api_patch(f"/api/prompts/{quote(key, safe='')}", {"value": editor.value or ""})
                            if isinstance(d, dict):
                                ui.notify("Промт сохранён", type="positive")
                                await _refresh_prompts()
                            else:
                                ui.notify(last_api_error_text("Промт не сохранён"), type="negative")

                        async def _reset_prompt() -> None:
                            d = await api_delete(f"/api/prompts/{quote(key, safe='')}")
                            if isinstance(d, dict):
                                ui.notify("Промт сброшен", type="positive")
                                await _refresh_prompts()
                            else:
                                ui.notify(last_api_error_text("Промт не сброшен"), type="negative")

                        action_button(
                            "Сохранить",
                            icon="o_save",
                            on_click=_save_prompt,
                            compact=True,
                            variant="primary",
                        )
                        reset = action_button(
                            "Сбросить",
                            icon="o_restart_alt",
                            on_click=_reset_prompt,
                            compact=True,
                            variant="quiet",
                        )
                        if not overridden:
                            reset.props("disable")

        async def _refresh_prompts() -> None:
            d = await api_get("/api/prompts")
            if not isinstance(d, dict):
                ui.notify(last_api_error_text("Промты недоступны"), type="negative")
                return
            editable = [item for item in d.get("editable") or [] if isinstance(item, dict)]
            connected = [item for item in editable if item.get("connected")]
            changed = sum(1 for item in editable if item.get("overridden"))
            extra = len(editable) - len(connected)
            prompt_summary.text = (
                f"Подключено: {len(connected)} · лишних: {extra} · изменений: {changed}. "
                "Правка применяется к следующему вызову модели."
            )
            prompts_box.clear()
            with prompts_box:
                for item in connected:
                    _render_prompt_editor(item)

        async def _refresh() -> None:
            d = await api_get("/api/service-sources")
            if not isinstance(d, dict):
                ui.notify(last_api_error_text("Реестр источников недоступен"), type="negative")
                return
            s = d.get("summary", {})
            summary.text = (
                f"Источников: {s.get('total', 0)} · готовы {s.get('ok', 0)} · "
                f"нужно добавить {s.get('missing_degraded', 0)} · блокируют {s.get('missing_blocking', 0)}"
            )
            cards.clear()
            with cards:
                for item in d.get("sources") or []:
                    _render_source(item)
            await _refresh_etm_status()

        async def _refresh_fgis_status() -> None:
            d = await api_get("/api/service-sources/fgis/update/status")
            if not isinstance(d, dict):
                fgis_status.text = "ФГИС ЦС: статус обновления недоступен"
                fgis_detail.text = last_api_error_text("Не удалось прочитать состояние фоновой задачи")
                fgis_progress.set_visibility(False)
                fgis_update_btn.props(remove="loading disable")
                return
            status_text, detail_text, percent, running = _fgis_progress_text(d)
            progress = d.get("progress") or {}
            dependency = d.get("gesn_dependency") or {}
            if dependency.get("running"):
                dep_progress = dependency.get("progress") or {}
                dep_text = "ГЭСН уже скачивается отдельно"
                if dep_progress.get("current_prefix"):
                    dep_text += f" · сейчас {dep_progress.get('current_prefix')}"
                if dep_progress.get("otdels_done") is not None:
                    dep_text += f" · отделов готово {dep_progress.get('otdels_done')}"
                detail_text = f"{detail_text} · {dep_text}" if detail_text else dep_text
            fgis_status.text = status_text
            fgis_detail.text = detail_text
            state = str(progress.get("state") or "idle")
            state_tone = "muted"
            if running:
                fgis_state_icon.name = "o_cloud_download"
                state_tone = "accent"
            elif state in {"done", "partial"}:
                fgis_state_icon.name = "o_check_circle"
                state_tone = "ok"
            elif state in {"failed", "interrupted"}:
                fgis_state_icon.name = "o_error"
                state_tone = "error"
            else:
                fgis_state_icon.name = "o_schedule"
            fgis_state_icon.classes(
                remove="sov-tools-state-icon--accent sov-tools-state-icon--ok sov-tools-state-icon--error sov-tools-state-icon--muted",
                add=f"sov-tools-state-icon--{state_tone}",
            )
            fgis_stage.text = f"Этап: {progress.get('stage_label') or 'ожидание'}"
            completed = progress.get("completed")
            total = progress.get("total")
            fgis_counter.text = (
                f"Готово: {completed}/{total}" if completed is not None and total else "Готово: —"
            )
            fgis_volume.text = f"Скачано: {_format_bytes(progress.get('bytes_downloaded'))}"
            fgis_eta.text = (
                f"Осталось: {_format_duration(progress.get('eta_seconds'))}"
                if progress.get("eta_seconds") is not None
                else "Осталось: считаем…" if running else "Осталось: —"
            )
            fgis_layers.clear()
            with fgis_layers:
                for layer in d.get("layers") or []:
                    layer_state = str(layer.get("state") or "pending")
                    icon_name, layer_tone, state_label = {
                        "done": ("o_check_circle", "ok", "готово"),
                        "running": ("o_downloading", "accent", "выполняется"),
                        "warning": ("o_warning", "warn", "нужен повтор"),
                        "error": ("o_error", "error", "остановлено"),
                    }.get(layer_state, ("o_schedule", "muted", "ожидает"))
                    with ui.row().classes(f"sov-tools-layer sov-tools-layer--{layer_tone}"):
                        ui.icon(icon_name).classes("sov-tools-layer__icon")
                        ui.label(str(layer.get("label") or "Слой")).classes("sov-tools-layer__title")
                        detail = str(layer.get("detail") or "").strip()
                        if detail:
                            ui.label(detail).classes("sov-tools-layer__detail")
                        ui.label(state_label).classes("sov-tools-layer__state")
            raw_lines = [str(line) for line in d.get("log_tail") or []]
            current = progress.get("current") or {}
            current_name = " · ".join(
                str(current.get(key) or "").strip()
                for key in ("subject", "zone", "period", "collection", "prefix")
                if str(current.get(key) or "").strip()
            )
            synthetic = (
                f"[{str(progress.get('updated_at') or '')[11:19]}] "
                f"{progress.get('stage_label') or 'ожидание'}"
                + (f" · {completed}/{total}" if completed is not None and total else "")
                + (f" · {current_name}" if current_name else "")
            )
            if running or state in {"done", "partial", "failed", "interrupted"}:
                raw_lines.append(synthetic)
            new_lines = [line for line in raw_lines if line and line not in fgis_log_state["seen"]]
            if new_lines and not fgis_log_state["started"]:
                fgis_log.clear()
                fgis_log_state["started"] = True
            for line in new_lines:
                fgis_log.push(line)
                fgis_log_state["seen"].add(line)
            if running:
                fgis_update_btn.props("loading disable")
                fgis_progress.set_visibility(True)
                if percent is None:
                    fgis_progress.props("indeterminate")
                else:
                    fgis_progress.props(remove="indeterminate")
                    fgis_progress.value = percent / 100.0
            else:
                fgis_update_btn.props(remove="loading disable")
                if percent is None:
                    fgis_progress.set_visibility(False)
                else:
                    fgis_progress.props(remove="indeterminate")
                    fgis_progress.value = percent / 100.0
                    fgis_progress.set_visibility(True)

        async def _refresh_etm_status() -> None:
            d = await api_get("/api/prices/etm/status")
            if not isinstance(d, dict):
                etm_status.text = "ЭТМ: статус недоступен"
                etm_detail.text = last_api_error_text("Не удалось прочитать конфигурацию ЭТМ")
                etm_state_icon.classes(
                    remove="sov-tools-state-icon--accent sov-tools-state-icon--ok sov-tools-state-icon--error sov-tools-state-icon--muted",
                    add="sov-tools-state-icon--error",
                )
                etm_lookup_btn.props("disable")
                return
            configured = bool(d.get("configured"))
            caps = d.get("capabilities") or {}
            etm_status.text = (
                "ЭТМ: настроен (read-only Product API)"
                if configured
                else "ЭТМ: не настроен — задайте LES_ETM_LOGIN / LES_ETM_PASSWORD"
            )
            etm_detail.text = (
                f"Каталог Goods: {'да' if caps.get('goods_browse') else 'нет'} · "
                f"цены→КАЦ: {'да' if caps.get('kac_map') else 'нет'} · "
                f"заказы: нет · {d.get('base_url') or ''}"
            )
            etm_state_icon.classes(
                remove="sov-tools-state-icon--accent sov-tools-state-icon--ok sov-tools-state-icon--error sov-tools-state-icon--muted",
                add="sov-tools-state-icon--ok" if configured else "sov-tools-state-icon--muted",
            )
            if configured:
                etm_lookup_btn.props(remove="disable")
            else:
                etm_lookup_btn.props("disable")

        async def _lookup_etm_price() -> None:
            code = str(etm_code_input.value or "").strip()
            if not code:
                ui.notify("Укажите код ЭТМ", type="warning")
                return
            d = await api_post(
                "/api/prices/etm/lookup-batch",
                {
                    "items": [{
                        "code": code,
                        "material": f"ETM {code}",
                        "unit": "шт",
                    }],
                },
            )
            if not isinstance(d, dict):
                etm_lookup_result.text = last_api_error_text("Запрос цены ЭТМ не выполнен")
                ui.notify(etm_lookup_result.text, type="negative")
                return
            rows = d.get("rows") or []
            row = rows[0] if rows else {}
            if row.get("found"):
                etm_lookup_result.text = (
                    f"Код {code}: {row.get('price')} "
                    f"({row.get('price_field') or 'pricewnds'}; provenance supplier_api)"
                )
                ui.notify("Цена ЭТМ получена", type="positive")
            else:
                reason = str(row.get("reason") or "not_found")
                etm_lookup_result.text = (
                    f"Код {code}: цена не взята ({reason}) — оставляем MISSING, не 0"
                )
                ui.notify(etm_lookup_result.text, type="warning")

        refresh_btn.on("click", _refresh)
        fgis_update_btn.on("click", _update_all_fgis)
        etm_lookup_btn.on("click", _ui_handler(_lookup_etm_price))
        refresh_prompts_btn.on("click", _refresh_prompts)
        ui.timer(0.2, _refresh, once=True)
        ui.timer(0.25, _refresh_fgis_status, once=True)
        ui.timer(3.0, _refresh_fgis_status)
        ui.timer(0.3, _refresh_etm_status, once=True)
        ui.timer(0.35, _refresh_prompts, once=True)
