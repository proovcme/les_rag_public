"""Small NiceGUI primitives for P0-migrated Sovushka surfaces."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from sovushka.uikit.states import feedback_state


def add_classes(element: Any, *classes: str) -> Any:
    """Attach stable UI-kit classes without hiding the underlying NiceGUI element."""
    element.classes(" ".join(value for value in classes if value))
    return element


def status_badge(label: str, tone: str = "muted") -> Any:
    safe_tone = tone if tone in {"ok", "warn", "error", "blocked", "muted"} else "muted"
    return ui.label(label).classes(f"sov-ui-status sov-ui-status--{safe_tone}")


def acronym_identity(
    acronym: str,
    expansion: str,
    *,
    icon: str = "",
    compact: bool = False,
) -> Any:
    """Render one consistent product/module identity with optional expansion."""
    modifier = " sov-acronym-identity--compact" if compact else ""
    with ui.row().classes(f"sov-acronym-identity{modifier}") as container:
        if icon:
            ui.icon(icon).classes("sov-acronym-mark").props("aria-hidden=true")
        with ui.column().classes("sov-acronym-copy"):
            ui.label(acronym).classes("sov-acronym-title")
            ui.label(expansion).classes("sov-acronym-expansion")
    container.tooltip(expansion)
    return container


def render_feedback_state(
    kind: str,
    *,
    error_code: str = "",
    detail: str = "",
) -> Any:
    state = feedback_state(kind, error_code=error_code, detail=detail)
    with ui.element("section").classes(
        f"sov-ui-feedback sov-ui-feedback--{state['kind']}"
    ).props('role="status" aria-live="polite"') as container:
        ui.label(state["title"]).classes("sov-ui-feedback__title")
        ui.label(state["detail"]).classes("sov-ui-feedback__detail")
        if state["error_code"]:
            ui.label(state["error_code"]).classes(
                "sov-ui-feedback__detail sov-ui-source-chip"
            )
    return container
