"""С.О.В.У.Ш.К.А. — вкладка ИНСТРУМЕНТЫ.

v0.24.0.2: экран оставлен только под служебные источники данных. Оператору здесь нужны не
внутренние скрипты, а понятные папки, статус готовности и безопасная кнопка проверки.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from nicegui import ui

from sovushka.state import add_log, api_get, api_post, last_api_error_text

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


def build_instrumenty():
    """Содержимое вкладки ИНСТРУМЕНТЫ. Вызывать внутри with ui.tab_panel(...)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("w-full items-end justify-between gap-3"):
            with ui.column().classes("gap-1"):
                ui.label("ИСТОЧНИКИ ДАННЫХ").style(
                    "font-size:1.08rem;font-weight:900;letter-spacing:1px;"
                )
                ui.label(
                    "Папки и датасеты, на которых ЛЕС считает сметы и проверяет документацию."
                ).style("font-size:.72rem;color:var(--dim);")
            ui.button("ОБНОВИТЬ", on_click=lambda: asyncio.create_task(_refresh())).props("dense no-caps")

        with ui.card().classes("card-les w-full"):
            summary = ui.label("Загрузка источников…").style("font-size:.74rem;color:var(--dim);")
            cards = ui.column().classes("w-full gap-2")

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
                            ui.button(icon="folder_open", on_click=lambda p=folders[0]["path"]: asyncio.create_task(_open_folder(p))).props(
                                "dense flat round"
                            ).tooltip("Открыть папку источника")
                        ui.button(icon="play_arrow", on_click=lambda sid=item.get("id"): asyncio.create_task(_process_source(str(sid)))).props(
                            "dense flat round"
                        ).tooltip(item.get("process_label") or "Проверить источник")

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

        ui.timer(0.2, lambda: asyncio.create_task(_refresh()), once=True)
