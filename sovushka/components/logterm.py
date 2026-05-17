"""
С.О.В.У.Ш.К.А. v5.0 — Терминал логов (footer)
"""
from __future__ import annotations

from nicegui import ui
import sovushka.state as _state


def build_log_terminal():
    """Строит footer с логом. Устанавливает state.log_element."""
    ui.separator().style("border-color:var(--border);")
    with ui.element("footer").style(
        "background:#000;font-family:var(--font);font-size:.7rem;height:120px;overflow-y:auto;"
        "border-top:1px solid var(--border);flex-shrink:0;width:100%;padding:8px 18px;"
    ):
        _state.log_element = ui.log(max_lines=100).classes("w-full h-full").style(
            "background:transparent;color:var(--ok);font-family:var(--font);font-size:.7rem;border:none;"
        )
        _state.add_log("[С.О.В.У.Ш.К.А.] v5.0 NiceGUI Edition. Инициализация...")
