"""Single-screen editor for versioned chat profiles."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from nicegui import ui

from sovushka.state import api_delete, api_get, api_post, last_api_error_text
from sovushka.uikit.components import (
    action_button,
    panel,
    render_feedback_state,
    section_heading,
    select_field,
    status_badge,
    text_field,
)


MODE_ORDER = ("search", "agent", "estimator", "engineer")


def profile_text_budget(
    registry: dict[str, Any], kind: str, text: str
) -> dict[str, Any]:
    limits = registry.get("text_limits") or {}
    limit = int(limits.get(kind) or 0)
    current = len(str(text or "").strip())
    over_limit = limit <= 0 or current > limit
    tone = "error" if over_limit else "warn" if current == limit else "muted"
    return {
        "current": current,
        "limit": limit,
        "tone": tone,
        "over_limit": over_limit,
    }


def _profile(registry: dict[str, Any], mode: str) -> dict[str, Any]:
    return next(
        (item for item in registry.get("profiles") or [] if item.get("mode") == mode),
        {},
    )


def profile_revision_options(registry: dict[str, Any], mode: str) -> dict[str, str]:
    profile = _profile(registry, mode)
    active = str(profile.get("active_revision_id") or "")
    options: dict[str, str] = {}
    for revision in profile.get("revisions") or []:
        revision_id = str(revision.get("revision_id") or "")
        if not revision_id:
            continue
        parts = [str(revision.get("name") or revision_id)]
        if revision.get("is_factory"):
            parts.append("Base")
        if revision_id == active:
            parts.append("Активная")
        options[revision_id] = " · ".join(parts)
    return options


def _revision(registry: dict[str, Any], mode: str, revision_id: str) -> dict[str, Any]:
    return next(
        (
            item
            for item in (_profile(registry, mode).get("revisions") or [])
            if item.get("revision_id") == revision_id
        ),
        {},
    )


def build_profiles():
    """Build the Configuration → Profiles working surface."""

    state: dict[str, Any] = {
        "registry": {},
        "mode": "agent",
        "revision_id": "",
        "draft": {},
    }

    with ui.column().classes("sov-config-page"):
        with panel(variant="raised", classes="sov-config-hero"):
            section_heading(
                "Профили чата",
                "Промпт, скилл, инструменты и настройки сохраняются одной неизменяемой версией.",
            )
        workspace = ui.column().classes("w-full gap-3")

    def _draft_from_revision(revision: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": str(revision.get("name") or "Новая версия"),
            "source_revision_id": revision.get("revision_id"),
            "prompt_revision_id": revision.get("prompt_revision_id"),
            "skill_revision_id": revision.get("skill_revision_id"),
            "prompt_text": str(revision.get("prompt_text") or ""),
            "skill_text": str(revision.get("skill_text") or ""),
            "tools": list(revision.get("tools") or []),
            "model_policy": dict(revision.get("model_policy") or {}),
            "rag_policy": dict(revision.get("rag_policy") or {}),
        }

    async def _load(*, keep_mode: bool = True) -> None:
        data = await api_get("/api/profiles")
        if not isinstance(data, dict):
            workspace.clear()
            with workspace:
                render_feedback_state("error", detail=last_api_error_text("Профили недоступны"))
            return
        state["registry"] = data
        if not keep_mode or state["mode"] not in MODE_ORDER:
            state["mode"] = str(data.get("default_mode") or "agent")
        profile = _profile(data, state["mode"])
        options = profile_revision_options(data, state["mode"])
        if state["revision_id"] not in options:
            state["revision_id"] = str(profile.get("active_revision_id") or next(iter(options), ""))
        state["draft"] = _draft_from_revision(
            _revision(data, state["mode"], state["revision_id"])
        )
        _render()

    async def _select_mode(mode: str) -> None:
        state["mode"] = mode
        state["revision_id"] = ""
        await _load()

    async def _select_revision(revision_id: str) -> None:
        state["revision_id"] = str(revision_id or "")
        state["draft"] = _draft_from_revision(
            _revision(state["registry"], state["mode"], state["revision_id"])
        )
        _render()

    async def _activate() -> None:
        revision_id = state["revision_id"]
        result = await api_post(
            f"/api/profiles/{state['mode']}/activate/{quote(revision_id, safe='')}", {}
        )
        if isinstance(result, dict):
            ui.notify("Версия профиля назначена активной", type="positive")
            await _load()
        else:
            ui.notify(last_api_error_text("Версия не активирована"), type="negative")

    async def _delete_profile() -> None:
        revision = _revision(state["registry"], state["mode"], state["revision_id"])
        if revision.get("is_factory"):
            ui.notify("Заводскую Base-версию удалить нельзя", type="warning")
            return
        result = await api_delete(
            f"/api/profiles/profile/{quote(state['revision_id'], safe='')}"
        )
        if isinstance(result, dict):
            ui.notify("Версия удалена", type="positive")
            state["revision_id"] = ""
            await _load()
        else:
            ui.notify(last_api_error_text("Версия не удалена"), type="negative")

    async def _delete_text_revision(kind: str, item: dict[str, Any], dialog: Any) -> None:
        if item.get("is_factory"):
            ui.notify("Заводскую Base-редакцию удалить нельзя", type="warning")
            return
        result = await api_delete(
            f"/api/profiles/{kind}/{quote(str(item['revision_id']), safe='')}"
        )
        if not isinstance(result, dict):
            ui.notify(last_api_error_text("Редакция не удалена"), type="negative")
            return
        if state["draft"].get(f"{kind}_revision_id") == item["revision_id"]:
            state["draft"][f"{kind}_revision_id"] = None
        dialog.close()
        ui.notify("Редакция удалена", type="positive")
        await _load()

    async def _save() -> None:
        draft = state["draft"]
        registry = state["registry"]
        exceeded = [
            profile_text_budget(registry, kind, draft.get(f"{kind}_text") or "")
            for kind in ("prompt", "skill")
        ]
        if any(item["over_limit"] for item in exceeded):
            ui.notify("Превышен лимит текста; сократите промпт или скилл", type="warning")
            return
        prompt = await api_post(
            "/api/profiles/text-revisions",
            {
                "kind": "prompt",
                "name": f"{draft['name']} · промпт",
                "text": draft.get("prompt_text") or "",
                "source_revision_id": draft.get("prompt_revision_id"),
            },
        )
        if not isinstance(prompt, dict):
            ui.notify(last_api_error_text("Промпт не сохранён"), type="negative")
            return
        skill = await api_post(
            "/api/profiles/text-revisions",
            {
                "kind": "skill",
                "name": f"{draft['name']} · скилл",
                "text": draft.get("skill_text") or "",
                "source_revision_id": draft.get("skill_revision_id"),
            },
        )
        if not isinstance(skill, dict):
            ui.notify(last_api_error_text("Скилл не сохранён"), type="negative")
            return
        profile = await api_post(
            "/api/profiles/revisions",
            {
                "mode": state["mode"],
                "name": draft.get("name") or "Новая версия",
                "prompt_revision_id": prompt["revision_id"],
                "skill_revision_id": skill["revision_id"],
                "tools": draft.get("tools") or [],
                "model_policy": draft.get("model_policy") or {},
                "rag_policy": draft.get("rag_policy") or {},
                "source_revision_id": draft.get("source_revision_id"),
            },
        )
        if not isinstance(profile, dict):
            ui.notify(last_api_error_text("Версия профиля не сохранена"), type="negative")
            return
        state["revision_id"] = str(profile["revision_id"])
        ui.notify("Неизменяемая версия профиля сохранена", type="positive")
        await _load()

    def _choose_dialog(kind: str) -> Any:
        label = "промпт" if kind == "prompt" else "скилл"
        items = state["registry"].get(f"{kind}_revisions") or []
        dialog = ui.dialog()
        with dialog, ui.card().classes("sov-ui-panel sov-ui-panel--raised w-full max-w-3xl"):
            section_heading(f"Выбрать {label}", "Base и сохранённые пользовательские редакции.")
            with ui.column().classes("w-full gap-2"):
                for item in items:
                    with panel(variant="inset", classes="w-full"):
                        with ui.row().classes("w-full items-center justify-between gap-2"):
                            with ui.column().classes("min-w-0 gap-1"):
                                ui.label(str(item.get("name") or "Редакция")).classes(
                                    "sov-ui-section-title"
                                )
                                if item.get("is_factory"):
                                    status_badge("Base", "muted")

                            async def _select(item=item, dialog=dialog) -> None:
                                state["draft"][f"{kind}_revision_id"] = item["revision_id"]
                                state["draft"][f"{kind}_text"] = item["text"]
                                dialog.close()
                                _render()

                            with ui.row().classes("items-center gap-1"):
                                action_button(
                                    "Выбрать",
                                    icon="o_check",
                                    on_click=_select,
                                    variant="secondary",
                                    compact=True,
                                )
                                if not item.get("is_factory"):
                                    action_button(
                                        "Удалить редакцию",
                                        icon="o_delete",
                                        on_click=lambda _event, kind=kind, item=item, dialog=dialog: asyncio.create_task(
                                            _delete_text_revision(kind, item, dialog)
                                        ),
                                        variant="danger",
                                        compact=True,
                                    )
            action_button("Закрыть", on_click=dialog.close, variant="quiet", compact=True)
        return dialog

    def _render() -> None:
        workspace.clear()
        registry = state["registry"]
        mode = state["mode"]
        profile = _profile(registry, mode)
        revision = _revision(registry, mode, state["revision_id"])
        draft = state["draft"]
        text_limits = registry.get("text_limits") or {}
        controls: dict[str, Any] = {"save": None}

        def _update_budget(kind: str, badge: Any) -> None:
            budget = profile_text_budget(registry, kind, draft.get(f"{kind}_text") or "")
            suffix = " · Превышен лимит" if budget["over_limit"] else ""
            badge.set_text(f"{budget['current']} / {budget['limit']}{suffix}")
            badge.classes(
                remove="sov-ui-status--muted sov-ui-status--warn sov-ui-status--error",
                add=f"sov-ui-status--{budget['tone']}",
            )
            save_button = controls.get("save")
            if save_button is not None:
                prompt_over = profile_text_budget(
                    registry, "prompt", draft.get("prompt_text") or ""
                )["over_limit"]
                skill_over = profile_text_budget(
                    registry, "skill", draft.get("skill_text") or ""
                )["over_limit"]
                if prompt_over or skill_over or not text_limits:
                    save_button.disable()
                else:
                    save_button.enable()
        with workspace:
            with panel(variant="plain", classes="w-full"):
                section_heading("Режим", "Каждая кнопка — отдельный заводской профиль.")
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    for item in registry.get("profiles") or []:
                        selected = item.get("mode") == mode
                        action_button(
                            str(item.get("label") or item.get("mode")),
                            icon="o_check_circle" if selected else "o_radio_button_unchecked",
                            on_click=lambda _event, selected_mode=item.get("mode"): asyncio.create_task(
                                _select_mode(str(selected_mode))
                            ),
                            variant="primary" if selected else "secondary",
                        )

            with panel(variant="plain", classes="w-full"):
                with ui.row().classes("w-full items-start justify-between gap-3 flex-wrap"):
                    section_heading("Версия профиля", "Base неизменяема; сохранение создаёт новую редакцию.")
                    if revision.get("is_factory"):
                        status_badge("Base", "muted")
                    if state["revision_id"] == profile.get("active_revision_id"):
                        status_badge("Активная", "ok")
                version_select = select_field(
                    profile_revision_options(registry, mode),
                    value=state["revision_id"],
                    label="Сохранённая версия",
                    classes="w-full",
                )
                version_select.on_value_change(
                    lambda event: asyncio.create_task(_select_revision(str(event.value or "")))
                )
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    action_button(
                        "Сделать активной",
                        icon="o_check_circle",
                        on_click=_activate,
                        variant="primary",
                    )

                    def _copy() -> None:
                        draft["name"] = str(draft.get("name") or "Версия") + " · копия"
                        state["revision_id"] = ""
                        _render()

                    action_button("Создать копию", icon="o_content_copy", on_click=_copy, variant="secondary")

                    def _blank() -> None:
                        state["revision_id"] = ""
                        state["draft"] = {
                            "name": "Новая версия",
                            "source_revision_id": None,
                            "prompt_revision_id": None,
                            "skill_revision_id": None,
                            "prompt_text": "",
                            "skill_text": "",
                            "tools": [],
                            "model_policy": {"temperature": 0.1},
                            "rag_policy": {"grounded": True, "iterative": True},
                        }
                        _render()

                    action_button("Создать с нуля", icon="o_add", on_click=_blank, variant="secondary")
                    action_button("Удалить", icon="o_delete", on_click=_delete_profile, variant="danger")

            with panel(variant="plain", classes="w-full"):
                section_heading("Содержимое версии", "Промпт и скилл выбираются внутри профиля.")
                name_input = text_field(label="Название версии", value=draft.get("name") or "", classes="w-full")
                name_input.on_value_change(lambda event: draft.__setitem__("name", str(event.value or "")))

                with panel(variant="inset", classes="w-full"):
                    with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                        section_heading("Промпт", "Системная роль и правила ответа.")
                        prompt_counter = status_badge("", "muted")
                        prompt_dialog = _choose_dialog("prompt")
                        action_button(
                            "Выбрать промпт",
                            icon="o_library_books",
                            on_click=prompt_dialog.open,
                            variant="secondary",
                        )
                    prompt_preview = ui.markdown(draft.get("prompt_text") or "").classes("w-full")

                    def _prompt_changed(event: Any) -> None:
                        value = str(event.value or "")
                        draft["prompt_text"] = value
                        prompt_preview.set_content(value)
                        _update_budget("prompt", prompt_counter)

                    prompt_editor = ui.codemirror(
                        value=draft.get("prompt_text") or "",
                        language="Markdown",
                        line_wrapping=True,
                        on_change=_prompt_changed,
                    ).classes("w-full")

                with panel(variant="inset", classes="w-full"):
                    with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                        section_heading("Скилл", "Рабочая методика модели в Markdown.")
                        skill_counter = status_badge("", "muted")
                        skill_dialog = _choose_dialog("skill")
                        action_button(
                            "Выбрать скилл",
                            icon="o_school",
                            on_click=skill_dialog.open,
                            variant="secondary",
                        )
                    skill_preview = ui.markdown(draft.get("skill_text") or "").classes("w-full")

                    def _skill_changed(event: Any) -> None:
                        value = str(event.value or "")
                        draft["skill_text"] = value
                        skill_preview.set_content(value)
                        _update_budget("skill", skill_counter)

                    skill_editor = ui.codemirror(
                        value=draft.get("skill_text") or "",
                        language="Markdown",
                        line_wrapping=True,
                        on_change=_skill_changed,
                    ).classes("w-full")

            with panel(variant="plain", classes="w-full"):
                section_heading("Инструменты", "Модель увидит только отмеченные зарегистрированные тулзы.")
                with ui.column().classes("w-full gap-1"):
                    for tool in registry.get("tools") or []:
                        tool_name = str(tool.get("name") or "")
                        checkbox = ui.checkbox(
                            str(tool.get("title") or tool_name),
                            value=tool_name in set(draft.get("tools") or []),
                        ).props(f'aria-label="Инструмент {tool_name}"')

                        def _toggle(event, tool_name=tool_name) -> None:
                            selected = set(draft.get("tools") or [])
                            if event.value:
                                selected.add(tool_name)
                            else:
                                selected.discard(tool_name)
                            draft["tools"] = sorted(selected)

                        checkbox.on_value_change(_toggle)

            with panel(variant="plain", classes="w-full"):
                section_heading(
                    "Настройки модели и RAG",
                    "Параметры входят в неизменяемый snapshot версии профиля.",
                )
                temperature = ui.number(
                    "Температура модели",
                    value=float((draft.get("model_policy") or {}).get("temperature", 0.1)),
                    min=0.0,
                    max=2.0,
                    step=0.1,
                ).props("outlined dense").classes("w-full")
                temperature.on_value_change(
                    lambda event: draft.setdefault("model_policy", {}).__setitem__(
                        "temperature", float(event.value or 0.0)
                    )
                )
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    grounded = ui.switch(
                        "Только по источникам",
                        value=bool((draft.get("rag_policy") or {}).get("grounded", True)),
                    )
                    iterative = ui.switch(
                        "Итеративный поиск",
                        value=bool((draft.get("rag_policy") or {}).get("iterative", True)),
                    )
                    citations = ui.switch(
                        "Обязательные ссылки",
                        value=bool((draft.get("rag_policy") or {}).get("require_citations", False)),
                    )
                grounded.on_value_change(
                    lambda event: draft.setdefault("rag_policy", {}).__setitem__("grounded", bool(event.value))
                )
                iterative.on_value_change(
                    lambda event: draft.setdefault("rag_policy", {}).__setitem__("iterative", bool(event.value))
                )
                citations.on_value_change(
                    lambda event: draft.setdefault("rag_policy", {}).__setitem__(
                        "require_citations", bool(event.value)
                    )
                )
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    retrieval_candidate_k = ui.number(
                        "Кандидаты RRF",
                        value=int((draft.get("rag_policy") or {}).get("retrieval_candidate_k", 64)),
                        min=1,
                        max=512,
                        step=1,
                    ).props("outlined dense").classes("min-w-48 flex-1")
                    document_diversity_k = ui.number(
                        "Фрагментов на документ",
                        value=int((draft.get("rag_policy") or {}).get("document_diversity_k", 2)),
                        min=1,
                        max=32,
                        step=1,
                    ).props("outlined dense").classes("min-w-48 flex-1")
                    model_evidence_k = ui.number(
                        "Evidence модели",
                        value=int((draft.get("rag_policy") or {}).get("model_evidence_k", 6)),
                        min=1,
                        max=64,
                        step=1,
                    ).props("outlined dense").classes("min-w-48 flex-1")
                retrieval_candidate_k.on_value_change(
                    lambda event: draft.setdefault("rag_policy", {}).__setitem__(
                        "retrieval_candidate_k", int(event.value or 64)
                    )
                )
                document_diversity_k.on_value_change(
                    lambda event: draft.setdefault("rag_policy", {}).__setitem__(
                        "document_diversity_k", int(event.value or 2)
                    )
                )
                model_evidence_k.on_value_change(
                    lambda event: draft.setdefault("rag_policy", {}).__setitem__(
                        "model_evidence_k", int(event.value or 6)
                    )
                )

            with ui.row().classes("w-full justify-end"):
                save_button = action_button(
                    "Сохранить версию",
                    icon="o_save",
                    on_click=_save,
                    variant="primary",
                )
                controls["save"] = save_button
                _update_budget("prompt", prompt_counter)
                _update_budget("skill", skill_counter)

    asyncio.create_task(_load(keep_mode=False))
