"""Canonical NiceGUI primitives for Sovushka's migrated working surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import ui

from sovushka.uikit.states import feedback_state

BUTTON_VARIANTS = frozenset({"primary", "secondary", "quiet", "danger"})
PANEL_VARIANTS = frozenset({"plain", "raised", "inset"})


def add_classes(element: Any, *classes: str) -> Any:
    """Attach stable UI-kit classes without hiding the underlying NiceGUI element."""
    element.classes(" ".join(value for value in classes if value))
    return element


def status_badge(label: str, tone: str = "muted") -> Any:
    safe_tone = tone if tone in {"ok", "warn", "error", "blocked", "muted"} else "muted"
    return ui.label(label).classes(f"sov-ui-status sov-ui-status--{safe_tone}")


def action_button(
    label: str = "",
    *,
    icon: str | None = None,
    on_click: Callable[..., Any] | None = None,
    variant: str = "secondary",
    compact: bool = False,
    icon_only: bool = False,
    aria_label: str = "",
    classes: str = "",
) -> Any:
    """Render one of the four approved action variants.

    Page code may add a semantic hook through ``classes`` but must not restyle
    the visual role locally.
    """
    if variant not in BUTTON_VARIANTS:
        raise ValueError(f"Unknown action button variant: {variant}")
    if icon_only and not (aria_label or label):
        raise ValueError("Icon-only action buttons require an accessible label")
    modifiers = [f"sov-ui-button--{variant}"]
    if compact:
        modifiers.append("sov-ui-button--compact")
    if icon_only:
        modifiers.append("sov-ui-button--icon")
    props = ["flat", "no-caps"]
    accessible_name = aria_label or label
    if accessible_name:
        props.append(f'aria-label="{accessible_name}"')
    button = ui.button(
        "" if icon_only else label,
        icon=icon,
        color=None,
        on_click=on_click,
    ).props(" ".join(props)).classes(
        " ".join(["sov-ui-button", *modifiers, classes]).strip()
    )
    return button


def text_field(
    *,
    label: str = "",
    placeholder: str = "",
    aria_label: str = "",
    clearable: bool = False,
    classes: str = "",
) -> Any:
    """Render the canonical text field; page code owns only data and width."""
    props = ["outlined"]
    if clearable:
        props.append("clearable")
    accessible_name = aria_label or label or placeholder
    if accessible_name:
        props.append(f'aria-label="{accessible_name}"')
    return ui.input(label=label or None, placeholder=placeholder).props(
        " ".join(props)
    ).classes(" ".join(["sov-ui-input", classes]).strip())


def panel(*, variant: str = "plain", classes: str = "") -> Any:
    """Return a neutral section container from the approved surface set."""
    if variant not in PANEL_VARIANTS:
        raise ValueError(f"Unknown panel variant: {variant}")
    return ui.element("section").classes(
        " ".join(["sov-ui-panel", f"sov-ui-panel--{variant}", classes]).strip()
    )


def section_heading(title: str, detail: str = "") -> Any:
    """Render the shared title/detail hierarchy used inside panels."""
    with ui.column().classes("sov-ui-section-heading") as container:
        ui.label(title).classes("sov-ui-section-title")
        if detail:
            ui.label(detail).classes("sov-ui-section-detail")
    return container


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
