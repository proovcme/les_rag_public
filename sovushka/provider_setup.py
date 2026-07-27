"""First-run provider chooser shown immediately after access-key login."""
from __future__ import annotations

from fastapi import Request
from nicegui import ui
from starlette.responses import RedirectResponse

from backend.auth import get_role, is_authenticated
from sovushka.provider_session import provider_public_profile, save_provider_config
from sovushka.trust import trusted_role_for_request


_PROVIDER_SETUP_CSS = """
<style>
* { box-sizing: border-box; }
html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
body { background:#08090b !important; color:#e2e8f0; }
html, body, #app, .q-layout, .q-page-container, .q-page, .nicegui-content {
  width:100% !important; min-width:100% !important;
}
.provider-shell {
  min-height:100vh; width:100%; padding:32px 18px; display:flex;
  align-items:center; justify-content:center; background:
  radial-gradient(circle at 50% 0%, rgba(59,130,246,.11), transparent 38%), #08090b;
}
.provider-card {
  width:min(760px, 100%); padding:32px; border:1px solid #1e2d3d; border-radius:18px;
  background:#0d1117; box-shadow:0 24px 70px rgba(0,0,0,.38);
}
.provider-kicker { color:#3b82f6; font:800 .68rem/1.2 'Courier New',monospace; letter-spacing:.14em; }
.provider-title { margin:8px 0 6px; font-size:clamp(1.5rem,4vw,2.25rem); font-weight:850; letter-spacing:-.035em; text-wrap:balance; }
.provider-copy { max-width:620px; color:#94a3b8; font-size:.9rem; line-height:1.55; text-wrap:pretty; }
.provider-grid { width:100%; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:24px; }
.provider-choice {
  min-height:138px; padding:18px; border:1px solid #263548; border-radius:14px;
  background:#0a0e14; cursor:pointer; transition:transform .16s ease,border-color .16s ease,background-color .16s ease,box-shadow .16s ease;
}
.provider-choice:hover { border-color:#3b82f6; background:#0d1420; box-shadow:0 10px 30px rgba(0,0,0,.22); }
.provider-choice:active { transform:scale(.98); }
.provider-choice.selected { border-color:#3b82f6; background:rgba(59,130,246,.09); box-shadow:0 0 0 1px rgba(59,130,246,.18); }
.provider-choice-title { font-size:1rem; font-weight:800; margin-bottom:6px; }
.provider-choice-copy { color:#7f8da1; font-size:.76rem; line-height:1.5; }
.provider-badge { display:inline-flex; margin-top:12px; padding:4px 8px; border-radius:999px; background:#131c29; color:#8eaccf; font:700 .62rem/1.2 'Courier New',monospace; }
.provider-fields { width:100%; margin-top:14px; padding:18px; border:1px solid #1e2d3d; border-radius:14px; background:#090d12; }
.provider-fields .q-field { width:100%; }
.provider-note { margin-top:14px; color:#64748b; font-size:.7rem; line-height:1.5; }
.provider-error { min-height:20px; margin-top:8px; color:#f87171; font-size:.72rem; }
.provider-action { min-height:44px !important; border-radius:10px !important; font-weight:800 !important; letter-spacing:.02em; transition:transform .16s ease,filter .16s ease !important; }
.provider-action:active { transform:scale(.96); }
.nicegui-content { padding:0 !important; max-width:none !important; }
@media (max-width:640px) {
  .provider-shell { align-items:flex-start; padding:18px 12px; }
  .provider-card { padding:22px 16px; border-radius:16px; }
  .provider-grid { grid-template-columns:1fr; }
  .provider-choice { min-height:116px; }
}
</style>
"""


def _chat_target() -> str:
    return "/les" if get_role() == "admin" else "/classic"


def register_provider_setup_page() -> None:
    @ui.page("/provider-setup")
    async def provider_setup_page(request: Request):
        trusted_role = trusted_role_for_request(request)
        if trusted_role:
            return RedirectResponse("/les" if trusted_role == "admin" else "/classic")
        if not is_authenticated():
            return RedirectResponse("/login")

        ui.add_head_html(_PROVIDER_SETUP_CSS)
        ui.query("body").style("background:#08090b;margin:0;")

        previous = provider_public_profile()
        selected = {"mode": "cloud" if previous.get("provider") in {"openrouter", "openai"} else "local"}

        with ui.element("div").classes("provider-shell"):
            with ui.element("section").classes("provider-card"):
                ui.label("Л.Е.С. · ШАГ 2 ИЗ 2").classes("provider-kicker")
                ui.label("Какой моделью отвечать?").classes("provider-title")
                ui.label(
                    "Локальная модель работает на сервере Л.Е.С. и отвечает медленнее. "
                    "Облачная — быстрее, но использует ваш собственный API-ключ."
                ).classes("provider-copy")

                with ui.element("div").classes("provider-grid"):
                    with ui.element("button").props('type="button" aria-label="Выбрать локальную модель"').classes(
                        "provider-choice"
                    ) as local_choice:
                        ui.label("Локальная модель").classes("provider-choice-title")
                        ui.label("Без внешнего API-ключа. Приватнее, но заметно медленнее.").classes("provider-choice-copy")
                        ui.label("МЕДЛЕННО · ЛОКАЛЬНО").classes("provider-badge")
                    with ui.element("button").props('type="button" aria-label="Выбрать облачную модель"').classes(
                        "provider-choice"
                    ) as cloud_choice:
                        ui.label("Облачная модель").classes("provider-choice-title")
                        ui.label("OpenRouter или OpenAI с вашим ключом и выбранной моделью.").classes("provider-choice-copy")
                        ui.label("БЫСТРЕЕ · BYOK").classes("provider-badge")

                with ui.element("div").classes("provider-fields") as cloud_fields:
                    provider = ui.select(
                        {"openrouter": "OpenRouter", "openai": "OpenAI"},
                        value=previous.get("provider") if previous.get("provider") in {"openrouter", "openai"} else "openrouter",
                        label="Провайдер",
                    ).props("outlined dark options-dense")
                    model = ui.input(
                        "Модель",
                        value=previous.get("model") or "openai/gpt-5.4",
                        placeholder="openai/gpt-5.4",
                    ).props("outlined dark autocomplete=off")
                    api_key = ui.input(
                        "API-ключ",
                        password=True,
                        password_toggle_button=True,
                        placeholder="Ключ не сохраняется на диске",
                    ).props("outlined dark autocomplete=new-password")
                    ui.label(
                        "Ключ хранится только в памяти текущего процесса до 12 часов. "
                        "Л.Е.С. не показывает его повторно и не записывает в общие настройки. "
                        "Защищённые данные по политике безопасности всё равно обрабатываются локально."
                    ).classes("provider-note")

                error = ui.label("").classes("provider-error")

                def render_selection() -> None:
                    local_selected = selected["mode"] == "local"
                    local_choice.classes(replace="provider-choice selected" if local_selected else "provider-choice")
                    cloud_choice.classes(replace="provider-choice selected" if not local_selected else "provider-choice")
                    cloud_fields.set_visibility(not local_selected)

                def choose(mode: str) -> None:
                    selected["mode"] = mode
                    error.set_text("")
                    render_selection()

                def provider_changed(event) -> None:
                    current = str(event.value or "")
                    if current == "openai" and (not model.value or str(model.value).startswith("openai/")):
                        model.value = "gpt-5.4"
                    elif current == "openrouter" and (not model.value or str(model.value) == "gpt-5.4"):
                        model.value = "openai/gpt-5.4"

                async def continue_to_chat() -> None:
                    try:
                        if selected["mode"] == "local":
                            save_provider_config("mlx")
                        else:
                            save_provider_config(str(provider.value or ""), str(model.value or ""), str(api_key.value or ""))
                    except ValueError as exc:
                        error.set_text(str(exc))
                        return
                    api_key.value = ""
                    ui.navigate.to(_chat_target())

                local_choice.on("click", lambda: choose("local"))
                cloud_choice.on("click", lambda: choose("cloud"))
                provider.on_value_change(provider_changed)
                render_selection()
                ui.button("Продолжить в чат", on_click=continue_to_chat).props(
                    "unelevated color=primary no-caps"
                ).classes("provider-action w-full")
