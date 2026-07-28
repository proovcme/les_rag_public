"""С.О.В.У.Ш.К.А. — вкладка ИНСТРУМЕНТЫ.

v0.24.0.2: экран оставлен только под служебные источники данных. Оператору здесь нужны не
внутренние скрипты, а понятные папки, статус готовности и безопасная кнопка проверки.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from sovushka.state import add_log, api_delete, api_get, api_patch, api_post, last_api_error_text

_ROOT = Path(__file__).resolve().parents[2]
_SRC_STATUS = {
    "ok": ("Готово", "var(--ok)"),
    "missing_degraded": ("Нужно добавить", "#d6a400"),
    "missing_blocking": ("Блокирует", "var(--err)"),
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


def _prompt_text(value: object, *, limit: int = 2200) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


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

    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("w-full items-end justify-between gap-3"):
            with ui.column().classes("gap-1"):
                ui.label("ИСТОЧНИКИ ДАННЫХ").style(
                    "font-size:1.08rem;font-weight:900;letter-spacing:1px;"
                )
                ui.label(
                    "Папки и датасеты, на которых ЛЕС считает сметы и проверяет документацию."
                ).style("font-size:.72rem;color:var(--dim);")
            with ui.row().classes("items-center gap-2"):
                fgis_update_btn = ui.button("СКАЧАТЬ / ОБНОВИТЬ ФСНБ", icon="cloud_download").props(
                    "dense no-caps"
                ).style("min-height:40px;")
                refresh_btn = ui.button("ОБНОВИТЬ").props("dense no-caps")

        with ui.card().classes("card-les w-full"):
            summary = ui.label("Загрузка источников…").style("font-size:.74rem;color:var(--dim);")
            with ui.row().classes("w-full items-center gap-2"):
                fgis_state_icon = ui.icon("o_schedule").style("font-size:20px;color:var(--dim);")
                fgis_status = ui.label(
                    "ФГИС ЦС: проверка состояния общего обновления…"
                ).style("font-size:.78rem;font-weight:800;flex:1;font-variant-numeric:tabular-nums;")
            fgis_progress = ui.linear_progress(value=0).props("rounded size=6px").classes("w-full")
            fgis_progress.set_visibility(False)
            fgis_detail = ui.label("").style(
                "font-size:.66rem;color:var(--dim);font-variant-numeric:tabular-nums;text-wrap:pretty;"
            )
            with ui.row().classes("w-full gap-2").style("flex-wrap:wrap;"):
                fgis_stage = ui.label("Этап: —").classes("sov-status-pill")
                fgis_counter = ui.label("Готово: —").classes("sov-status-pill")
                fgis_volume = ui.label("Скачано: —").classes("sov-status-pill")
                fgis_eta = ui.label("Осталось: —").classes("sov-status-pill")
            fgis_layers = ui.column().classes("w-full gap-1")
            with ui.expansion("ЖУРНАЛ ОБНОВЛЕНИЯ", icon="o_terminal").classes("w-full").props("dense"):
                fgis_log = ui.log(max_lines=40).classes("w-full").style(
                    "height:180px;background:#111827;color:#d1fae5;border-radius:8px;"
                    "padding:8px;font-size:11px;font-variant-numeric:tabular-nums;"
                )
                fgis_log.push("Ожидаем запуск обновления…")
            fgis_log_state = {"seen": set(), "started": False}
            cards = ui.column().classes("w-full gap-2")

        with ui.card().classes("card-les w-full"):
            with ui.row().classes("w-full items-end justify-between gap-3"):
                with ui.column().classes("gap-1"):
                    ui.label("СИСТЕМНЫЕ ПРОМТЫ").style(
                        "font-size:1.02rem;font-weight:900;letter-spacing:1px;"
                    )
                ui.label(
                    "Общий характер ЛЕСа и режимные рамки. Это поведение модели, не evidence."
                ).style("font-size:.72rem;color:var(--dim);")
                refresh_prompts_btn = ui.button("ОБНОВИТЬ").props("dense no-caps")
            prompt_summary = ui.label("Загрузка промтов…").style("font-size:.74rem;color:var(--dim);")
            prompts_box = ui.column().classes("w-full gap-2")

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
            label, color = _SRC_STATUS.get(item.get("status"), (str(item.get("status") or "?"), "var(--dim)"))
            folders = [f for f in item.get("folders") or [] if f.get("path")]
            needed = "; ".join(item.get("needed_for") or []) or "служебная работа ЛЕС"
            accepted = ", ".join(item.get("accepted_files") or []) or "поддерживаемые файлы источника"
            required_docs = ((item.get("required_documents") or {}).get("items") or [])
            with ui.card().classes("w-full").style("border-radius:8px;box-shadow:none;border:1px solid var(--line);"):
                with ui.row().classes("w-full items-start justify-between gap-3"):
                    with ui.column().classes("gap-1").style("min-width:0;"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(label).style(f"font-size:.72rem;font-weight:900;color:{color};")
                            ui.label(str(item.get("domain") or "")).style("font-size:.68rem;color:var(--dim);")
                        ui.label(str(item.get("label") or item.get("id") or "Источник")).style(
                            "font-size:.92rem;font-weight:800;"
                        )
                        ui.label(f"Папка: {_folder_text(item)}").style("font-size:.72rem;color:var(--fg);")
                        ui.label(f"Класть сюда: {accepted}").style("font-size:.68rem;color:var(--dim);")
                        ui.label(f"Нужно для: {needed}").style("font-size:.68rem;color:var(--dim);")
                        action = str(item.get("operator_action") or "").strip()
                        if action:
                            ui.label(action).style("font-size:.68rem;color:var(--fg);")
                        ui.label(_facts_text(item)).style("font-size:.68rem;color:var(--dim);")
                        req_text = _required_docs_text(item)
                        if req_text:
                            ui.label(req_text).style("font-size:.68rem;color:var(--dim);font-weight:700;")
                    with ui.row().classes("items-center gap-1"):
                        if folders:
                            ui.button(icon="folder_open", on_click=_ui_handler(_open_folder, folders[0]["path"])).props(
                                "dense flat round"
                            ).tooltip("Открыть папку источника")
                        ui.button(icon="play_arrow", on_click=_ui_handler(_process_source, str(item.get("id")))).props(
                            "dense flat round"
                        ).tooltip(item.get("process_label") or "Проверить источник")
                        if str(item.get("id") or "") == "gesn_base":
                            ui.button(icon="cloud_download", on_click=_ui_handler(_update_gesn_from_fgis)).props(
                                "dense flat round"
                            ).tooltip("Скачать/обновить базу ГЭСН из ФГИС ЦС")
                if required_docs:
                    with ui.expansion("Какие документы нужны", icon="inventory_2").classes("w-full").props("dense"):
                        for req in required_docs:
                            req_label, req_color = _SRC_STATUS.get(
                                req.get("status"),
                                (str(req.get("status") or "?"), "var(--dim)"),
                            )
                            preferred = ", ".join(req.get("preferred_files") or []) or "не задано"
                            accepted_raw = ", ".join(req.get("accepted_files") or []) or "не задано"
                            found = int(req.get("found_preferred_count") or 0) + int(req.get("found_raw_count") or 0)
                            with ui.element("div").classes("w-full").style(
                                "border-top:1px solid var(--line);padding:6px 0;"
                            ):
                                with ui.row().classes("w-full items-start justify-between gap-2"):
                                    with ui.column().classes("gap-0").style("min-width:0;"):
                                        ui.label(str(req.get("label") or req.get("id") or "Документ")).style(
                                            "font-size:.76rem;font-weight:800;"
                                        )
                                        ui.label(f"preferred: {preferred}").style(
                                            "font-size:.66rem;color:var(--dim);"
                                        )
                                        ui.label(f"raw accepted: {accepted_raw}").style(
                                            "font-size:.66rem;color:var(--dim);"
                                        )
                                        if req.get("needed_for"):
                                            ui.label("нужно для: " + "; ".join(req.get("needed_for") or [])).style(
                                                "font-size:.66rem;color:var(--fg);"
                                            )
                                    with ui.column().classes("items-end gap-0"):
                                        ui.label(req_label).style(
                                            f"font-size:.68rem;font-weight:900;color:{req_color};"
                                        )
                                        ui.label(f"найдено: {found}").style("font-size:.64rem;color:var(--dim);")

        def _render_prompt_block(title: str, text: str, *, tools: list[str] | None = None) -> None:
            with ui.expansion(title, icon="article").classes("w-full").props("dense"):
                if tools:
                    ui.label("Карта режима: " + ", ".join(tools)).style(
                        "font-size:.68rem;color:var(--dim);margin-bottom:6px;"
                    )
                ui.markdown("```text\n" + _prompt_text(text).replace("```", "'''") + "\n```").classes(
                    "w-full sov-prompt-preview sov-prompt-registry"
                ).style(
                    "font-size:.72rem;line-height:1.45;"
                )

        def _render_prompt_editor(item: dict) -> None:
            key = str(item.get("key") or "")
            title = str(item.get("label") or key)
            overridden = bool(item.get("overridden"))
            with ui.element("div").classes("sov-prompt-editor"):
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    with ui.column().classes("gap-0").style("min-width:0;"):
                        ui.label(title).style("font-size:.82rem;font-weight:900;")
                        ui.label("изменён" if overridden else "по умолчанию").style(
                            "font-size:.66rem;color:var(--dim);"
                        )
                    with ui.row().classes("items-center gap-1"):
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

                        ui.button("Сохранить", icon="o_save", on_click=_save_prompt).props(
                            "dense no-caps"
                        )
                        ui.button(icon="o_restart_alt", on_click=_reset_prompt).props(
                            'flat round dense aria-label="Сбросить промт"'
                        ).tooltip("Сбросить к встроенному промту")
                editor = ui.textarea(value=str(item.get("value") or "")).props(
                    "outlined dense autogrow"
                ).classes("w-full sov-prompt-textarea")

        async def _refresh_prompts() -> None:
            d = await api_get("/api/prompts")
            if not isinstance(d, dict):
                ui.notify(last_api_error_text("Промты недоступны"), type="negative")
                return
            modes = d.get("modes") or {}
            editable = [item for item in d.get("editable") or [] if isinstance(item, dict)]
            changed = sum(1 for item in editable if item.get("overridden"))
            prompt_summary.text = (
                f"Registry: {d.get('schema', '?')} · редактируемых: {len(editable)} · "
                f"изменённых: {changed} · файл: {d.get('overrides_path') or '—'}"
            )
            prompts_box.clear()
            with prompts_box:
                for item in editable:
                    _render_prompt_editor(item)
                ui.separator()
                for mode_id, item in modes.items():
                    if isinstance(item, dict):
                        label = str(item.get("label") or mode_id)
                        prompt = str(item.get("prompt") or "")
                        tools = [str(t) for t in item.get("tools") or []]
                    else:
                        label = str(mode_id)
                        prompt = str(item or "")
                        tools = []
                    _render_prompt_block(f"{label} · {mode_id}", prompt, tools=tools)

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
            if running:
                fgis_state_icon.name = "o_cloud_download"
                fgis_state_icon.style("color:var(--accent);")
            elif state in {"done", "partial"}:
                fgis_state_icon.name = "o_check_circle"
                fgis_state_icon.style("color:var(--ok);")
            elif state in {"failed", "interrupted"}:
                fgis_state_icon.name = "o_error"
                fgis_state_icon.style("color:var(--err);")
            else:
                fgis_state_icon.name = "o_schedule"
                fgis_state_icon.style("color:var(--dim);")
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
                    icon_name, icon_color, state_label = {
                        "done": ("o_check_circle", "var(--ok)", "готово"),
                        "running": ("o_downloading", "var(--accent)", "выполняется"),
                        "warning": ("o_warning", "var(--warn)", "нужен повтор"),
                        "error": ("o_error", "var(--err)", "остановлено"),
                    }.get(layer_state, ("o_schedule", "var(--dim)", "ожидает"))
                    with ui.row().classes("w-full items-center gap-2").style(
                        "padding:5px 7px;border:1px solid var(--line);border-radius:7px;"
                    ):
                        ui.icon(icon_name).style(f"font-size:16px;color:{icon_color};")
                        ui.label(str(layer.get("label") or "Слой")).style(
                            "font-size:.7rem;font-weight:750;flex:1;"
                        )
                        detail = str(layer.get("detail") or "").strip()
                        if detail:
                            ui.label(detail).style("font-size:.64rem;color:var(--dim);")
                        ui.label(state_label).style(f"font-size:.64rem;font-weight:800;color:{icon_color};")
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

        refresh_btn.on("click", _refresh)
        fgis_update_btn.on("click", _update_all_fgis)
        refresh_prompts_btn.on("click", _refresh_prompts)
        ui.timer(0.2, _refresh, once=True)
        ui.timer(0.25, _refresh_fgis_status, once=True)
        ui.timer(3.0, _refresh_fgis_status)
        ui.timer(0.35, _refresh_prompts, once=True)
