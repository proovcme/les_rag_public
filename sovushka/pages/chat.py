"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка AI ЧАТ
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Optional
from nicegui import ui

from sovushka.state import state, api_get, api_post, add_log, refresh_samovar
from sovushka.components.charts import _html, esc


def build_chat(is_admin: bool, tabs=None, tab_mermaid=None):
    """Строит содержимое вкладки AI ЧАТ. Вызывать внутри with ui.tab_panel(tab_chat)."""
    with ui.splitter(value=62).classes("w-full").style("height:calc(100vh - 210px);min-height:500px;") as chat_split:

        # ── ЛЕВАЯ ПАНЕЛЬ: ЧАТ ──────────────────
        with chat_split.before:
            with ui.column().classes("w-full h-full gap-2 p-3"):

                # Чат-история
                chat_scroll = ui.scroll_area().classes("w-full flex-1").style(
                    "background:var(--bg-panel);border:1px solid var(--border);"
                    "border-radius:8px;min-height:0;"
                )
                with chat_scroll:
                    chat_column = ui.column().classes("w-full p-4 gap-3")
                    with chat_column:
                        _html('<div class="chat-msg-sys">Система активирована. Ожидание запросов.</div>')

                def _render_msg(msg):
                    if msg["role"] == "user":
                        safe_q = esc(msg["text"])
                        _html(f'<div class="chat-msg-user">{safe_q}</div>')
                    else:
                        ans = msg.get("text", "")
                        srcs = msg.get("srcs", [])
                        crag = msg.get("crag", "")
                        srcs_html = ""
                        if srcs:
                            tags = "".join(f'<span class="src-tag">{esc(s.get("file", s) if isinstance(s, dict) else s)}</span>' for s in srcs)
                            srcs_html = f'<div class="msg-srcs" style="margin-top:8px;">{tags}</div>'
                        if crag:
                            cls = "src-tag" if crag == "VERIFIED" else "src-tag src-tag-err"
                            srcs_html += f'<span class="{cls}" style="margin-left:4px;">Т.О.С.К.А.: {esc(crag)}</span>'
                        safe_ans = esc(ans).replace(chr(10), "<br>")
                        _html(f'<div class="chat-msg-ai">{safe_ans}{srcs_html}</div>')

                # Рендер текущей (in-memory) истории — если совушка не перезапускалась
                with chat_column:
                    for msg in state.get("chat_history", []):
                        _render_msg(msg)

                async def _load_history():
                    # Если история пришла из вкладки ИСТОРИЯ — рендерим её
                    if state.get("load_session_id"):
                        sid = state["load_session_id"]
                        state["load_session_id"] = None
                        state["session_id"] = sid
                        hist = state.get("chat_history", [])
                        chat_column.clear()
                        with chat_column:
                            _html('<div class="chat-msg-sys">Сессия загружена из истории.</div>')
                            for m in hist:
                                _render_msg(m)
                        chat_scroll.scroll_to(percent=1)
                        return
                    if not state.get("chat_history"):
                        hist = await api_get("/api/chat/history?limit=40")
                        if hist:
                            state["chat_history"] = hist
                            chat_column.clear()
                            with chat_column:
                                _html('<div class="chat-msg-sys">История загружена.</div>')
                                for m in hist:
                                    _render_msg(m)
                            chat_scroll.scroll_to(percent=1)

                ui.timer(0.5, lambda: asyncio.create_task(_load_history()), once=True)

                # Следим за переходом из вкладки ИСТОРИЯ
                async def _watch_session_load():
                    if state.get("load_session_id"):
                        await _load_history()

                ui.timer(0.5, lambda: asyncio.create_task(_watch_session_load()))

                # Ввод + кнопка
                with ui.row().classes("w-full gap-2 items-end"):
                    chat_input = ui.textarea(
                        placeholder="Запрос по нормативам или проекту... (Enter — отправить, Shift+Enter — перенос)"
                    ).classes("flex-1").style(
                        "background:var(--bg);border:1px solid var(--border);color:var(--text);"
                        "font-family:var(--font);border-radius:4px;font-size:.8rem;resize:none;"
                    ).props("rows=2 autogrow")

                    with ui.column().classes("gap-1"):
                        send_btn = ui.button(
                            "▶ ОТПРАВИТЬ",
                            on_click=lambda: asyncio.create_task(send_chat())
                        ).props("no-caps").style(
                            "background:transparent;border:1px solid var(--ok);color:var(--ok);"
                            "font-family:var(--font);font-weight:900;font-size:.7rem;white-space:nowrap;"
                        )
                        ui.button(
                            "✕ ОЧИСТИТЬ",
                            on_click=lambda: _clear_chat()
                        ).props("no-caps flat").style(
                            "font-size:.6rem;color:var(--dim);"
                        )

        # ── ПРАВАЯ ПАНЕЛЬ: ФОРМА ЗАПРОСА ───────
        with chat_split.after:
            with ui.column().classes("w-full h-full gap-0").style(
                "background:var(--bg-panel);border-left:1px solid var(--border);"
                "overflow-y:auto;"
            ):
                # Заголовок панели
                _html(
                    '<div style="padding:10px 14px;background:var(--bg-mod);border-bottom:1px solid var(--border);">'
                    '<span style="font-size:.75rem;font-weight:900;letter-spacing:.5px;color:var(--accent);">'
                    'ФОРМА ЗАПРОСА</span>'
                    '<span style="font-size:.6rem;color:var(--dim);margin-left:8px;">формат · параметры · образец</span>'
                    '</div>'
                )

                with ui.column().classes("w-full gap-3 p-3"):

                    # ── 1. ФОРМАТ ВЫДАЧИ ──────────────────
                    with ui.card().classes("card-les w-full"):
                        _html('<div class="section-title" style="margin-bottom:10px;">① ФОРМАТ ВЫДАЧИ</div>')

                        OUTPUT_FORMATS = {
                            "text":      ("📝", "Текст",        "Свободный текст, абзацы"),
                            "spec":      ("📋", "Спецификация", "Таблица изделий: поз./марка/кол-во"),
                            "schema":    ("🗂",  "Схема",        "Иерархия/классификатор в виде дерева"),
                            "structure": ("🏗",  "Структура",    "JSON-объект с вложенностью"),
                            "table":     ("📊", "Таблица",      "Произвольная таблица (AG Grid)"),
                            "mermaid":   ("🔀", "Диаграмма",    "Mermaid: flowchart/sequence/ER"),
                            "svg":       ("🖼",  "SVG",          "Векторная схема/план"),
                            "template":  ("📎", "По образцу",   "Структура из загруженного файла"),
                        }

                        out_mode_val = {"v": "text"}
                        format_btns = {}

                        with ui.grid(columns=2).classes("w-full gap-1"):
                            for key, (icon, label, hint) in OUTPUT_FORMATS.items():
                                btn = ui.button(
                                    f"{icon} {label}",
                                ).props("no-caps flat").style(
                                    "font-size:.65rem;font-weight:700;text-align:left;justify-content:flex-start;"
                                    "padding:6px 8px;border:1px solid var(--border);border-radius:4px;"
                                    "color:var(--dim);background:var(--bg);width:100%;"
                                )
                                format_btns[key] = btn

                        format_hint_lbl = ui.label("Свободный текст, абзацы").style(
                            "font-size:.6rem;color:var(--dim);margin-top:4px;font-style:italic;"
                        )

                        def select_format(key):
                            out_mode_val["v"] = key
                            icon, label, hint = OUTPUT_FORMATS[key]
                            format_hint_lbl.set_text(hint)
                            for k, b in format_btns.items():
                                if k == key:
                                    b.style(
                                        "font-size:.65rem;font-weight:900;text-align:left;justify-content:flex-start;"
                                        "padding:6px 8px;border:1px solid var(--accent);border-radius:4px;"
                                        "color:var(--accent);background:rgba(59,130,246,.1);width:100%;"
                                    )
                                else:
                                    b.style(
                                        "font-size:.65rem;font-weight:700;text-align:left;justify-content:flex-start;"
                                        "padding:6px 8px;border:1px solid var(--border);border-radius:4px;"
                                        "color:var(--dim);background:var(--bg);width:100%;"
                                    )
                            mermaid_opts_row.set_visibility(key == "mermaid")
                            svg_opts_row.set_visibility(key == "svg")
                            spec_opts_row.set_visibility(key == "spec")
                            schema_opts_row.set_visibility(key == "schema")
                            template_row.set_visibility(key == "template")
                            _update_prompt_preview()

                        for key in OUTPUT_FORMATS:
                            format_btns[key].on("click", lambda k=key: select_format(k))

                    # ── 2. ПАРАМЕТРЫ ФОРМАТОВ ──────────────────
                    with ui.card().classes("card-les w-full"):
                        _html('<div class="section-title" style="margin-bottom:8px;">② ПАРАМЕТРЫ</div>')

                        mermaid_opts_row = ui.column().classes("w-full gap-2")
                        with mermaid_opts_row:
                            mermaid_type = ui.select(
                                ["flowchart TD", "flowchart LR", "sequenceDiagram",
                                 "erDiagram", "gantt", "classDiagram", "mindmap"],
                                value="flowchart TD",
                                label="Тип диаграммы"
                            ).style("font-size:.72rem;width:100%;")
                        mermaid_opts_row.set_visibility(False)

                        svg_opts_row = ui.column().classes("w-full gap-2")
                        with svg_opts_row:
                            svg_type = ui.select(
                                ["Аксонометрическая схема", "План помещения",
                                 "Функциональная схема", "Принципиальная схема",
                                 "Организационная структура", "Диаграмма потоков"],
                                value="Функциональная схема",
                                label="Тип схемы SVG"
                            ).style("font-size:.72rem;width:100%;")
                            svg_size = ui.select(
                                ["800×600", "1200×800", "600×400", "1600×900"],
                                value="800×600",
                                label="Размер (px)"
                            ).style("font-size:.72rem;width:100%;")
                        svg_opts_row.set_visibility(False)

                        spec_opts_row = ui.column().classes("w-full gap-2")
                        with spec_opts_row:
                            spec_type = ui.select(
                                ["Спецификация оборудования (по ГОСТ 21.110)",
                                 "Ведомость чертежей (ГОСТ 21.101)",
                                 "Ведомость ссылочных документов",
                                 "Спецификация материалов",
                                 "Перечень элементов (ПЭ3)"],
                                value="Спецификация оборудования (по ГОСТ 21.110)",
                                label="Тип спецификации"
                            ).style("font-size:.72rem;width:100%;")
                            spec_group = ui.switch("Группировать по разделам").style("font-size:.72rem;")
                            spec_gost = ui.switch("Строгий формат ГОСТ", value=True).style("font-size:.72rem;")
                        spec_opts_row.set_visibility(False)

                        schema_opts_row = ui.column().classes("w-full gap-2")
                        with schema_opts_row:
                            schema_depth = ui.number(
                                "Глубина вложенности", value=3, min=1, max=6, step=1
                            ).style("font-size:.72rem;width:100%;")
                            schema_format = ui.select(
                                ["JSON дерево", "Маркированный список", "Нумерованный список", "YAML"],
                                value="JSON дерево",
                                label="Формат схемы"
                            ).style("font-size:.72rem;width:100%;")
                        schema_opts_row.set_visibility(False)

                        template_row = ui.column().classes("w-full gap-2")
                        with template_row:
                            ui.label("Загрузи файл-образец (JSON, CSV, XLSX — первые 3 строки как шаблон)").style(
                                "font-size:.65rem;color:var(--dim);"
                            )
                            ui.upload(
                                auto_upload=True,
                                on_upload=lambda e: asyncio.create_task(load_output_template(e))
                            ).props("flat accept=.json,.csv,.xlsx").classes("w-full")
                            template_lbl = ui.label("").style("font-size:.65rem;color:var(--ok);")
                            template_preview = _html("").style(
                                "font-size:.65rem;color:var(--dim);max-height:80px;overflow:auto;"
                                "background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px;"
                                "white-space:pre;font-family:var(--font);"
                            )
                        template_row.set_visibility(False)

                        with ui.row().classes("items-center gap-3 mt-2"):
                            separate_output_sw = ui.switch(
                                "Показать результат отдельной панелью", value=True
                            ).style("font-size:.7rem;")

                    # ── 3. ДЕТАЛИ ЗАПРОСА ──────────────────
                    with ui.card().classes("card-les w-full"):
                        _html('<div class="section-title" style="margin-bottom:8px;">③ ДЕТАЛИ ЗАПРОСА</div>')

                        detail_dataset = ui.select(
                            [], label="Датасет (опционально)"
                        ).style("font-size:.72rem;width:100%;")
                        ui.label("Если выбран — поиск только по этому индексу").style(
                            "font-size:.6rem;color:var(--dim);margin-top:-4px;"
                        )

                        detail_depth = ui.select(
                            ["Кратко (1-2 абзаца)", "Стандарт (3-5 абзацев)",
                             "Подробно (развёрнутый ответ)", "Максимум (полный анализ)"],
                            value="Стандарт (3-5 абзацев)",
                            label="Детальность"
                        ).style("font-size:.72rem;width:100%;margin-top:8px;")

                        detail_lang = ui.select(
                            ["Русский (технический)", "Русский (нормативный ГОСТ)",
                             "Краткие тезисы", "Для презентации"],
                            value="Русский (технический)",
                            label="Стиль ответа"
                        ).style("font-size:.72rem;width:100%;")

                        reranker_sw = ui.switch("Реранкер", value=False).style(
                            "font-size:.72rem;margin-top:4px;"
                        )
                        ui.label("Улучшает подбор чанков, замедляет ответ ~5–10с").style(
                            "font-size:.6rem;color:var(--dim);margin-top:-4px;"
                        )

                        detail_extra = ui.textarea(
                            label="Дополнительные требования"
                        ).props("rows=2").style(
                            "font-size:.72rem;width:100%;background:var(--bg);"
                            "border:1px solid var(--border);color:var(--text);border-radius:4px;"
                        )

                        async def _load_datasets_select():
                            await refresh_samovar()
                            names = [s.get("folder", "") for s in state["sources"]]
                            detail_dataset.options = ["(все датасеты)"] + names
                            detail_dataset.value = "(все датасеты)"

                        ui.timer(0.5, lambda: asyncio.create_task(_load_datasets_select()), once=True)

                    # ── 4. ПРЕВЬЮ ПРОМПТА ──────────────────
                    with ui.card().classes("card-les w-full"):
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html('<div class="section-title">④ ПРОМПТ</div>')
                            ui.button("↻", on_click=lambda: _update_prompt_preview()).props("flat").style(
                                "font-size:.7rem;color:var(--dim);"
                            )

                        prompt_preview = _html("").style(
                            "font-size:.65rem;color:var(--dim);background:var(--bg);"
                            "border:1px solid var(--border);border-radius:4px;padding:8px;"
                            "white-space:pre-wrap;font-family:var(--font);max-height:120px;overflow:auto;"
                        )

                    # ── КНОПКА ПРИМЕНИТЬ ───────────────────
                    apply_btn = ui.button(
                        "▶ ПРИМЕНИТЬ ФОРМУ И ОТПРАВИТЬ",
                        on_click=lambda: asyncio.create_task(send_with_form())
                    ).props("no-caps").classes("w-full").style(
                        "background:rgba(59,130,246,.15);border:1px solid var(--accent);"
                        "color:var(--accent);font-family:var(--font);font-weight:900;font-size:.75rem;"
                        "padding:10px;"
                    )

    # ── ПАНЕЛЬ РЕЗУЛЬТАТА ──────
    result_panel = ui.column().classes("w-full")

    # ─────────────────────────────────────────
    # ЛОГИКА
    # ─────────────────────────────────────────

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
            template_lbl.set_text(f"✓ {fname} ({len(tmpl)} строк)")
            if tmpl:
                preview_str = json.dumps(tmpl[0], ensure_ascii=False, indent=2)
                template_preview.set_content(
                    f'<pre style="margin:0;font-size:.62rem;color:var(--ok);">{preview_str}</pre>'
                )
            add_log(f"[ШАБЛОН] Загружен {fname} · {len(tmpl)} строк")
            _update_prompt_preview()
            ui.notify(f"Образец загружен: {fname}", type="positive")
        except Exception as ex:
            ui.notify(f"Ошибка парсинга: {ex}", type="negative")
            add_log(f"[ШАБЛОН] Ошибка: {ex}")

    def _build_extra_prompt(question: str) -> str:
        mode = out_mode_val["v"]
        depth_map = {
            "Кратко (1-2 абзаца)":          "Ответь кратко — 1-2 абзаца.",
            "Стандарт (3-5 абзацев)":       "Ответь развёрнуто — 3-5 абзацев.",
            "Подробно (развёрнутый ответ)": "Дай полный развёрнутый ответ со всеми деталями.",
            "Максимум (полный анализ)":     "Проведи максимально подробный анализ. Не сокращай.",
        }
        style_map = {
            "Русский (технический)":      "Пиши профессиональным техническим языком.",
            "Русский (нормативный ГОСТ)": "Пиши в нормативном стиле ГОСТ: чёткие формулировки, без лирики.",
            "Краткие тезисы":             "Отвечай тезисами — каждый пункт одна мысль.",
            "Для презентации":            "Формат для слайдов: заголовок + маркированный список.",
        }

        parts = []
        depth_inst = depth_map.get(detail_depth.value, "")
        style_inst = style_map.get(detail_lang.value, "")
        if depth_inst: parts.append(depth_inst)
        if style_inst: parts.append(style_inst)

        if mode == "spec":
            gost_str = " строго по форме ГОСТ 21.110-2013" if spec_gost.value else ""
            group_str = " Группируй по разделам." if spec_group.value else ""
            parts.append(
                f"\n\nВЫВЕДИ ОТВЕТ В ФОРМАТЕ СПЕЦИФИКАЦИИ{gost_str}.\n"
                f"Тип: {spec_type.value}.{group_str}\n"
                f"Верни JSON-массив объектов. Обязательные поля для оборудования: "
                f"поз, обозначение, наименование, тип_марка, ед_изм, кол_во, масса_ед, примечание.\n"
                f"Оберни в ```json ... ```"
            )
        elif mode == "schema":
            depth = int(schema_depth.value) if schema_depth.value else 3
            fmt = schema_format.value
            if fmt == "JSON дерево":
                parts.append(
                    f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ ИЕРАРХИЧЕСКОЙ СХЕМЫ (JSON дерево, глубина {depth}).\n"
                    f"Структура узла: {{\"name\": str, \"children\": [...], \"desc\": str}}.\n"
                    f"Оберни в ```json ... ```"
                )
            elif fmt == "YAML":
                parts.append(f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ YAML-ДЕРЕВА (глубина {depth}).\nОберни в ```yaml ... ```")
            else:
                parts.append(f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ {fmt.upper()} (глубина {depth} уровней).")
        elif mode == "structure":
            parts.append("\n\nВЫВЕДИ ОТВЕТ В ВИДЕ СТРУКТУРИРОВАННОГО JSON-ОБЪЕКТА.\nОберни в ```json ... ```")
        elif mode == "table":
            parts.append("\n\nВЫВЕДИ ОТВЕТ В ВИДЕ ТАБЛИЦЫ — JSON-массив объектов.\nОберни в ```json ... ```")
        elif mode == "mermaid":
            mtype = mermaid_type.value if hasattr(mermaid_type, 'value') else "flowchart TD"
            parts.append(
                f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ MERMAID-ДИАГРАММЫ типа {mtype}.\n"
                f"Оберни в ```mermaid ... ```\n"
                f"Пиши на русском языке. Используй короткие метки узлов."
            )
        elif mode == "svg":
            w, h = svg_size.value.split("×") if "×" in svg_size.value else ("800", "600")
            parts.append(
                f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ SVG-СХЕМЫ ({svg_type.value}).\n"
                f"Размер viewBox: 0 0 {w} {h}. Тёмный фон #1a1e25, белый текст #ffffff.\n"
                f"Оберни в ```svg ... ```"
            )
        elif mode == "template":
            tmpl = state.get("output_template")
            if tmpl:
                parts.append(
                    f"\n\nОТВЕЧАЙ СТРОГО ПО СТРУКТУРЕ ОБРАЗЦА (JSON-массив).\n"
                    f"Образец:\n```json\n{json.dumps(tmpl[:3], ensure_ascii=False, indent=2)}\n```\n"
                    f"Оберни в ```json ... ```"
                )
            else:
                parts.append("\n\nОТВЕЧАЙ В ВИДЕ JSON-МАССИВА ОБЪЕКТОВ. Оберни в ```json ... ```")

        if detail_extra.value.strip():
            parts.append(f"\n\nДОПОЛНИТЕЛЬНО: {detail_extra.value.strip()}")

        return " ".join(p for p in parts[:2]) + "".join(parts[2:])

    def _update_prompt_preview():
        q = chat_input.value.strip() or "[текст запроса]"
        extra = _build_extra_prompt(q)
        preview_text = (q + extra)[:800] + ("…" if len(q + extra) > 800 else "")
        safe_preview = esc(preview_text)
        prompt_preview.set_content(
            f'<pre style="margin:0;font-size:.63rem;color:var(--dim);white-space:pre-wrap;">{safe_preview}</pre>'
        )

    chat_input.on("input", lambda: _update_prompt_preview())

    def _clear_chat():
        from sovushka.state import _new_session_id
        chat_column.clear()
        with chat_column:
            _html('<div class="chat-msg-sys">Чат очищен.</div>')
        result_panel.clear()
        state["chat_history"].clear()
        state["session_id"] = _new_session_id()
        state["load_session_id"] = None
        add_log("[ЧАТ] История очищена, новая сессия")

    _sending = {"v": False}

    async def _do_send(question: str):
        if _sending["v"]:
            return
        _sending["v"] = True
        send_btn.props("disabled")
        apply_btn.props("disabled")
        chat_input.props("disabled")
        out_mode = out_mode_val["v"]

        # Сохраняем вопрос СРАЗУ — до await, чтобы пережить реконнект
        state["chat_history"].append({"role": "user", "text": question})

        with chat_column:
            safe_q = esc(question)
            _html(f'<div class="chat-msg-user">{safe_q}</div>')
        chat_scroll.scroll_to(percent=1)
        add_log(f'[AI] Запрос: "{question[:60]}"')

        with chat_column:
            ai_placeholder = _html('<div class="chat-msg-ai typing">⟳ Генерирую... 0с</div>')
        chat_scroll.scroll_to(percent=1)

        extra_prompt = _build_extra_prompt(question)
        payload = {
            "question": question + extra_prompt,
            "reranker_enabled": reranker_sw.value,
            "session_id": state.get("session_id"),
        }
        if detail_dataset.value and detail_dataset.value != "(все датасеты)":
            payload["dataset_filter"] = detail_dataset.value

        # Тикер: обновляем placeholder каждую секунду
        _t0 = time.monotonic()
        _stop_tick = {"v": False}

        async def _tick():
            spin = ["⟳", "↻", "⟲", "↺"]
            i = 0
            while not _stop_tick["v"]:
                elapsed = int(time.monotonic() - _t0)
                s = spin[i % len(spin)]
                ai_placeholder.set_content(
                    f'<div class="chat-msg-ai typing">{s} Генерирую... {elapsed}с</div>'
                )
                i += 1
                await asyncio.sleep(1)

        _tick_task = asyncio.create_task(_tick())

        try:
            d = await api_post("/api/chat", payload)
            if d:
                ans  = d.get("answer", d.get("response", "Нет ответа"))
                srcs = d.get("sources", [])
                crag = d.get("crag_status", "")

                state["chat_history"].append({"role": "ai", "text": ans, "srcs": srcs, "crag": crag})

                srcs_html = ""
                if srcs:
                    tags = "".join(f'<span class="src-tag">{esc(s.get("file", s) if isinstance(s, dict) else s)}</span>' for s in srcs)
                    srcs_html = f'<div class="msg-srcs" style="margin-top:8px;">{tags}</div>'
                if crag:
                    cls = "src-tag" if crag == "VERIFIED" else "src-tag src-tag-err"
                    srcs_html += f'<span class="{cls}" style="margin-left:4px;">Т.О.С.К.А.: {esc(crag)}</span>'

                safe_ans = esc(ans).replace(chr(10), "<br>")
                ai_placeholder.set_content(
                    f'<div class="chat-msg-ai">{safe_ans}{srcs_html}</div>'
                )

                if separate_output_sw.value:
                    result_panel.clear()
                    try:
                        _render_result(ans, out_mode, result_panel)
                    except Exception as render_ex:
                        with result_panel:
                            ui.label(f"Ошибка рендера: {render_ex}").style("color:var(--err);font-size:.75rem;")

                add_log(f"[AI] Формат:{out_mode} CRAG:{crag or 'N/A'} src:{len(srcs)}")
            else:
                ai_placeholder.set_content('<div class="chat-msg-ai" style="color:var(--err);">Ошибка запроса</div>')
        except Exception as ex:
            ai_placeholder.set_content(f'<div class="chat-msg-ai" style="color:var(--err);">Ошибка: {ex}</div>')
        finally:
            _stop_tick["v"] = True
            _tick_task.cancel()
            _sending["v"] = False
            send_btn.props(remove="disabled")
            apply_btn.props(remove="disabled")
            chat_input.props(remove="disabled")
            chat_scroll.scroll_to(percent=1)

    async def send_chat():
        q = chat_input.value.strip()
        if not q: return
        chat_input.value = ""
        await _do_send(q)

    async def send_with_form():
        q = chat_input.value.strip()
        if not q:
            ui.notify("Введите текст запроса", type="warning")
            return
        chat_input.value = ""
        _update_prompt_preview()
        await _do_send(q)

    # ── Рендер результатов ──
    def _render_result(ans: str, mode: str, container):
        with container:
            with ui.card().classes("card-les w-full"):
                if mode == "text":
                    with ui.row().classes("items-center justify-between mb-2"):
                        _html('<div class="section-title">РЕЗУЛЬТАТ // ТЕКСТ</div>')
                        ui.button("📋 Копировать", on_click=lambda: ui.clipboard.write(ans)).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                    ui.markdown(ans).style("font-size:.8rem;line-height:1.6;color:var(--text);")
                elif mode == "spec":
                    _html('<div class="section-title mb-2">РЕЗУЛЬТАТ // СПЕЦИФИКАЦИЯ</div>')
                    data = _parse_table_from_ai(ans)
                    if data:
                        _render_spec_table(data)
                    else:
                        ui.markdown(ans).style("font-size:.78rem;")
                elif mode == "schema":
                    _html('<div class="section-title mb-2">РЕЗУЛЬТАТ // СХЕМА</div>')
                    data = _parse_json_from_ai(ans)
                    if data:
                        _render_tree(data)
                    else:
                        ui.markdown(ans).style("font-size:.78rem;")
                elif mode in ("structure", "table", "template"):
                    lbl = {"structure": "СТРУКТУРА", "table": "ТАБЛИЦА", "template": "ПО ОБРАЗЦУ"}[mode]
                    _html(f'<div class="section-title mb-2">РЕЗУЛЬТАТ // {lbl}</div>')
                    data = _parse_table_from_ai(ans) or _parse_json_from_ai(ans)
                    if isinstance(data, list) and data:
                        keys = list(data[0].keys()) if isinstance(data[0], dict) else ["значение"]
                        cols = [{"headerName": k, "field": k, "flex": 1, "filter": True, "sortable": True, "resizable": True} for k in keys]
                        rows = data if isinstance(data[0], dict) else [{"значение": str(r)} for r in data]
                        ui.table(columns=cols, rows=rows).classes("w-full") # table since aggrid doesn't render lines
                        with ui.row().classes("gap-2 mt-2"):
                            ui.button("📋 JSON", on_click=lambda d=data: ui.clipboard.write(json.dumps(d, ensure_ascii=False, indent=2))).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                    elif isinstance(data, dict):
                        ui.markdown(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```").style("font-size:.75rem;")
                    else:
                        ui.markdown(ans).style("font-size:.78rem;")
                elif mode == "mermaid":
                    _html('<div class="section-title mb-2">РЕЗУЛЬТАТ // ДИАГРАММА</div>')
                    code = _parse_mermaid_from_ai(ans)
                    if code:
                        state["mermaid_last"] = code
                        ui.mermaid(code)
                        with ui.row().classes("gap-2 mt-2"):
                            ui.button("📋 Копировать код", on_click=lambda c=code: ui.clipboard.write(c)).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                            if tabs and tab_mermaid:
                                ui.button("→ В редактор", on_click=lambda: tabs.set_value(tab_mermaid)).props("no-caps flat").style("font-size:.65rem;color:var(--pauk);")
                    else:
                        ui.markdown(ans).style("font-size:.78rem;")
                elif mode == "svg":
                    _html('<div class="section-title mb-2">РЕЗУЛЬТАТ // SVG СХЕМА</div>')
                    svg_code = _parse_svg_from_ai(ans)
                    if svg_code:
                        ui.code(svg_code, language="xml").classes("w-full")
                        ui.button("📋 Копировать SVG", on_click=lambda c=svg_code: ui.clipboard.write(c)).props("no-caps flat").style("font-size:.65rem;color:var(--accent);mt-2")
                    else:
                        ui.markdown(ans).style("font-size:.78rem;")

    # ── Вспомогательные парсеры ──
    def _parse_table_from_ai(text: str):
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try: return json.loads(m.group(1))
            except: pass
        return None

    def _parse_json_from_ai(text: str):
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if m:
            try: return json.loads(m.group(1))
            except: pass
        try:
            start = text.find("{") if "{" in text else text.find("[")
            if start >= 0:
                end = text.rfind("}") if "{" in text else text.rfind("]")
                return json.loads(text[start:end+1])
        except: pass
        return None

    def _parse_mermaid_from_ai(text: str) -> Optional[str]:
        m = re.search(r"```mermaid\s*(.*?)```", text, re.DOTALL)
        return m.group(1).strip() if m else None

    def _parse_svg_from_ai(text: str) -> Optional[str]:
        m = re.search(r"```svg\s*(.*?)```", text, re.DOTALL)
        if m: return m.group(1).strip()
        m2 = re.search(r"(<svg[\s\S]*?</svg>)", text, re.IGNORECASE)
        return m2.group(1).strip() if m2 else None

    def _render_spec_table(data: list[dict]):
        if not data: return
        keys = list(data[0].keys())
        cols = [{"name": k, "label": k, "field": k, "align": "left", "sortable": True} for k in keys]
        ui.table(columns=cols, rows=data).classes("w-full").style("background:var(--bg-panel);color:var(--text);font-family:var(--font);")
        with ui.row().classes("gap-2 mt-2"):
            ui.button("📋 JSON", on_click=lambda d=data: ui.clipboard.write(json.dumps(d, ensure_ascii=False, indent=2))).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")

    def _render_tree(data, level: int = 0):
        if isinstance(data, dict):
            name = data.get("name", data.get("title", data.get("id", "—")))
            desc = data.get("desc", data.get("description", ""))
            children = data.get("children", data.get("items", []))
            indent = level * 16
            with ui.row().classes("items-start gap-1").style(f"margin-left:{indent}px;"):
                _html(f'<span style="color:var(--accent);font-weight:700;font-size:.75rem;">{"▶" if children else "•"}</span>'
                      f'<span style="font-size:.75rem;font-weight:{"700" if level==0 else "400"};color:var(--text);">{esc(name)}</span>'
                      + (f'<span style="font-size:.65rem;color:var(--dim);margin-left:4px;">{esc(desc)}</span>' if desc else ""))
            for child in (children if isinstance(children, list) else []):
                _render_tree(child, level + 1)
        elif isinstance(data, list):
            for item in data: _render_tree(item, level)

    ui.timer(0.1, lambda: select_format("text"), once=True)
    chat_input.on("keydown.enter.prevent", lambda e: asyncio.create_task(send_chat()) if not (e.args or {}).get("shiftKey") else None)
