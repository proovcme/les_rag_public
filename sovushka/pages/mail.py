"""Read-only E.ZH.I.K. mailbox browser."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from nicegui import ui

from sovushka.state import api_get, api_post, last_api_error_text


def build_mail() -> None:
    state = {"accounts": [], "folders": [], "account": None, "messages": [], "detail": None}
    refs: dict[str, object] = {}

    def notify_error(default: str) -> None:
        ui.notify(last_api_error_text(default), type="negative")

    async def load_accounts() -> None:
        payload = await api_get("/api/mail/accounts")
        if not isinstance(payload, dict):
            notify_error("Не удалось загрузить почтовые аккаунты")
            return
        state["accounts"] = payload.get("accounts") or []
        state["folders"] = payload.get("folders") or []
        selected = state.get("account") or {}
        if selected:
            state["account"] = next(
                (item for item in state["accounts"] if item.get("id") == selected.get("id")), None
            )
        if not state.get("account") and state["accounts"]:
            state["account"] = state["accounts"][0]
        render_accounts()
        await load_messages()

    async def select_account(account: dict) -> None:
        state["account"] = account
        state["detail"] = None
        render_accounts()
        render_detail()
        await load_messages()

    async def load_messages() -> None:
        account = state.get("account") or {}
        if not account:
            state["messages"] = []
            render_messages()
            return
        search = str(getattr(refs.get("search"), "value", "") or "").strip()
        path = f"/api/mail/messages?account_id={quote(str(account['id']))}&limit=500"
        if search:
            path += f"&q={quote(search)}"
        payload = await api_get(path)
        state["messages"] = (payload or {}).get("messages") or [] if isinstance(payload, dict) else []
        render_messages()

    async def sync_account(account: dict, mode: str = "incremental") -> None:
        if account.get("kind") != "imap":
            ui.notify("Outlook синхронизируется фоновой задачей Windows", type="info")
            return
        ui.notify("Синхронизация запущена", type="info")
        result = await api_post(
            f"/api/mail/accounts/{account['id']}/sync",
            {"mode": mode, "max_messages": 200, "parse": True},
        )
        if result:
            ui.notify(f"Получено писем: {result.get('files', 0)}", type="positive")
            await load_accounts()
        else:
            notify_error("Синхронизация не удалась")

    async def show_message(message: dict) -> None:
        payload = await api_get(f"/api/mail/messages/{message['id']}")
        if not isinstance(payload, dict):
            notify_error("Не удалось открыть локальный снимок письма")
            return
        state["detail"] = payload
        render_detail()

    async def open_outlook(message_id: str) -> None:
        result = await api_post(f"/api/mail/messages/{message_id}/open", {})
        if result:
            ui.notify("Передано в Outlook", type="positive")
        else:
            notify_error("Не удалось открыть оригинал в Outlook")

    def open_add_account_dialog() -> None:
        with ui.dialog() as dialog, ui.card().style("min-width:520px;padding:20px;"):
            ui.label("Подключить IMAP-ящик").style("font-size:1rem;font-weight:800;")
            provider = ui.select(
                {"yandex": "Яндекс", "custom": "Другой IMAP"}, value="yandex", label="Провайдер"
            ).classes("w-full")
            label = ui.input("Название ящика").classes("w-full")
            login = ui.input("Логин / адрес почты").classes("w-full")
            password = ui.input("Пароль приложения", password=True, password_toggle_button=True).classes("w-full")
            host = ui.input("IMAP-сервер", value="imap.yandex.ru").classes("w-full")
            port = ui.number("Порт", value=993, min=1, max=65535).classes("w-full")
            ui.label("Пароль сохраняется в Windows Credential Manager и не возвращается API.").style(
                "font-size:.72rem;color:var(--dim);"
            )

            async def create() -> None:
                payload = {
                    "kind": "imap",
                    "provider": provider.value,
                    "label": label.value or login.value,
                    "login": login.value,
                    "password": password.value,
                    "host": host.value,
                    "port": int(port.value or 993),
                    "ssl": True,
                    "folders": ["*"],
                }
                result = await api_post("/api/mail/accounts", payload)
                if not result:
                    notify_error("Не удалось подключить ящик")
                    return
                password.value = ""
                dialog.close()
                ui.notify("Ящик добавлен; создан отдельный P0-датасет", type="positive")
                await load_accounts()

            with ui.row().classes("justify-end w-full"):
                ui.button("Отмена", on_click=dialog.close).props("flat no-caps")
                ui.button("Подключить", on_click=create).props("no-caps")
        dialog.open()

    def render_accounts() -> None:
        panel = refs.get("accounts")
        if panel is None:
            return
        panel.clear()
        with panel:
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("Ящики").style("font-size:.82rem;font-weight:800;")
                ui.button(icon="o_add", on_click=open_add_account_dialog).props("flat dense round").tooltip(
                    "Подключить IMAP"
                )
            if not state["accounts"]:
                ui.label("Подключите IMAP или запустите Outlook-sidecar на Legion.").style(
                    "font-size:.72rem;color:var(--dim);padding:12px 0;"
                )
            selected_id = (state.get("account") or {}).get("id")
            for account in state["accounts"]:
                active = account.get("id") == selected_id
                with ui.card().classes("w-full cursor-pointer").style(
                    "padding:10px;border:1px solid %s;background:var(--bg);" %
                    ("var(--accent)" if active else "var(--border)")
                ).on("click", lambda _event, item=account: asyncio.create_task(select_account(item))):
                    ui.label(account.get("label") or "Почта").style("font-size:.75rem;font-weight:700;")
                    ui.label(account.get("dataset_name") or "").style(
                        "font-size:.58rem;color:var(--dim);overflow-wrap:anywhere;"
                    )
                    ui.label(
                        f"{account.get('kind')} · {account.get('sync_state') or 'idle'}"
                    ).style("font-size:.6rem;color:var(--dim);")
            account = state.get("account") or {}
            if account:
                ui.separator()
                ui.label("Папки").style("font-size:.68rem;font-weight:700;")
                for folder in state["folders"]:
                    if folder.get("account_id") == account.get("id"):
                        ui.label(folder.get("path") or "—").style("font-size:.64rem;color:var(--dim);")

    def render_messages() -> None:
        panel = refs.get("messages")
        if panel is None:
            return
        panel.clear()
        with panel:
            account = state.get("account") or {}
            with ui.row().classes("items-center justify-between w-full"):
                ui.label(account.get("label") or "Переписка").style("font-size:.82rem;font-weight:800;")
                ui.button(
                    "Синхронизировать",
                    icon="o_sync",
                    on_click=lambda: asyncio.create_task(sync_account(account)),
                ).props("flat dense no-caps").style("font-size:.65rem;")
            if not state["messages"]:
                ui.label("Писем пока нет.").style("font-size:.72rem;color:var(--dim);padding:20px 0;")
            threads: dict[str, list[dict]] = {}
            for message in state["messages"]:
                threads.setdefault(message.get("thread_key") or message["id"], []).append(message)
            for messages in threads.values():
                latest = messages[0]
                with ui.card().classes("w-full cursor-pointer").style(
                    "padding:11px;border:1px solid var(--border);background:var(--bg);"
                ).on("click", lambda _event, item=latest: asyncio.create_task(show_message(item))):
                    with ui.row().classes("items-center justify-between w-full no-wrap"):
                        ui.label(latest.get("subject") or "(без темы)").style(
                            "font-size:.74rem;font-weight:700;overflow:hidden;text-overflow:ellipsis;"
                        )
                        if len(messages) > 1:
                            ui.badge(str(len(messages))).props("outline")
                    ui.label(latest.get("sender") or "").style("font-size:.63rem;color:var(--dim);")
                    ui.label(latest.get("received_at") or latest.get("sent_at") or "").style(
                        "font-size:.58rem;color:var(--dim);"
                    )

    def render_detail() -> None:
        panel = refs.get("detail")
        if panel is None:
            return
        panel.clear()
        with panel:
            detail = state.get("detail") or {}
            if not detail:
                ui.label("Выберите письмо").style("font-size:.78rem;color:var(--dim);padding:24px;")
                return
            message = detail.get("message") or {}
            profile = detail.get("profile") or {}
            account = detail.get("account") or {}
            ui.label(profile.get("mail_subject") or message.get("subject") or "(без темы)").style(
                "font-size:.95rem;font-weight:800;"
            )
            ui.label(f"От: {profile.get('mail_from') or message.get('sender') or '—'}").style("font-size:.68rem;")
            ui.label("Кому: " + ", ".join(profile.get("mail_to") or [])).style("font-size:.65rem;color:var(--dim);")
            with ui.row().classes("gap-2"):
                if message.get("source_kind") == "outlook_classic":
                    ui.button(
                        "Открыть в Outlook",
                        icon="o_open_in_new",
                        on_click=lambda: asyncio.create_task(open_outlook(message["id"])),
                    ).props("flat dense no-caps")
                ui.button(
                    "Спросить в LES",
                    icon="o_forum",
                    on_click=lambda: ui.navigate.to(f"/classic?scope=ds:{account['dataset_id']}&tab=chat"),
                ).props("flat dense no-caps")
            ui.separator()
            ui.label(detail.get("body") or "(тело не извлечено)").style(
                "font-size:.72rem;white-space:pre-wrap;line-height:1.55;"
            )
            ui.label("Вложения").style("font-size:.7rem;font-weight:800;margin-top:14px;")
            for attachment in detail.get("attachments") or []:
                ui.label(
                    f"{attachment.get('filename')} · {attachment.get('extraction')} · {attachment.get('size_bytes', 0)} Б"
                ).style("font-size:.64rem;color:var(--dim);")
            ui.separator()
            ui.label(
                f"Источник: {message.get('source_kind')} · {account.get('dataset_name')} · {message.get('index_status')}"
            ).style("font-size:.6rem;color:var(--dim);overflow-wrap:anywhere;")
            for location in message.get("locations") or []:
                ui.label(f"Папка: {location.get('folder_path')}").style("font-size:.6rem;color:var(--dim);")

    with ui.column().classes("w-full h-full gap-0").style("padding:14px;background:var(--bg);"):
        with ui.row().classes("items-center w-full gap-2").style("margin-bottom:10px;"):
            refs["search"] = ui.input("Поиск по теме и участникам").props("dense outlined clearable").style(
                "flex:1;"
            )
            refs["search"].on("keydown.enter", lambda: asyncio.create_task(load_messages()))
            ui.button(icon="o_search", on_click=lambda: asyncio.create_task(load_messages())).props("flat round")
        with ui.row().classes("w-full flex-1 no-wrap gap-3").style("min-height:calc(100vh - 150px);"):
            refs["accounts"] = ui.column().classes("gap-2").style("width:250px;min-width:220px;overflow:auto;")
            refs["messages"] = ui.column().classes("gap-2").style(
                "width:360px;min-width:300px;overflow:auto;border-left:1px solid var(--border);padding-left:12px;"
            )
            refs["detail"] = ui.column().classes("gap-2 flex-1").style(
                "overflow:auto;border-left:1px solid var(--border);padding-left:16px;"
            )

    render_accounts()
    render_messages()
    render_detail()
    asyncio.create_task(load_accounts())
