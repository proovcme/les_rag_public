"""
С.О.В.У.Ш.К.А. v5.0 — премиальная рабочая вкладка AI ЧАТ
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Optional

from nicegui import ui

from sovushka.components.charts import _html, esc
from sovushka.state import add_log, api_get, api_post, refresh_indexing_mode, refresh_samovar, state


OUTPUT_FORMATS = {
    "text": ("Текст", "Свободный ответ"),
    "spec": ("Спецификация", "JSON-таблица изделий"),
    "schema": ("Схема", "Иерархия или дерево"),
    "structure": ("Структура", "JSON-объект"),
    "table": ("Таблица", "JSON-массив строк"),
    "mermaid": ("Диаграмма", "Mermaid"),
    "svg": ("SVG", "Векторная схема"),
    "template": ("По образцу", "Структура файла"),
}


def build_chat(is_admin: bool, tabs=None, tab_mermaid=None):
    """Строит автономный экран чата: история слева, чат по центру, артефакты справа."""

    out_mode_val = {"v": "text"}
    selected_session_card = {"el": None}

    with ui.element("div").classes("sov-chat-shell"):
        history_drawer = ui.element("aside").classes("sov-history-drawer")
        history_drawer.set_visibility(False)

        with history_drawer:
            with ui.row().classes("w-full items-center justify-between"):
                _html('<div class="sov-panel-title">История</div>')
                ui.button(icon="o_close", on_click=lambda: history_drawer.set_visibility(False)).props(
                    "flat round dense"
                ).classes("sov-icon-btn")
            sessions_col = ui.column().classes("w-full gap-2 sov-history-list")

        with ui.element("main").classes("sov-chat-main"):
            with ui.row().classes("sov-chat-topbar"):
                with ui.row().classes("items-center gap-2"):
                    ui.button(icon="o_history", on_click=lambda: _toggle_history()).props(
                        "flat round dense"
                    ).classes("sov-icon-btn")
                    _html('<div class="sov-chat-title">С.О.В.У.Ш.К.А.</div>')
                    _html('<div class="sov-chat-subtitle">нормативный RAG-диспетчер</div>')
                with ui.row().classes("items-center gap-2"):
                    mode_chip = ui.label("RAG").classes("sov-chip")
                    _html('<span class="sov-chip sov-chip-soft">CRAG</span>')
                    ui.button(icon="o_delete_sweep", on_click=lambda: _clear_chat()).props(
                        "flat round dense"
                    ).classes("sov-icon-btn")

            chat_scroll = ui.scroll_area().classes("sov-chat-scroll")
            with chat_scroll:
                chat_column = ui.column().classes("sov-chat-thread")
                with chat_column:
                    _html('<div class="chat-msg-sys">Система активирована. Ожидание запросов.</div>')

            indexing_banner = ui.label("").classes("sov-indexing-banner")
            indexing_banner.set_visibility(False)

            with ui.element("div").classes("sov-composer") as composer_box:
                chat_input = ui.textarea(
                    placeholder="Спросить по нормативам, проекту или базе знаний..."
                ).classes("sov-composer-input").props("rows=2 autogrow borderless")
                with ui.row().classes("sov-composer-actions"):
                    advanced_btn = ui.button(
                        "Расширенный запрос",
                        icon="o_tune",
                        on_click=lambda: advanced_dialog.open(),
                    ).props("no-caps flat")
                    send_btn = ui.button(
                        "Отправить",
                        icon="o_send",
                        on_click=lambda: asyncio.create_task(send_chat()),
                    ).props("no-caps")

        with ui.element("aside").classes("sov-artifacts-panel"):
            with ui.row().classes("w-full items-center justify-between"):
                _html('<div class="sov-panel-title">Артефакты</div>')
                _html('<span class="sov-chip sov-chip-soft">live</span>')
            artifact_panel = ui.column().classes("sov-artifacts-body")
            with artifact_panel:
                _html(
                    '<div class="sov-artifact-empty">'
                    '<div class="sov-artifact-empty-title">Пока пусто</div>'
                    '<div class="sov-muted">Структурированные ответы, таблицы, SVG и диаграммы появятся здесь.</div>'
                    '</div>'
                )

    with ui.dialog() as advanced_dialog:
        with ui.card().classes("sov-advanced-dialog"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    _html('<div class="sov-panel-title">Расширенный запрос</div>')
                    _html('<div class="sov-muted">формат, датасет, стиль и образец выдачи</div>')
                ui.button(icon="o_close", on_click=advanced_dialog.close).props("flat round dense").classes("sov-icon-btn")

            with ui.scroll_area().classes("sov-advanced-scroll"):
                with ui.column().classes("w-full gap-3"):
                    with ui.card().classes("sov-control-card"):
                        _html('<div class="section-title">Формат выдачи</div>')
                        format_hint_lbl = ui.label(OUTPUT_FORMATS["text"][1]).classes("sov-muted")
                        format_btns = {}
                        with ui.grid(columns=4).classes("w-full gap-2"):
                            for key, (label, hint) in OUTPUT_FORMATS.items():
                                btn = ui.button(label).props("no-caps flat").classes("sov-format-btn")
                                format_btns[key] = btn

                    with ui.card().classes("sov-control-card"):
                        _html('<div class="section-title">Параметры форматов</div>')
                        mermaid_opts_row = ui.column().classes("w-full gap-2")
                        with mermaid_opts_row:
                            mermaid_type = ui.select(
                                [
                                    "flowchart TD",
                                    "flowchart LR",
                                    "sequenceDiagram",
                                    "erDiagram",
                                    "gantt",
                                    "classDiagram",
                                    "mindmap",
                                ],
                                value="flowchart TD",
                                label="Тип диаграммы",
                            ).classes("w-full")
                        mermaid_opts_row.set_visibility(False)

                        svg_opts_row = ui.column().classes("w-full gap-2")
                        with svg_opts_row:
                            svg_type = ui.select(
                                [
                                    "Аксонометрическая схема",
                                    "План помещения",
                                    "Функциональная схема",
                                    "Принципиальная схема",
                                    "Организационная структура",
                                    "Диаграмма потоков",
                                ],
                                value="Функциональная схема",
                                label="Тип SVG",
                            ).classes("w-full")
                            svg_size = ui.select(
                                ["800×600", "1200×800", "600×400", "1600×900"],
                                value="800×600",
                                label="Размер",
                            ).classes("w-full")
                        svg_opts_row.set_visibility(False)

                        spec_opts_row = ui.column().classes("w-full gap-2")
                        with spec_opts_row:
                            spec_type = ui.select(
                                [
                                    "Спецификация оборудования (по ГОСТ 21.110)",
                                    "Ведомость чертежей (ГОСТ 21.101)",
                                    "Ведомость ссылочных документов",
                                    "Спецификация материалов",
                                    "Перечень элементов (ПЭ3)",
                                ],
                                value="Спецификация оборудования (по ГОСТ 21.110)",
                                label="Тип спецификации",
                            ).classes("w-full")
                            spec_group = ui.switch("Группировать по разделам")
                            spec_gost = ui.switch("Строгий формат ГОСТ", value=True)
                        spec_opts_row.set_visibility(False)

                        schema_opts_row = ui.column().classes("w-full gap-2")
                        with schema_opts_row:
                            schema_depth = ui.number("Глубина вложенности", value=3, min=1, max=6, step=1).classes("w-full")
                            schema_format = ui.select(
                                ["JSON дерево", "Маркированный список", "Нумерованный список", "YAML"],
                                value="JSON дерево",
                                label="Формат схемы",
                            ).classes("w-full")
                        schema_opts_row.set_visibility(False)

                        template_row = ui.column().classes("w-full gap-2")
                        with template_row:
                            ui.label("Файл-образец: JSON, CSV или XLSX").classes("sov-muted")
                            ui.upload(
                                auto_upload=True,
                                on_upload=lambda e: asyncio.create_task(load_output_template(e)),
                            ).props("flat accept=.json,.csv,.xlsx").classes("w-full")
                            template_lbl = ui.label("").style("color:var(--ok);font-size:.72rem;")
                            template_preview = _html("").classes("sov-template-preview")
                        template_row.set_visibility(False)

                    with ui.card().classes("sov-control-card"):
                        _html('<div class="section-title">Детали запроса</div>')
                        detail_dataset = ui.select([], label="Датасет").classes("w-full")
                        detail_depth = ui.select(
                            [
                                "Кратко (1-2 абзаца)",
                                "Стандарт (3-5 абзацев)",
                                "Подробно (развёрнутый ответ)",
                                "Максимум (полный анализ)",
                            ],
                            value="Стандарт (3-5 абзацев)",
                            label="Детальность",
                        ).classes("w-full")
                        detail_lang = ui.select(
                            [
                                "Русский (технический)",
                                "Русский (нормативный ГОСТ)",
                                "Краткие тезисы",
                                "Для презентации",
                            ],
                            value="Русский (технический)",
                            label="Стиль",
                        ).classes("w-full")
                        reranker_sw = ui.switch("Реранкер", value=False)
                        detail_extra = ui.textarea(label="Дополнительные требования").props("rows=3").classes("w-full")

                    with ui.card().classes("sov-control-card"):
                        with ui.row().classes("w-full items-center justify-between"):
                            _html('<div class="section-title">Промпт</div>')
                            ui.button(icon="o_refresh", on_click=lambda: _update_prompt_preview()).props("flat round dense").classes("sov-icon-btn")
                        prompt_preview = _html("").classes("sov-prompt-preview")

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Закрыть", on_click=advanced_dialog.close).props("no-caps flat")
                apply_btn = ui.button(
                    "Применить и отправить",
                    icon="o_send",
                    on_click=lambda: asyncio.create_task(send_with_form()),
                ).props("no-caps")

    def select_format(key: str):
        out_mode_val["v"] = key
        label, hint = OUTPUT_FORMATS[key]
        format_hint_lbl.set_text(hint)
        for fmt_key, btn in format_btns.items():
            if fmt_key == key:
                btn.classes(add="sov-format-btn-active")
            else:
                btn.classes(remove="sov-format-btn-active")
        mermaid_opts_row.set_visibility(key == "mermaid")
        svg_opts_row.set_visibility(key == "svg")
        spec_opts_row.set_visibility(key == "spec")
        schema_opts_row.set_visibility(key == "schema")
        template_row.set_visibility(key == "template")
        _html_set_artifact_mode(label, hint)
        _update_prompt_preview()

    for _key in OUTPUT_FORMATS:
        format_btns[_key].on("click", lambda k=_key: select_format(k))

    async def _load_datasets_select():
        await refresh_samovar()
        names = [s.get("folder", "") for s in state["sources"]]
        detail_dataset.options = ["(все датасеты)"] + names
        detail_dataset.value = "(все датасеты)"

    asyncio.create_task(_load_datasets_select())

    def _toggle_history():
        history_drawer.set_visibility(not history_drawer.visible)
        if history_drawer.visible:
            asyncio.create_task(_load_sessions())

    async def _load_sessions():
        sessions_col.clear()
        data = await api_get("/api/chat/sessions?limit=40")
        if not data:
            with sessions_col:
                _html('<div class="sov-muted" style="padding:14px;">Нет сохранённых сессий</div>')
            return
        with sessions_col:
            for session in data:
                _render_session_card(session)

    def _render_session_card(session: dict):
        sid = session["session_id"]
        first_q = session.get("first_question") or "Без названия"
        msg_count = session.get("msg_count", 0)
        started_at = (session.get("started_at") or "")[:16].replace("T", " ")
        with ui.element("button").classes("sov-session-card") as card:
            _html(f'<span class="sov-session-title">{esc(first_q[:90])}</span>')
            _html(f'<span class="sov-session-meta">{esc(started_at)} · {msg_count} сообщ.</span>')

        async def _open(session_id=sid, el=card):
            await _open_session(session_id, el)

        card.on("click", _open)

    async def _open_session(session_id: str, el=None):
        add_log(f"[ИСТОРИЯ] Загружаю сессию {session_id[:8]}...")
        msgs = await api_get(f"/api/chat/history?session_id={session_id}")
        if msgs is None:
            add_log("[ИСТОРИЯ] Ошибка загрузки сессии")
            return
        state["chat_history"] = msgs
        state["load_session_id"] = session_id
        state["session_id"] = session_id
        if selected_session_card["el"]:
            selected_session_card["el"].classes(remove="sov-session-card-active")
        if el:
            el.classes(add="sov-session-card-active")
            selected_session_card["el"] = el
        _render_chat_history("Сессия загружена из истории.")
        history_drawer.set_visibility(False)
        chat_scroll.scroll_to(percent=1)

    def _render_msg(msg):
        if msg.get("role") == "user":
            _html(f'<div class="chat-msg-user">{esc(msg.get("text", ""))}</div>')
            return
        ans = msg.get("text", "")
        srcs = msg.get("srcs", [])
        crag = msg.get("crag", "")
        srcs_html = ""
        if srcs:
            tags = "".join(
                f'<span class="src-tag">{esc(s.get("file", s) if isinstance(s, dict) else s)}</span>'
                for s in srcs
            )
            srcs_html = f'<div class="msg-srcs">{tags}</div>'
        if crag:
            cls = "src-tag" if crag == "VERIFIED" else "src-tag src-tag-err"
            srcs_html += f'<span class="{cls}">Т.О.С.К.А.: {esc(crag)}</span>'
        safe_ans = esc(ans).replace(chr(10), "<br>")
        _html(f'<div class="chat-msg-ai">{safe_ans}{srcs_html}</div>')

    def _render_chat_history(system_msg: str = "История загружена."):
        chat_column.clear()
        with chat_column:
            _html(f'<div class="chat-msg-sys">{esc(system_msg)}</div>')
            for msg in state.get("chat_history", []):
                _render_msg(msg)
            if state.get("chat_pending"):
                pending_q = state["chat_pending"].get("question", "")
                _html(f'<div class="chat-msg-ai typing">Запрос выполняется: {esc(pending_q[:80])}</div>')

    async def _load_history():
        if state.get("load_session_id"):
            state["session_id"] = state["load_session_id"]
            state["load_session_id"] = None
            _render_chat_history("Сессия загружена из истории.")
            chat_scroll.scroll_to(percent=1)
            return
        if not state.get("chat_history"):
            hist = await api_get("/api/chat/history?limit=40")
            if hist:
                state["chat_history"] = hist
                _render_chat_history()
                chat_scroll.scroll_to(percent=1)

    asyncio.create_task(_load_history())

    async def load_output_template(e):
        content = e.content.read()
        fname = e.name
        try:
            if fname.endswith(".json"):
                data = json.loads(content.decode("utf-8"))
                state["output_template"] = data if isinstance(data, list) else [data]
            elif fname.endswith(".csv"):
                lines = content.decode("utf-8").strip().split("\n")
                keys = [k.strip() for k in lines[0].split(",")]
                rows = [dict(zip(keys, [v.strip() for v in row.split(",")])) for row in lines[1:] if row.strip()]
                state["output_template"] = rows
            elif fname.endswith(".xlsx"):
                import tempfile
                import openpyxl

                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
                    tf.write(content)
                    tf.flush()
                    wb = openpyxl.load_workbook(tf.name)
                    ws = wb.active
                    headers = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
                    rows = []
                    for row in list(ws.iter_rows(min_row=2, values_only=True))[:20]:
                        rows.append(dict(zip(headers, [str(v or "") for v in row])))
                    state["output_template"] = rows
            else:
                ui.notify("Поддерживаются JSON, CSV, XLSX", type="warning")
                return

            tmpl = state["output_template"]
            template_lbl.set_text(f"{fname} · {len(tmpl)} строк")
            if tmpl:
                preview_str = json.dumps(tmpl[0], ensure_ascii=False, indent=2)
                template_preview.set_content(f'<pre>{esc(preview_str)}</pre>')
            add_log(f"[ШАБЛОН] Загружен {fname} · {len(tmpl)} строк")
            _update_prompt_preview()
        except Exception as ex:
            ui.notify(f"Ошибка парсинга: {ex}", type="negative")
            add_log(f"[ШАБЛОН] Ошибка: {ex}")

    def _build_extra_prompt(question: str) -> str:
        mode = out_mode_val["v"]
        depth_map = {
            "Кратко (1-2 абзаца)": "Ответь кратко — 1-2 абзаца.",
            "Стандарт (3-5 абзацев)": "Ответь развёрнуто — 3-5 абзацев.",
            "Подробно (развёрнутый ответ)": "Дай полный развёрнутый ответ со всеми деталями.",
            "Максимум (полный анализ)": "Проведи максимально подробный анализ. Не сокращай.",
        }
        style_map = {
            "Русский (технический)": "Пиши профессиональным техническим языком.",
            "Русский (нормативный ГОСТ)": "Пиши в нормативном стиле ГОСТ: чёткие формулировки, без лирики.",
            "Краткие тезисы": "Отвечай тезисами — каждый пункт одна мысль.",
            "Для презентации": "Формат для слайдов: заголовок + маркированный список.",
        }

        parts = []
        if depth_map.get(detail_depth.value):
            parts.append(depth_map[detail_depth.value])
        if style_map.get(detail_lang.value):
            parts.append(style_map[detail_lang.value])

        if mode == "spec":
            gost_str = " строго по форме ГОСТ 21.110-2013" if spec_gost.value else ""
            group_str = " Группируй по разделам." if spec_group.value else ""
            parts.append(
                f"\n\nВЫВЕДИ ОТВЕТ В ФОРМАТЕ СПЕЦИФИКАЦИИ{gost_str}.\n"
                f"Тип: {spec_type.value}.{group_str}\n"
                "Верни JSON-массив объектов. Обязательные поля: "
                "поз, обозначение, наименование, тип_марка, ед_изм, кол_во, масса_ед, примечание.\n"
                "Оберни в ```json ... ```"
            )
        elif mode == "schema":
            depth = int(schema_depth.value) if schema_depth.value else 3
            fmt = schema_format.value
            if fmt == "JSON дерево":
                parts.append(
                    f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ JSON-ДЕРЕВА, глубина {depth}. "
                    "Структура узла: {\"name\": str, \"children\": [...], \"desc\": str}. "
                    "Оберни в ```json ... ```"
                )
            elif fmt == "YAML":
                parts.append(f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ YAML-ДЕРЕВА, глубина {depth}. Оберни в ```yaml ... ```")
            else:
                parts.append(f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ {fmt.upper()}, глубина {depth} уровней.")
        elif mode == "structure":
            parts.append("\n\nВЫВЕДИ ОТВЕТ В ВИДЕ СТРУКТУРИРОВАННОГО JSON-ОБЪЕКТА. Оберни в ```json ... ```")
        elif mode == "table":
            parts.append("\n\nВЫВЕДИ ОТВЕТ В ВИДЕ ТАБЛИЦЫ: JSON-массив объектов. Оберни в ```json ... ```")
        elif mode == "mermaid":
            parts.append(
                f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ MERMAID-ДИАГРАММЫ типа {mermaid_type.value}. "
                "Оберни в ```mermaid ... ```. Пиши на русском, метки узлов короткие."
            )
        elif mode == "svg":
            w, h = svg_size.value.split("×") if "×" in svg_size.value else ("800", "600")
            parts.append(
                f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ SVG-СХЕМЫ ({svg_type.value}). "
                f"Размер viewBox: 0 0 {w} {h}. Оберни в ```svg ... ```"
            )
        elif mode == "template":
            tmpl = state.get("output_template")
            if tmpl:
                parts.append(
                    "\n\nОТВЕЧАЙ СТРОГО ПО СТРУКТУРЕ ОБРАЗЦА (JSON-массив).\n"
                    f"Образец:\n```json\n{json.dumps(tmpl[:3], ensure_ascii=False, indent=2)}\n```\n"
                    "Оберни в ```json ... ```"
                )
            else:
                parts.append("\n\nОТВЕЧАЙ В ВИДЕ JSON-МАССИВА ОБЪЕКТОВ. Оберни в ```json ... ```")

        if detail_extra.value and detail_extra.value.strip():
            parts.append(f"\n\nДОПОЛНИТЕЛЬНО: {detail_extra.value.strip()}")
        return " ".join(parts[:2]) + "".join(parts[2:])

    def _update_prompt_preview():
        q = chat_input.value.strip() or "[текст запроса]"
        extra = _build_extra_prompt(q)
        preview_text = (q + extra)[:1000] + ("..." if len(q + extra) > 1000 else "")
        prompt_preview.set_content(f'<pre>{esc(preview_text)}</pre>')

    chat_input.on("input", lambda: _update_prompt_preview())

    def _clear_chat():
        from sovushka.state import _new_session_id

        chat_column.clear()
        with chat_column:
            _html('<div class="chat-msg-sys">Чат очищен. Новая сессия готова.</div>')
        artifact_panel.clear()
        with artifact_panel:
            _render_empty_artifacts()
        state["chat_history"].clear()
        state["session_id"] = _new_session_id()
        state["load_session_id"] = None
        state["chat_pending"] = None
        add_log("[ЧАТ] История очищена, новая сессия")

    _sending = {"v": False}
    _resource_blocked = {"v": False, "reason": ""}

    def _indexing_summary(data: dict) -> str:
        rag = state.get("rag_health", {}) if isinstance(state.get("rag_health"), dict) else {}
        totals = rag.get("totals", {}) if isinstance(rag, dict) else {}
        indexed = totals.get("indexed_files", "—")
        pending = totals.get("pending_files", "—")
        errors = totals.get("error_files", "—")
        chunks = totals.get("chunks", "—")
        reason = data.get("chat_generation_reason") or "Индексация активна."
        return (
            f"Индексация активна: чат заблокирован. "
            f"indexed={indexed} · pending={pending} · errors={errors} · chunks={chunks}. "
            f"{reason}"
        )

    def _set_chat_blocked(blocked: bool, reason: str = ""):
        _resource_blocked["v"] = blocked
        _resource_blocked["reason"] = reason
        if blocked:
            send_btn.props("disabled")
            apply_btn.props("disabled")
            advanced_btn.props("disabled")
            chat_input.props("disabled")
            composer_box.classes(add="sov-composer-blocked")
            indexing_banner.set_text(reason)
            indexing_banner.set_visibility(True)
            mode_chip.set_text("INDEXING")
            mode_chip.classes(add="sov-chip-soft")
            return
        if not _sending["v"]:
            send_btn.props(remove="disabled")
            apply_btn.props(remove="disabled")
            advanced_btn.props(remove="disabled")
            chat_input.props(remove="disabled")
        composer_box.classes(remove="sov-composer-blocked")
        indexing_banner.set_visibility(False)
        mode_chip.set_text("RAG")
        mode_chip.classes(remove="sov-chip-soft")

    async def _refresh_resource_gate() -> bool:
        data = await refresh_indexing_mode()
        allowed = bool(data.get("chat_generation_allowed", True)) if isinstance(data, dict) else True
        blocked = not allowed
        _set_chat_blocked(blocked, _indexing_summary(data) if blocked else "")
        return allowed

    async def _do_send(question: str):
        if _sending["v"]:
            return
        if not await _refresh_resource_gate():
            msg = _resource_blocked["reason"] or "Индексация активна: чат временно заблокирован."
            ui.notify(msg, type="warning")
            with chat_column:
                _html(f'<div class="chat-msg-sys">{esc(msg)}</div>')
            chat_scroll.scroll_to(percent=1)
            return
        _sending["v"] = True
        send_btn.props("disabled")
        apply_btn.props("disabled")
        advanced_btn.props("disabled")
        chat_input.props("disabled")
        out_mode = out_mode_val["v"]

        state["chat_history"].append({"role": "user", "text": question})
        state["chat_pending"] = {"question": question, "started_at": time.time()}

        with chat_column:
            _html(f'<div class="chat-msg-user">{esc(question)}</div>')
            ai_placeholder = _html('<div class="chat-msg-ai typing">Генерирую... 0с</div>')
        chat_scroll.scroll_to(percent=1)
        _render_artifact_loading(out_mode, question)
        add_log(f'[AI] Запрос: "{question[:60]}"')

        extra_prompt = _build_extra_prompt(question)
        payload = {
            "question": question + extra_prompt,
            "reranker_enabled": reranker_sw.value,
            "session_id": state.get("session_id"),
        }
        if detail_dataset.value and detail_dataset.value != "(все датасеты)":
            payload["dataset_filter"] = detail_dataset.value

        _t0 = time.monotonic()
        _stop_tick = {"v": False}

        async def _tick():
            while not _stop_tick["v"]:
                elapsed = int(time.monotonic() - _t0)
                ai_placeholder.set_content(f'<div class="chat-msg-ai typing">Генерирую... {elapsed}с</div>')
                await asyncio.sleep(1)

        _tick_task = asyncio.create_task(_tick())

        completed = False
        try:
            d = await api_post("/api/chat", payload)
            completed = True
            if d:
                ans = d.get("answer", d.get("response", "Нет ответа"))
                srcs = d.get("sources", [])
                crag = d.get("crag_status", "")
                state["chat_history"].append({"role": "ai", "text": ans, "srcs": srcs, "crag": crag})
                ai_placeholder.set_content(_message_html(ans, srcs, crag))
                _render_result(ans, out_mode, artifact_panel)
                add_log(f"[AI] Формат:{out_mode} CRAG:{crag or 'N/A'} src:{len(srcs)}")
            else:
                ai_placeholder.set_content('<div class="chat-msg-ai" style="color:var(--err);">Ошибка запроса</div>')
                _render_artifact_error("Ошибка запроса")
        except Exception as ex:
            completed = True
            ai_placeholder.set_content(f'<div class="chat-msg-ai" style="color:var(--err);">Ошибка: {esc(str(ex))}</div>')
            _render_artifact_error(str(ex))
        finally:
            if completed:
                state["chat_pending"] = None
            _stop_tick["v"] = True
            _tick_task.cancel()
            _sending["v"] = False
            await _refresh_resource_gate()
            chat_scroll.scroll_to(percent=1)

    async def send_chat():
        q = chat_input.value.strip()
        if not q:
            return
        chat_input.value = ""
        _update_prompt_preview()
        await _do_send(q)

    async def send_with_form():
        q = chat_input.value.strip()
        if not q:
            ui.notify("Введите текст запроса", type="warning")
            return
        advanced_dialog.close()
        chat_input.value = ""
        _update_prompt_preview()
        await _do_send(q)

    def _message_html(ans: str, srcs: list, crag: str) -> str:
        srcs_html = ""
        if srcs:
            tags = "".join(
                f'<span class="src-tag">{esc(s.get("file", s) if isinstance(s, dict) else s)}</span>'
                for s in srcs
            )
            srcs_html = f'<div class="msg-srcs">{tags}</div>'
        if crag:
            cls = "src-tag" if crag == "VERIFIED" else "src-tag src-tag-err"
            srcs_html += f'<span class="{cls}">Т.О.С.К.А.: {esc(crag)}</span>'
        return f'<div class="chat-msg-ai">{esc(ans).replace(chr(10), "<br>")}{srcs_html}</div>'

    def _html_set_artifact_mode(label: str, hint: str):
        artifact_panel.clear()
        with artifact_panel:
            _html(
                '<div class="sov-artifact-empty">'
                f'<div class="sov-artifact-empty-title">{esc(label)}</div>'
                f'<div class="sov-muted">{esc(hint)}</div>'
                '</div>'
            )

    def _render_empty_artifacts():
        _html(
            '<div class="sov-artifact-empty">'
            '<div class="sov-artifact-empty-title">Пока пусто</div>'
            '<div class="sov-muted">Структурированные ответы, таблицы, SVG и диаграммы появятся здесь.</div>'
            '</div>'
        )

    def _render_artifact_loading(mode: str, question: str):
        artifact_panel.clear()
        label = OUTPUT_FORMATS.get(mode, ("Артефакт", ""))[0]
        with artifact_panel:
            _html(
                '<div class="sov-artifact-empty">'
                f'<div class="sov-artifact-empty-title">{esc(label)}</div>'
                f'<div class="sov-muted">Готовлю артефакт по запросу: {esc(question[:100])}</div>'
                '<div class="sov-artifact-loader"></div>'
                '</div>'
            )

    def _render_artifact_error(detail: str):
        artifact_panel.clear()
        with artifact_panel:
            _html(
                '<div class="sov-artifact-empty">'
                '<div class="sov-artifact-empty-title" style="color:var(--err);">Ошибка</div>'
                f'<div class="sov-muted">{esc(detail)}</div>'
                '</div>'
            )

    def _render_result(ans: str, mode: str, container):
        container.clear()
        with container:
            with ui.card().classes("sov-artifact-card"):
                label = OUTPUT_FORMATS.get(mode, ("Ответ", ""))[0]
                with ui.row().classes("w-full items-center justify-between"):
                    _html(f'<div class="sov-panel-title">{esc(label)}</div>')
                    ui.button("Копировать", icon="o_content_copy", on_click=lambda: ui.clipboard.write(ans)).props(
                        "no-caps flat dense"
                    )

                if mode == "text":
                    ui.markdown(ans).classes("sov-artifact-markdown")
                elif mode == "spec":
                    data = _parse_table_from_ai(ans)
                    if data:
                        _render_table(data)
                    else:
                        ui.markdown(ans).classes("sov-artifact-markdown")
                elif mode == "schema":
                    data = _parse_json_from_ai(ans)
                    if data:
                        with ui.column().classes("w-full gap-1"):
                            _render_tree(data)
                    else:
                        ui.markdown(ans).classes("sov-artifact-markdown")
                elif mode in ("structure", "table", "template"):
                    data = _parse_table_from_ai(ans) or _parse_json_from_ai(ans)
                    if isinstance(data, list) and data:
                        _render_table(data if isinstance(data[0], dict) else [{"значение": str(r)} for r in data])
                    elif isinstance(data, dict):
                        ui.markdown(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```").classes("sov-artifact-markdown")
                    else:
                        ui.markdown(ans).classes("sov-artifact-markdown")
                elif mode == "mermaid":
                    code = _parse_mermaid_from_ai(ans)
                    if code:
                        state["mermaid_last"] = code
                        ui.mermaid(code).classes("w-full")
                        with ui.row().classes("gap-2"):
                            ui.button("Код", icon="o_content_copy", on_click=lambda c=code: ui.clipboard.write(c)).props("no-caps flat dense")
                            if tabs and tab_mermaid:
                                ui.button("В редактор", icon="o_open_in_new", on_click=lambda: tabs.set_value(tab_mermaid)).props("no-caps flat dense")
                    else:
                        ui.markdown(ans).classes("sov-artifact-markdown")
                elif mode == "svg":
                    svg_code = _parse_svg_from_ai(ans)
                    if svg_code:
                        _html(f'<div class="sov-svg-preview">{svg_code}</div>')
                        ui.button("Копировать SVG", icon="o_content_copy", on_click=lambda c=svg_code: ui.clipboard.write(c)).props("no-caps flat dense")
                    else:
                        ui.markdown(ans).classes("sov-artifact-markdown")

    def _parse_table_from_ai(text: str):
        match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        return None

    def _parse_json_from_ai(text: str):
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        try:
            start = text.find("{") if "{" in text else text.find("[")
            if start >= 0:
                end = text.rfind("}") if "{" in text else text.rfind("]")
                return json.loads(text[start : end + 1])
        except Exception:
            pass
        return None

    def _parse_mermaid_from_ai(text: str) -> Optional[str]:
        match = re.search(r"```mermaid\s*(.*?)```", text, re.DOTALL)
        return match.group(1).strip() if match else None

    def _parse_svg_from_ai(text: str) -> Optional[str]:
        match = re.search(r"```svg\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"(<svg[\s\S]*?</svg>)", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _render_table(data: list[dict]):
        keys = list(data[0].keys()) if data else []
        cols = [{"name": k, "label": k, "field": k, "align": "left", "sortable": True} for k in keys]
        ui.table(columns=cols, rows=data, pagination=8).classes("sov-artifact-table")
        ui.button(
            "JSON",
            icon="o_content_copy",
            on_click=lambda d=data: ui.clipboard.write(json.dumps(d, ensure_ascii=False, indent=2)),
        ).props("no-caps flat dense")

    def _render_tree(data, level: int = 0):
        if isinstance(data, dict):
            name = data.get("name", data.get("title", data.get("id", "—")))
            desc = data.get("desc", data.get("description", ""))
            children = data.get("children", data.get("items", []))
            indent = level * 14
            _html(
                f'<div class="sov-tree-row" style="margin-left:{indent}px;">'
                f'<span class="sov-tree-mark">{"▸" if children else "•"}</span>'
                f'<span class="sov-tree-name">{esc(name)}</span>'
                f'<span class="sov-tree-desc">{esc(desc)}</span>'
                '</div>'
            )
            for child in children if isinstance(children, list) else []:
                _render_tree(child, level + 1)
        elif isinstance(data, list):
            for item in data:
                _render_tree(item, level)

    select_format("text")
    asyncio.create_task(_refresh_resource_gate())
    ui.timer(5.0, lambda: asyncio.create_task(_refresh_resource_gate()))
    chat_input.on(
        "keydown.enter.prevent",
        lambda e: asyncio.create_task(send_chat()) if not (e.args or {}).get("shiftKey") and not _resource_blocked["v"] else None,
    )
