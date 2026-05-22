"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка ОБЗОР
"""
from __future__ import annotations

from nicegui import ui
from sovushka.components.charts import _html, dot_html


def build_overview(tabs, is_admin: bool):
    """Строит содержимое вкладки ОБЗОР. Вызывать внутри with ui.tab_panel(tab_overview)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        ui.label("Л.Е.С. // АРХИТЕКТУРА").style(
            "font-size:1rem;font-weight:900;letter-spacing:1px;color:var(--text);"
        )

        # Модули системы — (name, tag, desc, status, tab_key)
        # tab_key — строка, потому что вкладки создаются в main_page, передаём через tabs
        modules = [
            ("С.О.В.У.Ш.К.А.", "CORE UI",  "Интерфейс чата и управления",  "ok",   "AI ЧАТ"),
            ("П.Р.О.Р.А.Б.",   "METRICS",  "Телеметрия узла",               "ok",   "П.Р.О.Р.А.Б."),
            ("С.А.М.О.В.А.Р.", "RAG",      "Векторная база Qdrant",          "ok",   "С.А.М.О.В.А.Р."),
            ("Т.О.С.К.А.",     "CRAG",     "Валидация ответов LLM",          "ok",   None),
            ("В.О.Л.К.",       "AUTH",     "RBAC, аутентификация",           "idle", None),
            ("К.О.Т.",         "TERM",     "Семантический фильтр",           "ok",   None),
            ("С.У.Х.А.Р.И.К.", "BACKUP",   "Снапшоты Qdrant",               "idle", None),
            ("Е.Ж.И.К.",       "MAIL",     "Обработка почты IMAP",           "warn", None),
        ]

        with ui.grid(columns=4).classes("w-full gap-3"):
            for name, tag, desc, status, tab_key in modules:
                with ui.card().classes("card-les cursor-pointer").style(
                    "border-left:3px solid var(--accent);" if tag == "CORE UI" else ""
                ) as card:
                    if tab_key:
                        card.on("click", lambda t=tab_key: tabs.set_value(t))

                    with ui.row().classes("items-center justify-between mb-2"):
                        ui.label(name).style("font-weight:900;font-size:.9rem;")
                        _html(f'<span class="tag-dim">{tag}</span>')

                    ui.label(desc).style("font-size:.7rem;color:var(--dim);margin-bottom:8px;")

                    with ui.row().classes("items-center gap-2"):
                        _html(dot_html(status))
                        color_map = {"ok": "var(--ok)", "warn": "var(--warn)", "idle": "var(--dim)"}
                        ui.label(
                            "LIVE" if status == "ok" else ("WAIT" if status == "warn" else "IDLE")
                        ).style(
                            f"font-size:.6rem;font-weight:700;color:{color_map.get(status,'var(--dim)')};"
                        )

        # Стек
        with ui.card().classes("card-les w-full"):
            ui.label("СТЕК").classes("section-title mb-3")
            stack_items = [
                ("Apple Silicon Host / 24 GB",                                   "HOST"),
                ("Docker: les-proxy :8050 · les-qdrant :6333",            "DOCKER"),
                ("MLX Host :8080 · Qwen3-14B + Qwen3-4B + bge-m3",       "MLX"),
                ("Ollama :11434 · qwen3:14b + bge-m3 (резерв)",           "OLLAMA"),
            ]
            for text, tag in stack_items:
                with ui.row().classes("items-center gap-3 py-1"):
                    _html(f'<span class="tag-acc">{tag}</span>')
                    ui.label(text).style("font-size:.75rem;color:var(--text);")
