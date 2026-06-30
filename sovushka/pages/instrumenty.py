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


def _prompt_text(value: object, *, limit: int = 2200) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


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
            ui.button("ОБНОВИТЬ", on_click=_refresh).props("dense no-caps")

        with ui.card().classes("card-les w-full"):
            summary = ui.label("Загрузка источников…").style("font-size:.74rem;color:var(--dim);")
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
                ui.button("ОБНОВИТЬ", on_click=_refresh_prompts).props("dense no-caps")
            prompt_summary = ui.label("Загрузка промтов…").style("font-size:.74rem;color:var(--dim);")
            prompts_box = ui.column().classes("w-full gap-2")

        async def _process_source(source_id: str) -> None:
            d = await api_post(f"/api/service-sources/{source_id}/process", {})
            if not isinstance(d, dict):
                ui.notify(last_api_error_text("Источник не проверен"), type="negative")
                return
            ui.notify(d.get("message") or "Проверка источника выполнена", type="positive" if d.get("ok") else "warning")
            await _refresh()

        def _render_source(item: dict) -> None:
            label, color = _SRC_STATUS.get(item.get("status"), (str(item.get("status") or "?"), "var(--dim)"))
            folders = [f for f in item.get("folders") or [] if f.get("path")]
            needed = "; ".join(item.get("needed_for") or []) or "служебная работа ЛЕС"
            accepted = ", ".join(item.get("accepted_files") or []) or "поддерживаемые файлы источника"
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
                    with ui.row().classes("items-center gap-1"):
                        if folders:
                            ui.button(icon="folder_open", on_click=_ui_handler(_open_folder, folders[0]["path"])).props(
                                "dense flat round"
                            ).tooltip("Открыть папку источника")
                        ui.button(icon="play_arrow", on_click=_ui_handler(_process_source, str(item.get("id")))).props(
                            "dense flat round"
                        ).tooltip(item.get("process_label") or "Проверить источник")

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

        ui.timer(0.2, _refresh, once=True)
        ui.timer(0.35, _refresh_prompts, once=True)
