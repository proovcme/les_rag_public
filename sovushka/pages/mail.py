"""Read-only E.ZH.I.K. mailbox browser."""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import quote, urlencode

from nicegui import ui

from sovushka.state import api_get, api_post, last_api_error_text
from sovushka.uikit.components import (
    acronym_identity,
    action_button,
    panel,
    render_feedback_state,
    section_heading,
    status_badge,
    text_field,
)


def build_mail() -> None:
    state = {
        "accounts": [],
        "folders": [],
        "account": None,
        "messages": [],
        "detail": None,
        "status": {},
        "collecting": False,
    }
    refs: dict[str, object] = {}

    def notify_error(default: str) -> None:
        ui.notify(last_api_error_text(default), type="negative")

    async def load_accounts() -> None:
        payload, status = await asyncio.gather(
            api_get("/api/mail/accounts"),
            api_get("/api/mail/status"),
        )
        state["status"] = status if isinstance(status, dict) else {}
        render_status()
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
        render_status()
        await load_messages()

    async def select_account(account: dict) -> None:
        state["account"] = account
        state["detail"] = None
        render_accounts()
        render_status()
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

    def _message_chat_url(account: dict, message: dict) -> str:
        subject = str(message.get("subject") or "письмо").strip()
        params = {
            "scope": f"ds:{account['dataset_id']}",
            "tab": "chat",
            "question": (
                f"Прочитай письмо «{subject}» и доступные вложения. "
                "Ответь по их содержанию и явно укажи, чего не удалось извлечь."
            ),
        }
        relative_path = str(message.get("relative_path") or "").strip()
        if relative_path:
            params["target_file"] = relative_path
        return "/classic?" + urlencode(params)

    async def collect_more() -> None:
        account = state.get("account") or {}
        if not account:
            ui.notify("Сначала выберите почтовый ящик", type="warning")
            return
        state["collecting"] = True
        render_status()
        if account.get("kind") == "imap":
            result = await api_post(
                f"/api/mail/accounts/{account['id']}/sync",
                {"mode": "incremental", "max_messages": 200, "parse": True},
            )
        else:
            result = await api_post("/api/mail/collector/run", {})
        state["collecting"] = False
        if not isinstance(result, dict):
            notify_error("Не удалось забрать новые письма")
            render_status()
            return
        ui.notify("Сбор новых писем запущен", type="positive")
        await load_accounts()

    def render_status() -> None:
        panel = refs.get("status")
        if panel is None:
            return
        panel.clear()
        status = state.get("status") if isinstance(state.get("status"), dict) else {}
        summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
        account = state.get("account") or {}
        last_sync = str(account.get("last_sync") or "ещё не запускался")
        with panel:
            with ui.element("section").classes("sov-mail-status-strip").props(
                'aria-label="Состояние почтового индекса"'
            ):
                with ui.column().classes("gap-0 sov-mail-status-copy"):
                    ui.label(account.get("label") or "Почтовый индекс").classes("sov-mail-status-title")
                    ui.label(
                        f"Последний сбор: {last_sync} · в обработке: {int(summary.get('spool_pending') or 0)}"
                    ).classes("sov-mail-status-note")
                for label, value, tone in (
                    ("В индексе", summary.get("indexed") or 0, "ok"),
                    ("Ожидает", summary.get("pending") or 0, "muted"),
                    ("Ошибки", summary.get("errors") or 0, "warn"),
                ):
                    with ui.column().classes(
                        f"gap-0 sov-mail-status-metric sov-mail-status-metric--{tone}"
                    ):
                        ui.label(str(int(value))).classes("sov-mail-status-value")
                        ui.label(label).classes("sov-mail-status-label")
                collect = action_button(
                    "Забрать ещё",
                    icon="o_mark_email_unread",
                    on_click=lambda: asyncio.create_task(collect_more()),
                    variant="primary",
                    compact=True,
                    classes="sov-mail-collect-button",
                )
                if state.get("collecting"):
                    collect.props("loading disable")
                elif account.get("kind") == "outlook_classic" and not sys.platform.startswith("win"):
                    collect.props("disable")
                    collect.tooltip("Сборщик classic Outlook запускается на Windows")

    def render_accounts() -> None:
        panel = refs.get("accounts")
        if panel is None:
            return
        panel.clear()
        with panel:
            section_heading("Ящики", "Каждый ящик ограничен своим датасетом.")
            if not state["accounts"]:
                render_feedback_state(
                    "empty",
                    detail="Подключите ящик в Конфигурации → Почта.",
                )
            selected_id = (state.get("account") or {}).get("id")
            for account in state["accounts"]:
                active = account.get("id") == selected_id
                with ui.element("button").classes(
                    f"sov-mail-account {'sov-mail-account--active' if active else ''}"
                ).props(
                    f'type="button" aria-pressed="{"true" if active else "false"}"'
                ).on("click", lambda _event, item=account: asyncio.create_task(select_account(item))):
                    ui.icon("o_mail").classes("sov-mail-account__icon")
                    with ui.column().classes("sov-mail-account__copy"):
                        ui.label(account.get("label") or "Почта").classes("sov-mail-account__title")
                        ui.label(account.get("dataset_name") or "Датасет создаётся автоматически").classes(
                            "sov-mail-account__dataset"
                        )
                        ui.label(
                            f"{account.get('kind')} · {account.get('sync_state') or 'idle'}"
                        ).classes("sov-mail-account__meta")
                    status_badge("Выбран" if active else "Готов", "ok" if active else "muted")
            account = state.get("account") or {}
            if account:
                folders = [
                    str(folder.get("path") or "—")
                    for folder in state["folders"]
                    if folder.get("account_id") == account.get("id")
                ]
                if folders:
                    with ui.expansion("Папки", icon="o_folder").classes(
                        "w-full sov-mail-disclosure"
                    ).props("dense"):
                        for folder in folders:
                            ui.label(folder).classes("sov-mail-meta")

    def render_messages() -> None:
        panel = refs.get("messages")
        if panel is None:
            return
        panel.clear()
        with panel:
            account = state.get("account") or {}
            section_heading(account.get("label") or "Переписка", "Цепочки писем по теме.")
            if not state["messages"]:
                render_feedback_state("empty", detail="Писем пока нет. Запустите ручной сбор.")
            threads: dict[str, list[dict]] = {}
            for message in state["messages"]:
                threads.setdefault(message.get("thread_key") or message["id"], []).append(message)
            for messages in threads.values():
                latest = messages[0]
                with ui.element("button").classes(
                    "sov-mail-message"
                ).props(
                    'type="button"'
                ).on("click", lambda _event, item=latest: asyncio.create_task(show_message(item))):
                    with ui.row().classes("sov-mail-message__head"):
                        ui.label(latest.get("subject") or "(без темы)").classes(
                            "sov-mail-message__subject"
                        )
                        if len(messages) > 1:
                            status_badge(str(len(messages)), "muted")
                    ui.label(latest.get("sender") or "Отправитель не указан").classes(
                        "sov-mail-message__sender"
                    )
                    ui.label(latest.get("received_at") or latest.get("sent_at") or "Дата не указана").classes(
                        "sov-mail-message__date"
                    )

    def render_detail() -> None:
        panel = refs.get("detail")
        if panel is None:
            return
        panel.clear()
        with panel:
            detail = state.get("detail") or {}
            if not detail:
                render_feedback_state(
                    "empty",
                    detail="Выберите письмо слева — здесь появятся текст, вложения и источник.",
                )
                return
            message = detail.get("message") or {}
            profile = detail.get("profile") or {}
            account = detail.get("account") or {}
            with ui.column().classes("sov-mail-detail__head"):
                ui.label(profile.get("mail_subject") or message.get("subject") or "(без темы)").classes(
                    "sov-mail-detail__title"
                )
                ui.label(f"От: {profile.get('mail_from') or message.get('sender') or '—'}").classes(
                    "sov-mail-detail__participant"
                )
                ui.label("Кому: " + ", ".join(profile.get("mail_to") or [])).classes(
                    "sov-mail-detail__meta"
                )
            with ui.row().classes("sov-mail-detail__actions"):
                if message.get("source_kind") == "outlook_classic":
                    action_button(
                        "Открыть в Outlook",
                        icon="o_open_in_new",
                        on_click=lambda: asyncio.create_task(open_outlook(message["id"])),
                        compact=True,
                        variant="secondary",
                    )
                action_button(
                    "Спросить в чате",
                    icon="o_forum",
                    on_click=lambda: ui.navigate.to(_message_chat_url(account, message)),
                    compact=True,
                    variant="primary",
                    classes="sov-mail-ask-button",
                )
            with panel(variant="inset", classes="sov-mail-body"):
                ui.label(detail.get("body") or "(тело не извлечено)").classes("sov-mail-body__text")
            attachments = detail.get("attachments") or []
            if attachments:
                section_heading("Вложения", f"Файлов: {len(attachments)}")
                with ui.column().classes("w-full sov-mail-attachments"):
                    for attachment in attachments:
                        with ui.row().classes("sov-mail-attachment"):
                            ui.icon("o_attach_file")
                            ui.label(str(attachment.get("filename") or "Вложение")).classes(
                                "sov-mail-attachment__name"
                            )
                            ui.label(
                                f"{attachment.get('extraction')} · {attachment.get('size_bytes', 0)} Б"
                            ).classes("sov-mail-meta")
            with ui.expansion("Источник и диагностика", icon="o_fact_check").classes(
                "w-full sov-mail-disclosure"
            ).props("dense"):
                ui.label(
                    f"{message.get('source_kind')} · {account.get('dataset_name')} · {message.get('index_status')}"
                ).classes("sov-mail-meta")
                for location in message.get("locations") or []:
                    ui.label(f"Папка: {location.get('folder_path')}").classes("sov-mail-meta")

    with ui.column().classes("w-full h-full sov-mail-page"):
        with panel(variant="raised", classes="sov-mail-hero"):
            acronym_identity(
                "Е.Ж.И.К.",
                "Единый Журнал Импорта Корреспонденции",
                icon="o_mark_email_read",
            )
            ui.label(
                "Read-only переписка: выберите письмо и передайте его в чат с точной областью источника."
            ).classes("sov-mail-hero__detail")
        with ui.column().classes("w-full") as status_panel:
            refs["status"] = status_panel
        with ui.row().classes("sov-mail-search"):
            refs["search"] = text_field(
                placeholder="Поиск по теме, отправителю или получателю",
                aria_label="Поиск по теме и участникам",
                clearable=True,
                classes="sov-mail-search__field",
            )
            refs["search"].on("keydown.enter", lambda: asyncio.create_task(load_messages()))
            action_button(
                icon="o_search",
                on_click=lambda: asyncio.create_task(load_messages()),
                variant="secondary",
                icon_only=True,
                aria_label="Найти письма",
            )
        with ui.element("section").classes("sov-mail-workbench"):
            with panel(variant="plain", classes="sov-mail-column sov-mail-column--accounts"):
                refs["accounts"] = ui.column().classes("w-full sov-mail-column__content")
            with panel(variant="plain", classes="sov-mail-column sov-mail-column--messages"):
                refs["messages"] = ui.column().classes(
                    "w-full sov-mail-column__content"
                )
            with panel(variant="plain", classes="sov-mail-column sov-mail-column--detail"):
                refs["detail"] = ui.column().classes(
                    "w-full sov-mail-column__content"
                )

    render_accounts()
    render_status()
    render_messages()
    render_detail()
    asyncio.create_task(load_accounts())


def build_mail_settings() -> None:
    """Configurator-only account and collector setup; never renders messages."""
    state = {"accounts": [], "folders": [], "loading": False}
    refs: dict[str, object] = {}

    async def load() -> None:
        state["loading"] = True
        render()
        payload = await api_get("/api/mail/accounts")
        state["loading"] = False
        if not isinstance(payload, dict):
            host = refs.get("panel")
            if host is not None:
                with host:
                    ui.notify(last_api_error_text("Не удалось загрузить настройки почты"), type="negative")
            render()
            return
        state["accounts"] = list(payload.get("accounts") or [])
        state["folders"] = list(payload.get("folders") or [])
        render()

    async def test_account(account: dict) -> None:
        result = await api_post(f"/api/mail/accounts/{account['id']}/test", {})
        if isinstance(result, dict) and result.get("status") == "ready":
            ui.notify("Подключение готово", type="positive")
        else:
            ui.notify(last_api_error_text("Проверка подключения не прошла"), type="negative")

    async def sync_account(account: dict) -> None:
        if account.get("kind") != "imap":
            ui.notify("Outlook собирается интерактивной задачей Windows", type="info")
            return
        result = await api_post(
            f"/api/mail/accounts/{account['id']}/sync",
            {"mode": "incremental", "max_messages": 200, "parse": True},
        )
        if isinstance(result, dict):
            ui.notify(f"Получено новых писем: {int(result.get('files') or 0)}", type="positive")
            await load()
        else:
            ui.notify(last_api_error_text("Синхронизация не удалась"), type="negative")

    async def run_outlook_collector() -> None:
        result = await api_post("/api/mail/collector/run", {})
        if isinstance(result, dict) and result.get("status") == "started":
            ui.notify("Сбор новых писем запущен; Outlook освободится не позднее 15 секунд", type="positive")
        else:
            ui.notify(last_api_error_text("Не удалось запустить сбор Outlook"), type="negative")

    def add_account() -> None:
        with ui.dialog() as dialog, ui.card().classes("sov-mail-settings-dialog"):
            ui.label("Подключить IMAP").classes("sov-mail-settings-dialog-title")
            provider = ui.select(
                {"yandex": "Яндекс", "custom": "Другой IMAP"},
                value="yandex",
                label="Провайдер",
            ).classes("w-full")
            label = ui.input("Название ящика").classes("w-full")
            login = ui.input("Логин / адрес почты").classes("w-full")
            password = ui.input(
                "Пароль приложения",
                password=True,
                password_toggle_button=True,
            ).classes("w-full")
            host = ui.input("IMAP-сервер", value="imap.yandex.ru").classes("w-full")
            port = ui.number("Порт", value=993, min=1, max=65535).classes("w-full")
            ui.label(
                "Секрет сохраняется в системном хранилище и не возвращается API."
            ).classes("sov-mail-settings-note")

            async def create() -> None:
                result = await api_post(
                    "/api/mail/accounts",
                    {
                        "kind": "imap",
                        "provider": provider.value,
                        "label": label.value or login.value,
                        "login": login.value,
                        "password": password.value,
                        "host": host.value,
                        "port": int(port.value or 993),
                        "ssl": True,
                        "folders": ["*"],
                    },
                )
                if not isinstance(result, dict):
                    ui.notify(last_api_error_text("Не удалось подключить ящик"), type="negative")
                    return
                password.value = ""
                dialog.close()
                ui.notify("Ящик подключён", type="positive")
                await load()

            with ui.row().classes("justify-end w-full gap-2"):
                action_button("Отмена", on_click=dialog.close, variant="quiet")
                action_button("Подключить", icon="o_add", on_click=create, variant="primary")
        dialog.open()

    def render() -> None:
        container = refs.get("panel")
        if container is None:
            return
        container.clear()
        with container:
            with panel(variant="raised", classes="sov-mail-settings-hero"):
                with ui.row().classes("sov-mail-settings-head"):
                    with ui.column().classes("sov-mail-settings-identity"):
                        acronym_identity(
                            "Е.Ж.И.К.",
                            "Единый Журнал Импорта Корреспонденции",
                            icon="o_mark_email_read",
                        )
                        ui.label(
                            "Подключения и ручная синхронизация. Читать письма и задавать вопросы — в рабочей вкладке «Почта»."
                        ).classes("sov-mail-settings-subtitle")
                    action_button(
                        "Подключить IMAP",
                        icon="o_add",
                        on_click=add_account,
                        variant="primary",
                        classes="sov-mail-settings-connect",
                    )
            with panel(variant="plain", classes="sov-mail-settings-section"):
                section_heading(
                    "Сборщики",
                    "Оба контура read-only: они только читают письма и складывают локальные снимки в отдельные датасеты.",
                )
                with ui.element("section").classes("sov-mail-collector-card"):
                    ui.icon("o_desktop_windows").classes("sov-mail-collector-card__icon")
                    with ui.column().classes("sov-mail-collector-card__copy"):
                        ui.label("Classic Outlook").classes("sov-mail-settings-card-title")
                        ui.label(
                            "Локальный ручной сборщик · read-only · при первом запуске сам зарегистрирует видимые ящики."
                        ).classes("sov-mail-settings-note")
                    action_button(
                        "Забрать новые письма",
                        icon="o_mark_email_unread",
                        on_click=lambda: asyncio.create_task(run_outlook_collector()),
                        variant="secondary",
                        classes="sov-mail-settings-collect",
                    )
            with panel(variant="plain", classes="sov-mail-settings-section"):
                section_heading(
                    "Подключённые ящики",
                    "Один ящик — один датасет. Область не расширяется при поиске.",
                )
                if state.get("loading"):
                    with ui.row().classes("items-center sov-mail-settings-loading"):
                        ui.spinner(size="sm")
                        ui.label("Читаю подключения…")
                    return
                if not state["accounts"]:
                    render_feedback_state(
                        "empty",
                        detail="IMAP-ящики пока не подключены. Запустите сбор Classic Outlook — найденные ящики появятся автоматически.",
                    )
                    return
                for account in state["accounts"]:
                    folders = [
                        str(item.get("path") or "")
                        for item in state["folders"]
                        if item.get("account_id") == account.get("id")
                    ]
                    with ui.element("section").classes("sov-mail-account-card"):
                        with ui.row().classes("sov-mail-account-card__row"):
                            ui.icon("o_mail").classes("sov-mail-account-card__icon")
                            with ui.column().classes("sov-mail-account-card__copy"):
                                with ui.row().classes("sov-mail-account-card__identity"):
                                    ui.label(account.get("label") or "Почтовый ящик").classes(
                                        "sov-mail-settings-card-title"
                                    )
                                    status_badge(
                                        "Готов" if account.get("sync_state") in {"ready", "idle", "complete"} else "Проверить",
                                        "ok" if account.get("sync_state") in {"ready", "idle", "complete"} else "warn",
                                    )
                                ui.label(
                                    f"{account.get('kind')} · {account.get('sync_state') or 'idle'}"
                                ).classes("sov-mail-settings-note")
                                ui.label(
                                    account.get("dataset_name") or "Отдельный датасет будет создан автоматически"
                                ).classes("sov-mail-settings-dataset")
                                if folders:
                                    ui.label("Папки: " + ", ".join(folders[:12])).classes(
                                        "sov-mail-settings-note"
                                    )
                            with ui.row().classes("sov-mail-account-card__actions"):
                                action_button(
                                    "Проверить",
                                    icon="o_fact_check",
                                    on_click=lambda _e, item=account: asyncio.create_task(test_account(item)),
                                    compact=True,
                                    variant="secondary",
                                )
                                sync = action_button(
                                    "Синхронизировать",
                                    icon="o_sync",
                                    on_click=lambda _e, item=account: asyncio.create_task(sync_account(item)),
                                    compact=True,
                                    variant="quiet",
                                )
                                if account.get("kind") != "imap":
                                    sync.props("disable")

    with ui.column().classes("w-full h-full sov-mail-settings-page") as settings_panel:
        refs["panel"] = settings_panel
    render()
    asyncio.create_task(load())
