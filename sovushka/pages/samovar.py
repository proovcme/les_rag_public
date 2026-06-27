"""
С.О.В.У.Ш.К.А. v5.0 — Вкладка С.А.М.О.В.А.Р. (RAG-индекс)
"""
from __future__ import annotations

import asyncio
from html import escape
from datetime import datetime
from urllib.parse import quote, urlencode
from nicegui import context, ui

from sovushka.state import (
    state,
    api_get,
    api_post,
    api_patch,
    api_delete,
    add_log,
    refresh_proxy_logs,
    refresh_samovar,
    last_api_error_text,
)


def build_samovar():
    """Датасеты (v0.24) — таблица/карточки, светофор статуса, бар файлов, Пуск/Стоп/Ремонт,
    ошибка→что делать, диалог файлов, одна кнопка «Добавить». На API proxy/routers/datasets."""
    _S = {"mode": "table", "rows": [], "q": "", "filter": "all"}
    _refs = {"disp": None, "kpi": None, "status": None, "tbtn": None, "cbtn": None}

    def _error_hint(err: str) -> str:
        e = (err or "").lower()
        if any(k in e for k in ("memory", "память", "swap", "oom")):
            return "Память: уменьшить batch/cooldown, выгрузить MLX, затем Ремонт"
        if any(k in e for k in ("timeout", "таймаут", "1800")):
            return "Завис/большой: меньший лимит парсинга, затем Ремонт"
        if any(k in e for k in ("not found", "не найден", "no such file")):
            return "Файл переехал/удалён: пересинк папки-источника"
        if any(k in e for k in ("corrupt", "поврежд", "no stream")):
            return "Файл повреждён: пересоздать или пропустить"
        if any(k in e for k in ("unsupported", "не поддерж")):
            return "Формат не поддержан: конвертировать в pdf/docx"
        return "Открой список файлов — точный текст ошибки"

    def _agg(docs):
        by = {}
        for d in (docs or {}).get("documents", []):
            s = by.setdefault(d.get("dataset_id"), {"INDEXED": 0, "PENDING": 0, "ERROR": 0, "chunks": 0})
            st = d.get("status", "")
            if st in s and st != "chunks":
                s[st] += 1
            s["chunks"] += int(d.get("chunk_count") or 0)
        return by

    async def _load():
        ds = await api_get("/api/rag/datasets") or []
        # Эндпоинт документов капит лимит на 500 (le=500): limit>500 → 422 → пусто (баг v1).
        # Пагинируем по 500, агрегируем все.
        all_docs = []
        offset = 0
        while True:
            page = await api_get(f"/api/rag/documents?limit=500&offset={offset}")
            items = (page or {}).get("documents", []) if isinstance(page, dict) else []
            all_docs.extend(items)
            if len(items) < 500 or offset >= 30000:
                break
            offset += 500
        agg = _agg({"documents": all_docs})
        rows = []
        for d in (ds if isinstance(ds, list) else ds.get("datasets", []) or []):
            did = d.get("id") or d.get("dataset_id")
            a = agg.get(did, {"INDEXED": 0, "PENDING": 0, "ERROR": 0, "chunks": 0})
            tot = a["INDEXED"] + a["PENDING"] + a["ERROR"]
            rows.append({"id": did, "name": d.get("name", "?"), "sensitivity": d.get("sensitivity", "P0"),
                         "group": d.get("group_name", ""), "indexed": a["INDEXED"], "pending": a["PENDING"],
                         "error": a["ERROR"], "chunks": a["chunks"] or int(d.get("chunk_count") or 0), "total": tot})
        rows.sort(key=lambda r: (0 if r["error"] else 1, 0 if r["pending"] else 1, r["name"].lower()))
        _S["rows"] = rows

    def _light(r):
        if r["error"]:
            return ("var(--err)", f"{r['error']} ошибок", "o_error")
        if r["pending"]:
            return ("var(--warn)", f"Парсинг {r['indexed']}/{r['total']}", "o_sync")
        if r["indexed"]:
            return ("var(--ok)", "Готов", "o_check_circle")
        return ("var(--dim)", "Пусто", "o_remove")

    def _bar(r):
        with ui.element("div").style("height:7px;border-radius:4px;overflow:hidden;display:flex;"
                                     "background:var(--bg-mod);min-width:120px;"):
            for n, col in ((r["indexed"], "var(--ok)"), (r["pending"], "var(--warn)"), (r["error"], "var(--err)")):
                if n:
                    ui.element("div").style(f"flex:{n};background:{col};")

    async def _parse(r):
        # «Плей» = одна СИНХРОННАЯ партия ≤25 файлов (endpoint ждёт до конца). Даём честный сигнал:
        # старт сразу (notify+лог), затем результат со счётчиками — чтобы не было «идёт или стоит?».
        nm = r.get("name", "?")
        add_log(f"[ПАРС] ▶ {nm}: партия до 25 файлов…")
        ui.notify(f"▶ Парсинг «{nm}» — партия до 25 файлов…", type="info")
        try:
            d = await api_post(f"/api/rag/parse-batch/{r['id']}?limit=25", {})
        except Exception as e:  # noqa: BLE001
            add_log(f"[ПАРС] ✗ {nm}: {e}")
            ui.notify(last_api_error_text(f"Парсинг «{nm}» не запустился"), type="negative")
            return
        if not d:
            add_log(f"[ПАРС] ✗ {nm}: отказ (вероятно, защита памяти — см. статус)")
            ui.notify(last_api_error_text(f"Парсинг «{nm}»: отказ (память?)"), type="negative")
            await _refresh_status()
            return
        res = (d or {}).get("result", {}) or {}
        chunks, errs, rem = res.get("chunks", 0), res.get("errors", 0), res.get("remaining_pending", 0)
        msg = f"✓ «{nm}»: +{chunks} чанков · ошибок {errs} · осталось {rem}"
        if rem:
            msg += " — повтори «плей» или жми «Пуск» (индексатор) для всех"
        add_log(f"[ПАРС] {msg}")
        ui.notify(msg, type="positive" if not errs else "warning")
        await _refresh()

    async def _repair(r):
        d = await api_post(f"/api/rag/datasets/{r['id']}/repair", {})
        n = (d or {}).get("requeued", 0)
        ui.notify(f"Ремонт {r['name']}: в очередь {n} файлов — нажми Пуск" if n else "Ошибочных файлов нет",
                  type="warning" if n else "info")
        await _refresh()

    async def _delete(r):
        ok = await ui.run_javascript(f"confirm('Удалить датасет {r['name']}? Необратимо.')", timeout=10)
        if ok:
            await api_delete(f"/api/rag/datasets/{r['id']}")
            ui.notify(f"Удалён: {r['name']}", type="warning")
            await _refresh()

    async def _start_all():
        await api_post("/api/runtime/dispatcher/reindex/start", {"parse_method": "scheduler"})
        ui.notify("Индексатор запущен", type="positive")
        await _refresh_status()

    async def _stop_all():
        await api_post("/api/runtime/dispatcher/reindex/pause", {"reason": "operator"})
        ui.notify("Индексатор остановлен", type="warning")
        await _refresh_status()

    files_dialog = ui.dialog()

    async def _open_files(r):
        files_dialog.clear()
        with files_dialog, ui.card().classes("sov-advanced-dialog").style("min-width:680px;"):
            with ui.row().classes("items-center w-full").style("gap:10px;"):
                ui.label(r["name"]).classes("sov-panel-title")
                ui.label(f"{r['total']} файлов · {r['indexed']} в индексе · {r['pending']} ждут · "
                         f"{r['error']} ошибок · {r['chunks']} чанков").classes("sov-muted")
                ui.element("div").style("flex:1;")
                if r["error"]:
                    ui.button("Ремонт", icon="o_build",
                              on_click=lambda rr=r: asyncio.create_task(_repair(rr))).props("flat dense no-caps").style("color:var(--accent);")
            flist = ui.column().classes("w-full sov-advanced-scroll").style("gap:0;")
        files_dialog.open()
        d = await api_get(f"/api/rag/documents?dataset_id={r['id']}&limit=1500") or {}
        flist.clear()
        with flist:
            for it in d.get("documents", []):
                st = it.get("status", "")
                col = "var(--ok)" if st == "INDEXED" else "var(--warn)" if st == "PENDING" else "var(--err)"
                with ui.row().classes("items-center w-full").style(
                        "gap:8px;padding:6px 4px;border-bottom:1px solid var(--border);"):
                    ui.icon("o_circle").style(f"font-size:8px;color:{col};")
                    ui.label((it.get("file_name") or "?")[-70:]).style("font-size:13px;flex:1;overflow:hidden;")
                    ui.label(st).style(f"font-size:11.5px;color:{col};")
                if st == "ERROR" and it.get("last_error"):
                    with ui.row().classes("w-full").style("gap:6px;padding:0 4px 6px 20px;"):
                        ui.label(f"{(it.get('last_error') or '')[:90]} → {_error_hint(it.get('last_error'))}").style(
                            "font-size:11.5px;color:var(--err);opacity:.85;")

    add_dialog = ui.dialog()

    def _open_add():
        add_dialog.clear()
        picked = {"path": ""}
        browse = {"path": ""}
        with add_dialog, ui.card().classes("sov-advanced-dialog").style("min-width:560px;"):
            ui.label("Добавить датасет").classes("sov-panel-title")
            ui.label("Папка индексируется in-place (без копии в storage).").classes("sov-muted")
            name_in = ui.input("Название").props("dense outlined").classes("w-full")
            with ui.row().classes("items-center w-full").style("gap:8px;"):
                path_lbl = ui.label("Папка не выбрана").style(
                    "flex:1;font-size:13px;color:var(--dim);border:1px solid var(--border);"
                    "border-radius:8px;padding:8px 10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;")
                ui.button("Обзор…", icon="o_folder_open",
                          on_click=lambda: _open_browser()).props("no-caps flat dense").style("color:var(--accent);")
            parse_sw = ui.switch("Сразу индексировать", value=True)

            # вложенный браузер папок (клик-навигация по серверной ФС, без печати пути)
            with ui.dialog() as fdlg, ui.card().style("min-width:520px;max-width:92vw;"):
                ui.label("Выбор папки").classes("sov-panel-title")
                with ui.row().classes("items-center w-full").style("gap:8px;margin:6px 0;"):
                    fb_sel = ui.button("Выбрать эту", icon="o_check",
                                       on_click=lambda: _pick()).props("no-caps").style(
                                       "background:var(--accent);color:var(--bg);border-radius:8px;")
                    ui.button("Отмена", on_click=fdlg.close).props("flat no-caps dense").style("color:var(--dim);")
                    fb_path = ui.label("…").style("flex:1;text-align:right;font-size:12px;"
                                                  "color:var(--accent);word-break:break-all;")
                fb_list = ui.column().classes("w-full").style("max-height:340px;overflow:auto;gap:2px;")

            async def _nav(path=""):
                d = await api_get(f"/api/rag/browse-external?path={quote(path, safe='')}")
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Не удалось открыть папку"), type="negative")
                    return
                browse["path"] = d.get("path", "")
                fb_path.set_text(d.get("path") or "Корни — выбери папку ниже")
                fb_list.clear()
                with fb_list:
                    if d.get("path"):
                        ui.button("↑ Вверх", icon="o_arrow_upward",
                                  on_click=lambda u=d.get("parent"): asyncio.create_task(_nav(u or ""))
                                  ).props("flat dense no-caps").classes("w-full")
                    for e in d.get("dirs", []):
                        ui.button(f"{e['name']}   ·   {e.get('file_count', 0)} файл.", icon="o_folder",
                                  on_click=lambda p=e["path"]: asyncio.create_task(_nav(p))
                                  ).props("flat dense no-caps align=left").classes("w-full")
                    if not d.get("dirs") and d.get("path"):
                        ui.label("Подпапок нет — можно выбрать эту.").classes("sov-muted").style("padding:6px;")
                fb_sel.set_enabled(bool(d.get("path")))

            def _pick():
                if browse["path"]:
                    picked["path"] = browse["path"]
                    path_lbl.set_text(browse["path"])
                    path_lbl.style("color:var(--text);")
                    fdlg.close()

            def _open_browser():
                fdlg.open()
                asyncio.create_task(_nav(""))

            async def _do_add():
                nm = (name_in.value or "").strip()
                pth = picked["path"]
                if not nm or not pth:
                    ui.notify("Нужны название и выбранная папка (Обзор…)", type="negative")
                    return
                ds = await api_post(f"/api/rag/datasets?name={quote(nm)}", {})
                did = (ds or {}).get("id")
                if not did:
                    ui.notify(last_api_error_text("Не удалось создать датасет"), type="negative")
                    return
                # background=True: index-external отвечает мгновенно, регистрация+нарезка+парс — в фоне
                # (большие папки не упираются в HTTP-таймаут 180с; 758 файлов = ~47с регистрации).
                r = await api_post("/api/rag/index-external",
                                   {"path": pth, "dataset_id": did, "parse": bool(parse_sw.value),
                                    "parse_limit": 25, "background": True})
                add_dialog.close()
                if r and r.get("status") in ("started", "registered"):
                    ui.notify(f"Индексация «{nm}» запущена — файлы появятся в датасете", type="positive")
                    await _refresh()
                else:
                    # откат: не плодим пустые датасеты при ошибке (плохой путь, нет документов)
                    await api_delete(f"/api/rag/datasets/{did}")
                    ui.notify(last_api_error_text("Не удалось проиндексировать папку"), type="negative")
                    await _refresh()

            with ui.row().classes("justify-end w-full").style("gap:8px;margin-top:8px;"):
                ui.button("Отмена", on_click=add_dialog.close).props("flat dense no-caps").style("color:var(--dim);")
                ui.button("Индексировать", icon="o_bolt",
                          on_click=lambda: asyncio.create_task(_do_add())).props("no-caps").style(
                          "background:var(--accent);color:var(--bg);border-radius:8px;")
        add_dialog.open()

    def _row_actions(r):
        ui.button(icon="o_folder_open", on_click=lambda rr=r: asyncio.create_task(_open_files(rr))).props(
            'flat dense round aria-label="Файлы"').style("color:var(--dim);")
        if r["error"]:
            ui.button(icon="o_build", on_click=lambda rr=r: asyncio.create_task(_repair(rr))).props(
                'flat dense round aria-label="Ремонт"').style("color:var(--accent);")
        ui.button(icon="o_play_arrow", on_click=lambda rr=r: asyncio.create_task(_parse(rr))).props(
            'flat dense round aria-label="Пуск"').style("color:var(--ok);")
        ui.button(icon="o_delete", on_click=lambda rr=r: asyncio.create_task(_delete(rr))).props(
            'flat dense round aria-label="Удалить"').style("color:var(--dim);")

    def _visible_rows():
        q = (_S.get("q") or "").strip().lower()
        f = _S.get("filter", "all")
        out = []
        for r in _S["rows"]:
            if q and q not in str(r["name"]).lower():
                continue
            if f == "indexed" and not (r["error"] == 0 and r["pending"] == 0 and r["indexed"] > 0):
                continue
            if f == "pending" and r["pending"] <= 0:
                continue
            if f == "error" and r["error"] <= 0:
                continue
            if f == "empty" and r["total"] > 0:
                continue
            out.append(r)
        sk = _S.get("sort")
        if sk:
            keyf = {"files": lambda r: r["total"], "chunks": lambda r: r["chunks"],
                    "name": lambda r: str(r["name"]).lower()}.get(sk)
            if keyf:
                out.sort(key=keyf, reverse=_S.get("sort_dir", -1) < 0)
        return out

    def _render_rows():
        disp = _refs["disp"]
        if disp is None:
            return
        disp.clear()
        with disp:
            if not _S["rows"]:
                ui.label("Датасетов нет — нажми «Добавить».").classes("sov-muted").style("padding:18px;")
                return
            vis = _visible_rows()
            if not vis:
                ui.label("Ничего не найдено по фильтру.").classes("sov-muted").style("padding:18px;")
                return
            if _S["mode"] == "table":
                with ui.element("div").classes("card-les w-full").style("padding:0;overflow:hidden;"):
                    with ui.row().classes("items-center w-full").style(
                            "gap:10px;padding:8px 14px;border-bottom:1px solid var(--border);"
                            "font-size:11.5px;color:var(--dim);"):
                        ui.label("Датасет" + _sort_arrow("name")).style("flex:2;cursor:pointer;").on(
                            "click", lambda: _set_sort("name"))
                        ui.label("Статус").style("flex:1.4;")
                        ui.label("Файлы" + _sort_arrow("files")).style("flex:1.6;cursor:pointer;").on(
                            "click", lambda: _set_sort("files"))
                        ui.label("Чанки" + _sort_arrow("chunks")).style("width:70px;cursor:pointer;").on(
                            "click", lambda: _set_sort("chunks"))
                        ui.label("").style("width:160px;")
                    for r in vis:
                        col, txt, ico = _light(r)
                        with ui.row().classes("items-center w-full").style(
                                "gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);"):
                            ui.label(r["name"]).style("flex:2;font-size:14px;font-weight:500;")
                            with ui.row().classes("items-center").style("flex:1.4;gap:5px;"):
                                ui.icon(ico).style(f"font-size:15px;color:{col};")
                                ui.label(txt).style(f"font-size:12px;color:{col};")
                            with ui.column().style("flex:1.6;gap:2px;"):
                                _bar(r)
                            ui.label(str(r["chunks"])).style("width:70px;font-size:13px;color:var(--text);")
                            with ui.row().classes("items-center justify-end").style("width:160px;gap:0;"):
                                _row_actions(r)
            else:
                with ui.element("div").style(
                        "display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;width:100%;"):
                    for r in vis:
                        col, txt, ico = _light(r)
                        with ui.element("div").classes("card-les").style("padding:12px;"):
                            with ui.row().classes("items-center w-full").style("gap:8px;margin-bottom:8px;"):
                                ui.icon("o_circle").style(f"font-size:9px;color:{col};")
                                ui.label(r["name"]).style("font-size:14px;font-weight:500;flex:1;")
                                ui.label(f"{r['chunks']} чанков").classes("sov-muted")
                            _bar(r)
                            with ui.row().classes("items-center w-full").style("gap:6px;margin-top:8px;"):
                                ui.label(txt).style(f"font-size:12px;color:{col};flex:1;")
                                _row_actions(r)

    async def _refresh_status():
        # Тикает каждые 5с НЕЗАВИСИМО от _parse (который ждёт батч) → ловит «PARSING» датасета
        # живьём: parse_dataset ставит статус PARSING в БД на время партии. Так видно «идёт/стоит».
        st = await api_get("/api/runtime/dispatcher/status") or {}
        disp = bool((st.get("reindex") or {}).get("running") or st.get("running"))
        ds = await api_get("/api/rag/datasets") or []
        ds_list = ds if isinstance(ds, list) else (ds.get("datasets") or [])
        parsing = [d.get("name", "?") for d in ds_list if str(d.get("status", "")).upper() == "PARSING"]
        if _refs["status"]:
            if parsing:
                extra = f" +{len(parsing) - 3}" if len(parsing) > 3 else ""
                _refs["status"].set_text(f"Индексатор: ПАРСИНГ идёт — {', '.join(parsing[:3])}{extra}")
            elif disp:
                _refs["status"].set_text("Индексатор: идёт…")
            else:
                _refs["status"].set_text("Индексатор: простаивает")

    async def _refresh():
        try:
            await _load()
            if _refs.get("stats"):
                rows = _S["rows"]
                vals = {"datasets": len(rows), "files": sum(r["total"] for r in rows),
                        "indexed": sum(r["indexed"] for r in rows), "pending": sum(r["pending"] for r in rows),
                        "error": sum(r["error"] for r in rows), "chunks": sum(r["chunks"] for r in rows)}
                for k, lbl in _refs["stats"].items():
                    lbl.set_text(f"{vals.get(k, 0):,}".replace(",", " "))
            _render_rows()
            await _refresh_status()
        except Exception as exc:  # noqa: BLE001 — рендер не должен ронять страницу
            if _refs["disp"]:
                _refs["disp"].clear()
                with _refs["disp"]:
                    ui.label(f"Ошибка загрузки датасетов: {exc}").style("color:var(--err);padding:16px;")

    def _upd_toggle():
        for key, mode in (("tbtn", "table"), ("cbtn", "cards")):
            if _refs[key]:
                _refs[key].style("color:" + ("var(--accent)" if _S["mode"] == mode else "var(--dim)"))

    def _set_mode(m):
        _S["mode"] = m
        _upd_toggle()
        _render_rows()

    def _set_filter(m):
        _S["filter"] = m
        for key, btn in (_refs.get("fbtn") or {}).items():
            btn.style(f"font-size:.7rem;color:{'var(--accent)' if key == m else 'var(--dim)'};")
        _render_rows()

    def _set_sort(key):
        if _S.get("sort") == key:
            _S["sort_dir"] = -_S.get("sort_dir", -1)
        else:
            _S["sort"] = key
            _S["sort_dir"] = 1 if key == "name" else -1  # имя по возрастанию, числа по убыванию
        _render_rows()

    def _card_click(k):
        # карточки статистики кликабельны: статусные → фильтр, числовые → сортировка
        if k == "datasets":
            _set_filter("all")
        elif k in ("indexed", "pending", "error"):
            _set_filter(k)
        elif k in ("files", "chunks"):
            _set_sort(k)

    def _sort_arrow(key):
        if _S.get("sort") != key:
            return ""
        return " ▼" if _S.get("sort_dir", -1) < 0 else " ▲"

    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-3"):
        with ui.row().classes("items-center w-full").style("gap:12px;flex-wrap:nowrap;"):
            ui.label("Датасеты").style("font-size:20px;font-weight:500;")
            ui.element("div").style("flex:1;")
            with ui.row().classes("items-center").style("border:1px solid var(--border);border-radius:8px;overflow:hidden;"):
                _refs["tbtn"] = ui.button("Таблица", icon="o_table_rows",
                                          on_click=lambda: _set_mode("table")).props("flat dense no-caps")
                _refs["cbtn"] = ui.button("Карточки", icon="o_grid_view",
                                          on_click=lambda: _set_mode("cards")).props("flat dense no-caps")
            ui.button("Добавить", icon="o_add", on_click=_open_add).props("no-caps").style(
                "background:var(--accent);color:var(--bg);border-radius:8px;font-weight:500;")
        # Большая статистика сверху
        _refs["stats"] = {}
        _STAT_DEFS = (("datasets", "Датасеты", "var(--text)"), ("files", "Файлов", "var(--text)"),
                      ("indexed", "В индексе", "var(--ok)"), ("pending", "Ждут", "var(--warn)"),
                      ("error", "Ошибки", "var(--err)"), ("chunks", "Чанков", "var(--accent)"))
        with ui.element("div").style("display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));"
                                     "gap:10px;width:100%;"):
            for _k, _lbl, _col in _STAT_DEFS:
                with ui.element("div").classes("card-les").style("padding:14px 16px;cursor:pointer;").on(
                        "click", lambda k=_k: _card_click(k)).tooltip(
                        "клик: статус → фильтр, число → сортировка"):
                    _refs["stats"][_k] = ui.label("—").style(
                        f"font-size:26px;font-weight:500;line-height:1;color:{_col};font-variant-numeric:tabular-nums;")
                    ui.label(_lbl).style("font-size:12px;color:var(--dim);margin-top:6px;")
        # Фильтр-бар (напрашивался): поиск по имени + фильтр по статусу
        _refs["fbtn"] = {}
        with ui.row().classes("items-center w-full").style("gap:8px;flex-wrap:wrap;"):
            _fsearch = ui.input(placeholder="Поиск датасета…").props("dense outlined clearable").style(
                "min-width:220px;font-size:.72rem;")
            _fsearch.on_value_change(lambda *_: (_S.update(q=(_fsearch.value or "")), _render_rows()))
            with ui.row().classes("items-center").style(
                    "border:1px solid var(--border);border-radius:8px;overflow:hidden;"):
                for _fk, _flbl in (("all", "Все"), ("indexed", "В индексе"), ("pending", "Ждут"),
                                   ("error", "Ошибки"), ("empty", "Пустые")):
                    _refs["fbtn"][_fk] = ui.button(_flbl, on_click=lambda k=_fk: _set_filter(k)).props(
                        "flat dense no-caps").style(
                        f"font-size:.7rem;color:{'var(--accent)' if _fk == 'all' else 'var(--dim)'};")
        with ui.row().classes("items-center w-full").style("gap:10px;"):
            ui.button("Пуск", icon="o_play_arrow",
                      on_click=lambda: asyncio.create_task(_start_all())).props("flat dense no-caps").style("color:var(--ok);")
            ui.button("Стоп", icon="o_pause",
                      on_click=lambda: asyncio.create_task(_stop_all())).props("flat dense no-caps").style("color:var(--dim);")
            ui.element("div").style("width:1px;height:16px;background:var(--border);")
            _refs["status"] = ui.label("Индексатор: …").classes("sov-muted")
            ui.element("div").style("flex:1;")
            ui.button("Обновить", icon="o_refresh",
                      on_click=lambda: asyncio.create_task(_refresh())).props("flat dense no-caps").style("color:var(--dim);")
        _refs["disp"] = ui.column().classes("w-full").style("gap:8px;")

    _upd_toggle()
    asyncio.create_task(_refresh())
    # Авто-обновление: статус индексатора часто и дёшево, полная сводка (счётчики+строки) реже
    ui.timer(5.0, lambda: asyncio.create_task(_refresh_status()))
    ui.timer(20.0, lambda: asyncio.create_task(_refresh()))


def build_samovar_legacy():
    """LEGACY (v0.23 и ранее) — старая страница С.А.М.О.В.А.Р. Сохранена для отката
    (sovushka_ng.py: build_samovar → build_samovar_legacy при проблемах с новой)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.column().classes("gap-0"):
                ui.label("С.А.М.О.В.А.Р. // ИНДЕКС ЗНАНИЙ").style(
                    "font-size:1rem;font-weight:900;letter-spacing:1px;"
                )
                ui.label("/api/rag/sources + /api/rag/datasets").style(
                    "font-size:.6rem;color:var(--dim);"
                )
            ui.button(
                "↻ ОБНОВИТЬ",
                on_click=lambda: asyncio.create_task(refresh_and_render())
            ).props("no-caps outline").style(
                "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
            )

        # KPI строка
        with ui.row().classes("w-full gap-3"):
            sam_kpi = {}
            for key, lbl, color in [
                ("ds",     "Датасетов",       "var(--text)"),
                ("src",    "Файлов в папках",  "var(--text)"),
                ("idx",    "В индексе",        "var(--ok)"),
                ("pend",   "Ожидают",          "var(--warn)"),
                ("err",    "Ошибок",           "var(--err)"),
                ("chunks", "Чанков Qdrant",    "var(--text)"),
            ]:
                with ui.card().classes("kpi-box flex-1"):
                    v = ui.label("—").classes("kpi-val").style(
                        f"color:{color};font-size:1.6rem;font-weight:900;"
                    )
                    ui.label(lbl).classes("kpi-lbl").style(
                        "font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;"
                    )
                    sam_kpi[key] = v

        runtime_banner = ui.label("runtime: —").classes("w-full").style(
            "border:1px solid var(--border);background:var(--bg-panel);color:var(--dim);"
            "border-radius:6px;padding:8px 10px;font-size:.68rem;font-family:var(--font);"
        )

        # Parse scheduler
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full gap-3"):
                with ui.column().classes("gap-0"):
                    ui.label("ИНДЕКСАЦИЯ // НАСТРОЙКИ И ЗАПУСК").classes("section-title")
                    scheduler_status = ui.label("ожидают: — · job: —").style(
                        "font-size:.65rem;color:var(--dim);"
                    )
                with ui.row().classes("items-center gap-2"):
                    batch_limit_input = ui.number("batch", value=1, min=1, max=25, step=1).props("dense outlined").style(
                        "width:86px;font-size:.7rem;"
                    )
                    max_batches_input = ui.number("max", value=25, min=1, max=500, step=1).props("dense outlined").style(
                        "width:86px;font-size:.7rem;"
                    )
                    cooldown_input = ui.number("cooldown", value=20, min=0, max=600, step=5).props("dense outlined").style(
                        "width:112px;font-size:.7rem;"
                    )
                    min_free_input = ui.number("min GB", value=8, min=1, max=64, step=1).props("dense outlined").style(
                        "width:92px;font-size:.7rem;"
                    )
                    max_swap_input = ui.number("swap %", value=45, min=0, max=100, step=5).props("dense outlined").style(
                        "width:92px;font-size:.7rem;"
                    )

                    async def run_scheduler():
                        payload = {
                            "batch_limit": int(batch_limit_input.value or 5),
                            "max_batches": int(max_batches_input.value or 25),
                            "cooldown_sec": float(cooldown_input.value or 0),
                            "unload_between_batches": True,
                            "unload_before_start": True,
                            "min_free_gb": float(min_free_input.value or 8),
                            "max_swap_pct": float(max_swap_input.value or 45),
                            "background": True,
                        }
                        add_log(
                            f"[PARSE_SCHEDULER] batch={payload['batch_limit']} "
                            f"max={payload['max_batches']} cooldown={payload['cooldown_sec']}"
                        )
                        start_scheduler_btn.props("loading")
                        d = await api_post("/api/rag/parse-scheduler", payload)
                        start_scheduler_btn.props(remove="loading")
                        if d:
                            ui.notify(f"Scheduler запущен: job {d.get('job_id','?')}", type="positive")
                            add_log(f"[PARSE_SCHEDULER] job {d.get('job_id')} queued")
                            await asyncio.sleep(1)
                            await refresh_and_render()
                        else:
                            ui.notify(last_api_error_text("Ошибка запуска scheduler"), type="negative")

                    start_scheduler_btn = ui.button(
                        "▶ СТАРТ ИНДЕКСАЦИИ",
                        on_click=run_scheduler,
                    ).props("no-caps").style(
                        "background:rgba(245,158,11,.15);border:1px solid var(--warn);"
                        "color:var(--warn);font-size:.7rem;font-weight:900;"
                    )
                    scheduler_live_label = ui.label("○ статус загружается…").style(
                        "color:var(--dim);font-size:.7rem;font-weight:700;"
                    )
                    # W5.2: прогресс реиндекса из push-канала /api/live (state["reindex"]).
                    reindex_progress = ui.linear_progress(value=0.0, show_value=False, size="8px").props(
                        "instant-feedback color=orange"
                    ).style("width:220px;display:none;")
                    reindex_progress_label = ui.label("").style(
                        "color:var(--dim);font-size:.66rem;"
                    )


        # Таблица датасетов
        sam_tbl_cols = [
            {"name": "folder",   "label": "Папка",    "field": "folder",   "align": "left",   "sortable": True},
            {"name": "total",    "label": "Файлов",   "field": "total",    "align": "right",  "sortable": True},
            {"name": "indexed",  "label": "В индексе", "field": "indexed",  "align": "right",  "sortable": True},
            {"name": "pending",  "label": "Ожидают",  "field": "pending",  "align": "right",  "sortable": True},
            {"name": "errors",   "label": "Ошибки",   "field": "errors",   "align": "right",  "sortable": True},
            {"name": "chunks",   "label": "Чанков",   "field": "chunks",   "align": "right",  "sortable": True},
            {"name": "status",   "label": "Статус",   "field": "status",   "align": "left"},
            {"name": "sensitivity", "label": "Данные", "field": "sensitivity", "align": "center"},
            {"name": "group_name", "label": "Группа", "field": "group_name", "align": "left", "sortable": True},
            {"name": "job_info", "label": "Job",      "field": "job_info", "align": "left"},
            {"name": "actions",  "label": "",          "field": "folder",   "align": "center"},
        ]
        sam_grid = ui.table(
            columns=sam_tbl_cols, rows=[], row_key="folder"
        ).classes("w-full").style(
            "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
        )
        sam_grid.add_slot("body-cell-folder", """
            <q-td :props="props">
              <q-btn flat dense no-caps align="left" color="primary"
                     @click="$parent.$emit('inspect', props.row)"
                     style="font-family:var(--font-chat);font-size:.72rem;font-weight:800;padding:2px 0;max-width:320px;">
                <span style="display:block;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                  {{ props.value }}
                </span>
              </q-btn>
            </q-td>""")
        sam_grid.add_slot("body-cell-indexed", """
            <q-td :props="props">
              <span :style="{color: props.value > 0 ? '#10b981' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
            </q-td>""")
        sam_grid.add_slot("body-cell-pending", """
            <q-td :props="props">
              <span :style="{color: props.value > 0 ? '#f59e0b' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
            </q-td>""")
        sam_grid.add_slot("body-cell-errors", """
            <q-td :props="props">
              <span :style="{color: props.value > 0 ? '#ef4444' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
            </q-td>""")
        sam_grid.add_slot("body-cell-status", """
            <q-td :props="props">
              <span :style="{color: ['INDEXED','READY','COMPLETED'].includes(props.value)?'#10b981':['PARSING','SCANNING'].includes(props.value)?'#f59e0b':'#94a3b8'}">
                {{ props.value }}
              </span>
            </q-td>""")
        sam_grid.add_slot("body-cell-actions", """
            <q-td :props="props" auto-width>
              <q-btn v-if="props.row.can_sync" flat dense size="xs" color="primary" icon="sync"
                     @click="$parent.$emit('sync', props.row)"
                     style="font-size:.6rem;padding:2px 6px;">СИНК</q-btn>
              <q-btn v-if="props.row.can_sync" flat dense size="xs" color="negative" icon="delete_sweep"
                     @click="$parent.$emit('reset', props.row)"
                     style="font-size:.6rem;padding:2px 6px;margin-left:4px;">↺ СБРОС</q-btn>
              <q-btn v-if="!props.row.can_sync && props.row.dataset_id" flat dense size="xs" color="primary" icon="sync"
                     :title="props.row.sync_reason"
                     @click="$parent.$emit('parse', props.row)"
                     style="font-size:.6rem;padding:2px 6px;">СИНК</q-btn>
              <span v-if="!props.row.can_sync && !props.row.dataset_id" :title="props.row.sync_reason"
                    style="color:#94a3b8;font-size:.65rem;cursor:help;border-bottom:1px dotted #94a3b8;">нет синка</span>
            </q-td>""")
        # W3.3 (ADR-9): чувствительность данных датасета — гейт локал/облако.
        # P0 (зелёный) только локально; P1 (синий) можно в облако; P2 (жёлтый) — с согласия.
        sam_grid.add_slot("body-cell-sensitivity", """
            <q-td :props="props" auto-width>
              <q-select v-if="props.row.dataset_id" dense borderless options-dense emit-value map-options
                        v-model="props.row.sensitivity" :options="['P0','P1','P2']"
                        @update:model-value="val => $parent.$emit('setsens', {dataset_id: props.row.dataset_id, folder: props.row.folder, level: val})"
                        :style="{fontSize:'.64rem',fontWeight:'900',color: props.row.sensitivity==='P0' ? '#10b981' : props.row.sensitivity==='P2' ? '#f59e0b' : '#38bdf8'}"
                        :title="props.row.sensitivity==='P0' ? 'P0 — только локально (почта, договоры, ПДн)' : props.row.sensitivity==='P1' ? 'P1 — можно в облако (нормативка)' : 'P2 — облако с согласия (проекты)'">
              </q-select>
              <span v-else style="color:#64748b;font-size:.6rem;cursor:help;" title="нет датасета — пометка появится после индексации">—</span>
            </q-td>""")
        # Группа датасета — организация списка (клик по ячейке → ввод; сортировка колонки кластеризует).
        sam_grid.add_slot("body-cell-group_name", """
            <q-td :props="props">
              <div v-if="props.row.dataset_id" class="cursor-pointer"
                   style="font-size:.64rem;color:#a78bfa;font-weight:700;min-width:70px;border-bottom:1px dashed #475569;">
                {{ props.row.group_name || '— задать —' }}
                <q-popup-edit v-model="props.row.group_name" auto-save v-slot="scope"
                    @save="val => $parent.$emit('setgroup', {dataset_id: props.row.dataset_id, folder: props.row.folder, group: val})">
                  <q-input v-model="scope.value" dense autofocus counter maxlength="60"
                           placeholder="имя группы" @keyup.enter="scope.set"/>
                </q-popup-edit>
              </div>
              <span v-else style="color:#64748b;font-size:.6rem;">—</span>
            </q-td>""")
        sam_grid.on("setgroup", lambda e: asyncio.create_task(_set_group(e.args)))
        sam_grid.on("inspect", lambda e: asyncio.create_task(_open_index_dialog(e.args)))
        sam_grid.on("sync",  lambda e: asyncio.create_task(_sync_row(e.args)))
        sam_grid.on("reset", lambda e: asyncio.create_task(_reset_row(e.args)))
        sam_grid.on("parse", lambda e: asyncio.create_task(_parse_row(e.args)))
        sam_grid.on("setsens", lambda e: asyncio.create_task(_set_sensitivity(e.args)))

        selected_index = {"row": {}}
        with ui.dialog() as index_dialog:
            with ui.card().classes("card-les").style(
                "width:min(1180px,96vw);max-width:96vw;max-height:90vh;"
                "background:var(--bg-panel);color:var(--text);"
            ):
                with ui.row().classes("items-center justify-between w-full gap-3"):
                    with ui.column().classes("gap-0"):
                        index_title = ui.label("INDEX // —").style(
                            "font-size:.95rem;font-weight:900;letter-spacing:.6px;"
                        )
                        index_subtitle = ui.label("dataset: —").style(
                            "font-size:.65rem;color:var(--dim);"
                        )
                    ui.button(icon="o_close", on_click=index_dialog.close).props("flat round dense")

                with ui.row().classes("w-full gap-3"):
                    index_kpi = {}
                    for key, label, color in [
                        ("total", "Файлов", "var(--text)"),
                        ("indexed", "INDEXED", "var(--ok)"),
                        ("pending", "PENDING", "var(--warn)"),
                        ("errors", "ERROR", "var(--err)"),
                        ("chunks", "Чанков", "var(--text)"),
                    ]:
                        with ui.card().classes("kpi-box flex-1"):
                            index_kpi[key] = ui.label("—").classes("kpi-val").style(
                                f"color:{color};font-size:1.35rem;font-weight:900;"
                            )
                            ui.label(label).classes("kpi-lbl").style(
                                "font-size:.6rem;text-transform:uppercase;color:var(--dim);margin-top:4px;"
                            )

                with ui.row().classes("items-center gap-2 w-full"):
                    index_status_select = ui.select(
                        {"": "Все статусы", "INDEXED": "INDEXED", "PENDING": "PENDING", "ERROR": "ERROR"},
                        value="",
                        label="status",
                    ).props("dense outlined emit-value map-options").style("width:150px;font-size:.7rem;")
                    index_query_input = ui.input(
                        placeholder="Поиск по имени, домену, ошибке..."
                    ).props("dense outlined clearable").classes("flex-1").style("font-size:.7rem;")
                    index_limit_select = ui.select(
                        [50, 120, 250, 500],
                        value=120,
                        label="limit",
                    ).props("dense outlined").style("width:104px;font-size:.7rem;")
                    ui.button(
                        icon="o_search",
                        on_click=lambda: asyncio.create_task(_refresh_index_dialog_documents()),
                    ).props("flat round dense").tooltip("Искать в этом индексе")
                    ui.button(
                        icon="o_done_all",
                        on_click=lambda: asyncio.create_task(_quick_index_status("INDEXED")),
                    ).props("flat round dense").tooltip("Только INDEXED")
                    ui.button(
                        icon="o_pending_actions",
                        on_click=lambda: asyncio.create_task(_quick_index_status("PENDING")),
                    ).props("flat round dense").tooltip("Только PENDING")
                    ui.button(
                        icon="o_error_outline",
                        on_click=lambda: asyncio.create_task(_quick_index_status("ERROR")),
                    ).props("flat round dense").tooltip("Только ERROR")

                index_docs_status = ui.label("показано: —").style("font-size:.65rem;color:var(--dim);")
                index_docs_cols = [
                    {"name": "status", "label": "Статус", "field": "status", "align": "left", "sortable": True},
                    {"name": "file", "label": "Файл", "field": "file", "align": "left", "sortable": True},
                    {"name": "source", "label": "Источник (in-place)", "field": "source", "align": "left"},
                    {"name": "chunks", "label": "Чанков", "field": "chunks", "align": "center", "sortable": True},
                    {"name": "size", "label": "Размер", "field": "size", "align": "right", "sortable": True},
                    {"name": "domain", "label": "Domain", "field": "domain", "align": "left", "sortable": True},
                    {"name": "doc_type", "label": "Doc", "field": "doc_type", "align": "left", "sortable": True},
                    {"name": "content", "label": "Content", "field": "content", "align": "left", "sortable": True},
                    {"name": "pipeline", "label": "Pipeline", "field": "pipeline", "align": "left", "sortable": True},
                    {"name": "error", "label": "Last error", "field": "error", "align": "left"},
                ]
                index_docs_grid = ui.table(
                    columns=index_docs_cols,
                    rows=[],
                    row_key="id",
                    pagination=25,
                ).classes("w-full").props("dense wrap-cells").style(
                    "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
                )
                index_docs_grid.add_slot("body-cell-status", """
                    <q-td :props="props">
                      <span :style="{color: props.value === 'INDEXED' ? '#10b981' : props.value === 'ERROR' ? '#ef4444' : '#f59e0b', fontWeight:'900'}">
                        {{ props.value }}
                      </span>
                    </q-td>""")
                index_docs_grid.add_slot("body-cell-file", """
                    <q-td :props="props">
                      <div :title="props.value" style="max-width:460px;white-space:normal;word-break:break-word;font-family:var(--font-chat);font-size:.68rem;">
                        {{ props.value }}
                      </div>
                    </q-td>""")
                index_docs_grid.add_slot("body-cell-source", """
                    <q-td :props="props">
                      <span v-if="props.value" :title="props.value" style="color:#10b981;white-space:normal;word-break:break-all;font-size:.62rem;font-family:var(--font-chat);">
                        ⤵ {{ props.value }}
                      </span>
                      <span v-else style="color:#64748b;">— storage</span>
                    </q-td>""")
                index_docs_grid.add_slot("body-cell-error", """
                    <q-td :props="props">
                      <span v-if="props.value" :title="props.value" style="color:#ef4444;white-space:normal;word-break:break-word;font-size:.66rem;">
                        {{ props.value }}
                      </span>
                      <span v-else style="color:#64748b;">—</span>
                    </q-td>""")

        # Синк папки-источника: выпадающий список известных папок (+ ручной ввод для новых)
        with ui.row().classes("gap-3 w-full"):
            sync_folder_input = ui.select(
                options=[],
                with_input=True,
                new_value_mode="add-unique",
                label="Папка-источник для синка",
            ).props("dense outlined use-input").style(
                "background:var(--bg);border:1px solid var(--border);color:var(--text);"
                "font-family:var(--font);border-radius:4px;padding:6px 10px;font-size:.75rem;flex:1;"
            ).classes("flex-1")

            async def do_sync():
                folder = (sync_folder_input.value or "").strip()
                if not folder:
                    ui.notify("Укажи имя папки", type="warning")
                    return
                add_log(f"[SYNC] Запуск: {folder}")
                d = await api_post(f"/api/rag/sync/{quote(folder, safe='')}")
                if d:
                    ui.notify(
                        f"SYNC запущен. Job: {d.get('job_id','?')} | +{d.get('new_files',0)} новых",
                        type="positive"
                    )
                    add_log(f"[SYNC] {folder} → job {d.get('job_id')} +{d.get('new_files',0)} новых")
                    await asyncio.sleep(3)
                    await refresh_and_render()
                else:
                    ui.notify(last_api_error_text(f"Ошибка SYNC {folder}"), type="negative")

            ui.button("↻ SYNC", on_click=do_sync).props("no-caps outline").style(
                "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
            )

        # ── Внешняя папка → in-place индексация без копии в storage ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("ВНЕШНЯЯ ПАПКА // IN-PLACE (БЕЗ КОПИИ В STORAGE)").classes("section-title")
                ui.label("/api/rag/index-external · любой локальный каталог").style(
                    "font-size:.6rem;color:var(--dim);"
                )
            ui.label(
                "Исходники остаются в своей папке; в LES попадают только производное "
                "(Qdrant-векторы, Parquet, метаданные). Индексируется любая локальная папка "
                "(резолв симлинков, без копии в storage)."
            ).style("font-size:.64rem;color:var(--dim);margin-bottom:4px;")

            # Серверный браузер папок — выбрать внешнюю папку кликами, без печати пути.
            browse_state = {"path": ""}
            with ui.dialog() as folder_dialog, ui.card().style("min-width:520px;max-width:92vw"):
                ui.label("ВЫБОР ПАПКИ // любой локальный каталог").classes("section-title")
                # Действия СВЕРХУ: «Выбрать эту папку» видно сразу, без прокрутки списка.
                with ui.row().classes("w-full items-center gap-2").style("margin:4px 0 8px;"):
                    fb_select_btn = ui.button("✓ Выбрать эту папку", on_click=lambda: _pick_folder()).props("no-caps")
                    ui.button("Отмена", on_click=folder_dialog.close).props("flat no-caps")
                    fb_path_lbl = ui.label("…").style(
                        "font-size:.7rem;color:var(--accent);word-break:break-all;font-weight:700;flex:1;text-align:right;"
                    )
                fb_list = ui.column().classes("w-full gap-1").style("max-height:340px;overflow:auto;")

            async def _browse_folder(path=""):
                d = await api_get(f"/api/rag/browse-external?path={quote(path, safe='')}")
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Не удалось открыть папку"), type="negative")
                    return
                browse_state["path"] = d.get("path", "")
                fb_path_lbl.text = d.get("path", "") or "Корни (выбери папку ниже)"
                fb_list.clear()
                with fb_list:
                    if d.get("path"):
                        ui.button("↑ Вверх", icon="o_arrow_upward",
                                  on_click=lambda u=d.get("parent"): asyncio.create_task(_browse_folder(u or ""))
                                  ).props("flat dense no-caps").classes("w-full")
                    for entry in d.get("dirs", []):
                        ui.button(f"{entry['name']}   ·  {entry.get('file_count', 0)} файл(ов)", icon="o_folder",
                                  on_click=lambda p=entry["path"]: asyncio.create_task(_browse_folder(p))
                                  ).props("flat dense no-caps align=left").classes("w-full")
                    if not d.get("dirs") and d.get("path"):
                        ui.label("Подпапок нет — можно выбрать эту папку.").style(
                            "font-size:.66rem;color:var(--dim);")
                fb_select_btn.set_enabled(bool(d.get("path")))

            def _pick_folder():
                if browse_state["path"]:
                    ext_path_input.value = browse_state["path"]
                    ext_path_input.update()
                    folder_dialog.close()
                    ui.notify(f"Папка: {browse_state['path']}", type="positive")

            def _set_external_path(path: str):
                ext_path_input.value = path or ""
                ext_path_input.update()
                if path:
                    ui.notify(f"Путь выбран: {path}", type="positive")

            def _open_folder_browser():
                folder_dialog.open()
                asyncio.create_task(_browse_folder(""))

            with ui.row().classes("gap-2 w-full items-center"):
                ext_path_input = ui.input(
                    placeholder="/Users/ovc/RAG/CONTS/Документы/АМК ВОР 1901"
                ).props("dense outlined clearable").classes("flex-1").style(
                    "background:var(--bg);font-size:.75rem;"
                )
                ui.button("Обзор…", icon="o_folder_open", on_click=_open_folder_browser).props(
                    "dense no-caps flat"
                ).tooltip("Выбрать папку кликами, без печати пути")
                ext_limit_input = ui.number("parse", value=25, min=1, max=500, step=5).props(
                    "dense outlined"
                ).style("width:96px;font-size:.7rem;").tooltip("Сколько файлов распарсить сразу")

            with ui.row().classes("gap-2 w-full items-center"):
                ext_dataset_select = ui.select(
                    options={},
                    label="Существующий датасет",
                ).props("dense outlined emit-value map-options clearable").classes("flex-1").style(
                    "font-size:.7rem;"
                )
                ext_new_ds_input = ui.input(
                    placeholder="…или имя нового датасета"
                ).props("dense outlined clearable").classes("flex-1").style(
                    "background:var(--bg);font-size:.75rem;"
                )

                async def do_index_external():
                    path = (ext_path_input.value or "").strip()
                    if not path:
                        ui.notify("Укажи путь к внешней папке", type="warning")
                        return
                    ds_id = (ext_dataset_select.value or "").strip()
                    new_name = (ext_new_ds_input.value or "").strip()
                    if new_name:
                        created = await api_post(f"/api/rag/datasets?name={quote(new_name, safe='')}")
                        if not created or not created.get("id"):
                            ui.notify(last_api_error_text("Не удалось создать датасет"), type="negative")
                            return
                        ds_id = created["id"]
                        add_log(f"[EXT_INDEX] создан датасет «{new_name}» → {ds_id}")
                    if not ds_id:
                        ui.notify("Выбери датасет или укажи имя нового", type="warning")
                        return
                    payload = {
                        "path": path,
                        "dataset_id": ds_id,
                        "parse": True,
                        "parse_limit": int(ext_limit_input.value or 25),
                    }
                    add_log(f"[EXT_INDEX] {path} → {ds_id}")
                    ext_index_btn.props("loading")
                    d = await api_post("/api/rag/index-external", payload)
                    ext_index_btn.props(remove="loading")
                    if d and d.get("status") == "registered":
                        ui.notify(
                            f"In-place: +{d.get('registered_files', 0)} файлов из "
                            f"«{d.get('source_root', '')}» (без копии)"
                            f"{' · парсинг запущен' if d.get('parse_started') else ''}",
                            type="positive",
                        )
                        add_log(
                            f"[EXT_INDEX] +{d.get('registered_files', 0)} файлов · "
                            f"пропущено типов {d.get('skipped_unsupported', 0)} · "
                            f"вне корня {d.get('skipped_outside_root', 0)}"
                        )
                        ext_new_ds_input.value = ""
                        await asyncio.sleep(2)
                        await refresh_and_render()
                    else:
                        ui.notify(last_api_error_text("Ошибка in-place индексации"), type="negative")

                ext_index_btn = ui.button(
                    "⤵ ИНДЕКСИРОВАТЬ IN-PLACE",
                    on_click=do_index_external,
                ).props("no-caps").style(
                    "background:rgba(16,185,129,.15);border:1px solid var(--ok);"
                    "color:var(--ok);font-size:.7rem;font-weight:900;"
                )

        # ── External Radar: обзор внешних корней/карты/уже in-place датасетов ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("EXTERNAL RADAR // ВНЕШНИЕ ИСТОЧНИКИ").classes("section-title")
                radar_status = ui.label("—").style("font-size:.65rem;color:var(--dim);")
            ui.label(
                "Быстрый обзор без чтения содержимого: корни, карта архива, уже привязанные "
                "in-place файлы и папки-кандидаты."
            ).style("font-size:.64rem;color:var(--dim);margin-bottom:4px;")
            radar_box = ui.column().classes("w-full gap-1")

            async def refresh_external_radar():
                radar_status.text = "сканирую метаданные…"
                radar_box.clear()
                d = await api_get("/api/external-radar/summary?limit=12")
                if not isinstance(d, dict):
                    radar_status.text = "ошибка"
                    ui.notify(last_api_error_text("External Radar недоступен"), type="negative")
                    return
                roots = d.get("roots", [])
                cands = d.get("candidates", [])
                radar_status.text = (
                    f"{len(roots)} корн. · external docs {d.get('external_documents', 0)} · "
                    f"кандидатов {len(cands)}"
                )
                with radar_box:
                    if not roots:
                        ui.label("Корней нет: задай LES_EXTERNAL_SOURCE_ROOTS или выбери папку через Обзор.").style(
                            "font-size:.7rem;color:var(--dim);"
                        )
                    for root in roots[:6]:
                        status = root.get("status", "")
                        color = "var(--ok)" if root.get("indexed_files") else (
                            "var(--warn)" if root.get("mapped_files") else "var(--dim)"
                        )
                        sources = ",".join(root.get("sources", []))
                        with ui.row().classes("w-full items-center gap-2").style(
                            "border-bottom:1px dashed var(--dim);padding:2px 0;"
                        ):
                            ui.icon("o_radar").style(f"color:{color};font-size:18px;")
                            ui.label(root.get("name") or root.get("path", "")).classes("flex-1").style(
                                "font-size:.72rem;"
                            ).tooltip(root.get("path", ""))
                            ui.label(
                                f"{status} · map {root.get('mapped_files', 0)} · "
                                f"idx {root.get('indexed_files', 0)} · {sources}"
                            ).style("font-size:.62rem;color:var(--dim);")
                            ui.button(
                                "Взять путь",
                                on_click=lambda p=root.get("path", ""): _set_external_path(p),
                            ).props("flat dense no-caps").style("font-size:.62rem;")

                    if cands:
                        ui.label("Кандидаты из карты архива:").style(
                            "font-size:.65rem;color:var(--dim);margin-top:4px;"
                        )
                    for cand in cands[:8]:
                        already = int(cand.get("indexed_files") or 0)
                        color = "var(--ok)" if already else "var(--accent)"
                        with ui.row().classes("w-full items-center gap-2").style(
                            "border-bottom:1px dashed var(--dim);padding:2px 0;"
                        ):
                            ui.icon("o_folder_search").style(f"color:{color};font-size:18px;")
                            ui.label(cand.get("folder") or cand.get("root", "")).classes("flex-1").style(
                                "font-size:.72rem;"
                            ).tooltip(cand.get("abs_path", ""))
                            ui.label(
                                f"{cand.get('ciphered', 0)}/{cand.get('files', 0)} · "
                                f"idx {already} · {', '.join((cand.get('ciphers') or [])[:3])}"
                            ).style("font-size:.62rem;color:var(--dim);")
                            ui.button(
                                "Взять",
                                on_click=lambda p=cand.get("abs_path", ""): _set_external_path(p),
                            ).props("flat dense no-caps").style("font-size:.62rem;")

            with ui.row().classes("gap-2 items-center"):
                ui.button("Обновить радар", icon="o_radar", on_click=refresh_external_radar).props(
                    "dense no-caps outline"
                ).style("border-color:var(--accent);color:var(--accent);font-size:.7rem;")
                ui.label("Глубокий скан: блок «Карта архива» ниже").style(
                    "font-size:.68rem;color:var(--dim);"
                ).tooltip(
                    "Радар сам не сканирует диск; для новой карты используй блок «Карта архива» ниже"
                )

        # ── Outlook / IMAP → почта в RAG (Е.Ж.И.К.) — W11.13 ──
        with ui.card().classes("card-les w-full"):
            ui.label("OUTLOOK / IMAP // ПОЧТА В RAG (Е.Ж.И.К.)").classes("section-title")
            ui.label(
                "Подключение к ящику по IMAP: письма → .eml → индексация в MAIL_Index (P0, только локально). "
                "Пароль не сохраняется — живёт только на время импорта. Для авто-синхрона пропиши MAIL_IMAP_* в .env. "
                "Десктоп Outlook на Windows = клиент аккаунта; IMAP подключается к самому аккаунту "
                "(в корпоративном M365 базовый IMAP может быть закрыт админом — тогда нужен app-password)."
            ).style("font-size:.62rem;color:var(--dim);margin-bottom:4px;")
            with ui.row().classes("gap-2 w-full items-center"):
                mail_preset = ui.select(
                    {"office365": "Outlook / Microsoft 365", "outlookcom": "Outlook.com (личный)", "custom": "Другой IMAP"},
                    value="office365", label="Пресет",
                ).props("dense outlined").style("max-width:230px;font-size:.72rem;")
                mail_host = ui.input(label="IMAP-хост", value="outlook.office365.com").props(
                    "dense outlined"
                ).classes("flex-1").style("font-size:.72rem;")
                mail_port = ui.number(label="Порт", value=993, min=1, max=65535).props("dense outlined").style("width:88px;")
            with ui.row().classes("gap-2 w-full items-center"):
                mail_login = ui.input(label="Логин (email)").props("dense outlined").classes("flex-1").style("font-size:.72rem;")
                mail_pass = ui.input(label="Пароль / app-password").props("dense outlined type=password").classes(
                    "flex-1"
                ).style("font-size:.72rem;")
            with ui.row().classes("gap-2 w-full items-center"):
                mail_folders = ui.input(label="Папки (через запятую)", value="INBOX").props(
                    "dense outlined"
                ).classes("flex-1").style("font-size:.72rem;")
                mail_max = ui.number(label="Писем за раз", value=25, min=1, max=200).props("dense outlined").style("width:120px;")
                ui.button("⤵ ПОДКЛЮЧИТЬ И ИМПОРТИРОВАТЬ", on_click=lambda: asyncio.create_task(_mail_import())).props(
                    "no-caps"
                ).style("background:rgba(16,185,129,.15);border:1px solid var(--ok);color:var(--ok);font-size:.7rem;font-weight:900;")
            mail_status = ui.label("").style("font-size:.7rem;color:var(--dim);")
            autosync_lbl = ui.label("Авто-синхрон: …").style("font-size:.64rem;margin-top:2px;")

            async def _load_autosync():
                d = await api_get("/api/mail/status") or {}
                a = (d.get("autosync") or {})
                ps = int(a.get("poll_sec", 0) or 0)
                if ps > 0:
                    msg = (f"🟢 Внутренний IMAP-сервис ВКЛ: каждые {ps} сек · циклов {a.get('runs', 0)} · "
                           f"последняя порция {a.get('last_count', 0)} писем")
                    if a.get("last_error"):
                        msg += f" · ошибка: {str(a['last_error'])[:60]}"
                    autosync_lbl.set_text(msg); autosync_lbl.style("color:var(--ok);")
                else:
                    autosync_lbl.set_text("⚪ Внутренний IMAP-сервис ВЫКЛ — включить: "
                                          "MAIL_IMAP_POLL_SEC=600 + MAIL_IMAP_HOST/LOGIN/PASSWORD в .env")
                    autosync_lbl.style("color:var(--dim);")

            asyncio.create_task(_load_autosync())

            ui.separator().style("margin:6px 0;")
            ui.label(
                "Архив Outlook: .olm (Outlook для Mac) или .pst (Outlook Windows). Путь — внутри "
                "LES_EXTERNAL_SOURCE_ROOTS. Отдельные .msg-письма индексируются как обычные файлы "
                "(Скрепка в чате / загрузка в Самовар). .pst требует libpff (см. подсказку при ошибке)."
            ).style("font-size:.62rem;color:var(--dim);")
            with ui.row().classes("gap-2 w-full items-center"):
                arch_path = ui.input(placeholder="/Users/ovc/RAG/.../archive.olm").props(
                    "dense outlined clearable"
                ).classes("flex-1").style("font-size:.72rem;")
                ui.button("⤵ ИМПОРТ АРХИВА", on_click=lambda: asyncio.create_task(_archive_import())).props(
                    "no-caps"
                ).style("background:rgba(16,185,129,.15);border:1px solid var(--ok);color:var(--ok);font-size:.7rem;font-weight:900;")
            arch_status = ui.label("").style("font-size:.7rem;color:var(--dim);")

            async def _archive_import():
                if not (arch_path.value or "").strip():
                    ui.notify("Укажи путь к .olm/.pst", type="warning")
                    return
                arch_status.text = "Импорт архива…"
                add_log(f"[OUTLOOK ARCH] {arch_path.value}")
                d = await api_post("/api/mail/import-archive", {"path": arch_path.value.strip(), "parse": True})
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("Импорт архива не удался (для .pst нужен libpff)"), type="negative")
                    arch_status.text = ""
                    return
                arch_status.text = (f"Импортировано писем: {d.get('messages', 0)} "
                                    f"({d.get('format', '')}) → {d.get('dataset_name', 'MAIL')}")
                ui.notify(arch_status.text, type="positive")

            def _apply_preset():
                if mail_preset.value == "office365":
                    mail_host.value, mail_port.value = "outlook.office365.com", 993
                elif mail_preset.value == "outlookcom":
                    mail_host.value, mail_port.value = "imap-mail.outlook.com", 993
                mail_host.update()
                mail_port.update()

            mail_preset.on_value_change(lambda _e: _apply_preset())

            async def _mail_import():
                if not (mail_host.value and mail_login.value and mail_pass.value):
                    ui.notify("Заполни хост, логин и пароль", type="warning")
                    return
                mail_status.text = "Подключение и импорт…"
                add_log(f"[OUTLOOK] import {mail_login.value} @ {mail_host.value}")
                payload = {
                    "host": mail_host.value, "port": int(mail_port.value or 993),
                    "login": mail_login.value, "password": mail_pass.value, "ssl": True,
                    "folders": [f.strip() for f in (mail_folders.value or "INBOX").split(",") if f.strip()],
                    "max_messages": int(mail_max.value or 25), "parse": True, "background": False,
                }
                d = await api_post("/api/mail/import-imap", payload)
                if not isinstance(d, dict):
                    ui.notify(last_api_error_text("IMAP-импорт не удался (проверь хост/логин/пароль)"), type="negative")
                    mail_status.text = ""
                    return
                if d.get("status") == "no_new_mail":
                    mail_status.text = "Новых писем нет — всё уже импортировано."
                else:
                    mail_status.text = (f"Импортировано писем: {d.get('files', 0)} → {d.get('dataset_name', 'MAIL')}. "
                                        f"Парс запущен: {d.get('parse_started')}")
                ui.notify(mail_status.text, type="positive")

        # ── Карта архива → выборочная индексация (W15.1/W15.2) ──
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("КАРТА АРХИВА // ИНДЕКСАЦИЯ ИЗ ФАЙЛОПОМОЙКИ").classes("section-title")
                map_stats_label = ui.label("—").style("font-size:.65rem;color:var(--dim);")

            with ui.row().classes("gap-2 w-full items-center"):
                scan_path_input = ui.input(
                    placeholder="/путь/к/архиву для сканирования"
                ).props("dense outlined").classes("flex-1").style(
                    "background:var(--bg);font-size:.75rem;"
                )

                async def do_scan():
                    path = (scan_path_input.value or "").strip()
                    if not path:
                        ui.notify("Укажи путь к архиву", type="warning")
                        return
                    add_log(f"[FILEMAP] scan {path}")
                    d = await api_post("/api/filemap/scan", {"path": path})
                    if d:
                        ui.notify(
                            f"Скан: {d.get('files',0)} файлов, {d.get('total_gb',0)} ГБ "
                            f"(+{d.get('added',0)}/~{d.get('updated',0)}/-{d.get('removed',0)}) "
                            f"за {d.get('elapsed_sec',0)}с",
                            type="positive",
                        )
                        await refresh_map()
                    else:
                        ui.notify(last_api_error_text("Ошибка скана"), type="negative")

                ui.button("СКАНИРОВАТЬ", on_click=do_scan).props("no-caps outline").style(
                    "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
                )

            ui.label("Папки-кандидаты (где найдены шифры НТД/комплектов):").style(
                "font-size:.65rem;color:var(--dim);margin-top:6px;"
            )
            candidates_box = ui.column().classes("w-full gap-1")

            async def index_selection(*, dataset_name, root="", path_prefix="", cipher="", ext="", parse=True):
                if not dataset_name:
                    ui.notify("Укажи имя датасета", type="warning")
                    return
                add_log(f"[FILEMAP] index → {dataset_name}")
                d = await api_post("/api/filemap/index", {
                    "dataset_name": dataset_name, "root": root, "path_prefix": path_prefix,
                    "cipher": cipher, "ext": ext, "parse": parse,
                })
                if d and d.get("status") == "indexed":
                    ui.notify(
                        f"«{d['dataset_name']}»: +{d['registered']} файлов "
                        f"(из {d['selected']}){' · парсинг запущен' if d.get('parse_started') else ''}",
                        type="positive",
                    )
                    await refresh_and_render()
                elif d and d.get("status") == "nothing_supported":
                    ui.notify(f"Нет поддерживаемых файлов (отклонено: {d.get('rejected')})", type="warning")
                else:
                    ui.notify(last_api_error_text("Ошибка индексации"), type="negative")

            async def refresh_map():
                stats = await api_get("/api/filemap/stats") or {}
                roots = stats.get("roots", [])
                if roots:
                    total = sum(r.get("file_count", 0) for r in roots)
                    map_stats_label.text = (
                        f"{len(roots)} корн., {total} файлов, шифров: {stats.get('files_with_cipher', 0)}"
                    )
                else:
                    map_stats_label.text = "карта пуста — отсканируй архив"
                cands = (await api_get("/api/filemap/candidates?limit=25") or {}).get("candidates", [])
                candidates_box.clear()
                with candidates_box:
                    if not cands:
                        ui.label("кандидатов нет").style("font-size:.7rem;color:var(--dim);")
                    for c in cands:
                        folder = c.get("folder") or "(корень)"
                        ciphers = ", ".join(c.get("ciphers", [])[:4])
                        ds_default = (folder.rsplit("/", 1)[-1] or "Archive") + "_Index"
                        with ui.row().classes("w-full items-center gap-2").style(
                            "border-bottom:1px dashed var(--dim);padding:2px 0;"
                        ):
                            ui.label(f"{folder}").classes("flex-1").style("font-size:.72rem;").tooltip(c.get("root", ""))
                            ui.label(f"{c['ciphered']}/{c['files']} · {ciphers}").style(
                                "font-size:.62rem;color:var(--dim);"
                            )
                            ui.button(
                                "ИНДЕКС",
                                on_click=lambda c=c, ds=ds_default: asyncio.create_task(
                                    index_selection(dataset_name=ds, root=c.get("root", ""),
                                                    path_prefix=c.get("folder", ""))
                                ),
                            ).props("dense flat no-caps").style("color:var(--accent);font-size:.65rem;")

        # Live proxy log
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("ЖИВОЙ ЛОГ // PROXY + ИНДЕКСАТОР").classes("section-title")
                live_log_status = ui.label("waiting").style("font-size:.65rem;color:var(--dim);")
            live_log_box = ui.html("", sanitize=False).classes("sov-live-log")

        # История Jobs
        with ui.card().classes("card-les w-full"):
            ui.label("ИСТОРИЯ JOBS").classes("section-title mb-3")
            jobs_tbl_cols = [
                {"name": "job_id",   "label": "Job",       "field": "job_id",   "align": "left"},
                {"name": "dataset",  "label": "Датасет",   "field": "dataset",  "align": "left",   "sortable": True},
                {"name": "status",   "label": "Статус",    "field": "status",   "align": "left",   "sortable": True},
                {"name": "progress", "label": "Файлов",    "field": "progress", "align": "center"},
                {"name": "started",  "label": "Начало",    "field": "started",  "align": "left",   "sortable": True},
                {"name": "message",  "label": "Сообщение", "field": "message",  "align": "left"},
            ]
            jobs_grid = ui.table(
                columns=jobs_tbl_cols, rows=[], row_key="job_id"
            ).classes("w-full").style(
                "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
            )

        # Статус документов
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("ФАЙЛЫ ИНДЕКСАЦИИ").classes("section-title mb-3")
                docs_status = ui.label("INDEXED/PENDING/ERROR").style(
                    "font-size:.65rem;color:var(--dim);"
                )
            with ui.row().classes("items-center gap-2 w-full"):
                doc_dataset_select = ui.select(
                    {"": "Все датасеты"},
                    value="",
                    label="dataset",
                ).props("dense outlined emit-value map-options").style("min-width:230px;font-size:.7rem;")
                doc_status_select = ui.select(
                    {"": "Все статусы", "ERROR": "ERROR", "PENDING": "PENDING", "INDEXED": "INDEXED"},
                    value="INDEXED",
                    label="status",
                ).props("dense outlined emit-value map-options").style("width:150px;font-size:.7rem;")
                doc_query_input = ui.input(
                    placeholder="Файл, датасет, ошибка..."
                ).props("dense outlined clearable").classes("flex-1").style("font-size:.7rem;")
                doc_limit_select = ui.select(
                    [50, 120, 250, 500],
                    value=120,
                    label="limit",
                ).props("dense outlined").style("width:104px;font-size:.7rem;")
                ui.button(
                    icon="o_filter_alt",
                    on_click=lambda: asyncio.create_task(refresh_documents_only()),
                ).props("flat round dense").tooltip("Применить фильтры")
                ui.button(
                    icon="o_done_all",
                    on_click=lambda: asyncio.create_task(_quick_docs_status("INDEXED")),
                ).props("flat round dense").tooltip("Показать INDEXED")
                ui.button(
                    icon="o_error_outline",
                    on_click=lambda: asyncio.create_task(_quick_docs_status("ERROR")),
                ).props("flat round dense").tooltip("Показать ERROR")
                ui.button(
                    icon="o_pending_actions",
                    on_click=lambda: asyncio.create_task(_quick_docs_status("PENDING")),
                ).props("flat round dense").tooltip("Показать PENDING")
            docs_tbl_cols = [
                {"name": "status", "label": "Статус", "field": "status", "align": "left", "sortable": True},
                {"name": "dataset", "label": "Датасет", "field": "dataset", "align": "left", "sortable": True},
                {"name": "domain", "label": "Domain", "field": "domain", "align": "left", "sortable": True},
                {"name": "route", "label": "Route", "field": "route", "align": "left", "sortable": True},
                {"name": "content", "label": "Content", "field": "content", "align": "left", "sortable": True},
                {"name": "complexity", "label": "Complexity", "field": "complexity", "align": "left", "sortable": True},
                {"name": "chunks", "label": "Чанков", "field": "chunks", "align": "center", "sortable": True},
                {"name": "size", "label": "Размер", "field": "size", "align": "right", "sortable": True},
                {"name": "file", "label": "Файл", "field": "file", "align": "left", "sortable": True},
                {"name": "pipeline", "label": "Pipeline", "field": "pipeline", "align": "left"},
                {"name": "error", "label": "Last error", "field": "error", "align": "left"},
            ]
            docs_grid = ui.table(
                columns=docs_tbl_cols, rows=[], row_key="id", pagination=20
            ).classes("w-full").style(
                "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
            ).props("dense wrap-cells")
            docs_grid.add_slot("body-cell-status", """
                <q-td :props="props">
                  <span :style="{color: props.value === 'INDEXED' ? '#10b981' : props.value === 'ERROR' ? '#ef4444' : '#f59e0b', fontWeight:'800'}">
                    {{ props.value }}
                  </span>
                </q-td>""")
            docs_grid.add_slot("body-cell-file", """
                <q-td :props="props">
                  <div :title="props.value" style="max-width:360px;white-space:normal;word-break:break-word;font-family:var(--font-chat);font-size:.68rem;">
                    {{ props.value }}
                  </div>
                </q-td>""")
            docs_grid.add_slot("body-cell-error", """
                <q-td :props="props">
                  <span v-if="props.value" :title="props.value" style="color:#ef4444;white-space:normal;word-break:break-word;font-size:.66rem;">
                    {{ props.value }}
                  </span>
                  <span v-else style="color:#64748b;">—</span>
                </q-td>""")

        # ── Внутренние функции ──

        def _documents_api_path() -> str:
            params = {
                "limit": int(doc_limit_select.value or 120),
                "offset": 0,
            }
            dataset_id = doc_dataset_select.value or ""
            status = doc_status_select.value or ""
            q = (doc_query_input.value or "").strip()
            if dataset_id:
                params["dataset_id"] = dataset_id
            if status:
                params["status"] = status
            if q:
                params["q"] = q
            return "/api/rag/documents?" + urlencode(params)

        def _format_size(file_size: int) -> str:
            if file_size >= 1024 * 1024:
                return f"{file_size / (1024 * 1024):.1f} MB"
            if file_size >= 1024:
                return f"{file_size / 1024:.0f} KB"
            return f"{file_size} B"

        def _doc_row(item: dict) -> dict:
            return {
                "id": item.get("id", item.get("file_name", "")),
                "status": item.get("status", ""),
                "dataset": item.get("dataset_name", ""),
                "domain": item.get("domain", ""),
                "route": item.get("route_dataset", ""),
                "doc_type": item.get("doc_type", ""),
                "content": item.get("content_type", ""),
                "complexity": item.get("complexity", ""),
                "chunks": item.get("chunk_count", 0),
                "size": _format_size(int(item.get("file_size") or 0)),
                "file": item.get("file_name", ""),
                "source": item.get("source_path", ""),
                "pipeline": item.get("pipeline", ""),
                "error": item.get("last_error", ""),
            }

        def _index_documents_api_path() -> str:
            row = selected_index.get("row") or {}
            params = {
                "limit": int(index_limit_select.value or 120),
                "offset": 0,
            }
            dataset_id = row.get("dataset_id") or ""
            status = index_status_select.value or ""
            q = (index_query_input.value or "").strip()
            if dataset_id:
                params["dataset_id"] = dataset_id
            elif row.get("folder"):
                params["q"] = str(row.get("folder"))
            if status:
                params["status"] = status
            if q:
                params["q"] = q
            return "/api/rag/documents?" + urlencode(params)

        async def _refresh_index_dialog_documents(render_main: bool = False):
            row = selected_index.get("row") or {}
            if not row:
                return
            docs = await api_get(_index_documents_api_path())
            if not isinstance(docs, dict):
                ui.notify(last_api_error_text("Ошибка загрузки файлов индекса"), type="negative")
                return
            doc_rows = [_doc_row(item) for item in docs.get("documents", []) if isinstance(item, dict)]
            summary = docs.get("summary", {}) if isinstance(docs.get("summary", {}), dict) else {}
            indexed = summary.get("INDEXED", {})
            pending = summary.get("PENDING", {})
            errors = summary.get("ERROR", {})
            index_kpi["total"].set_text(str(docs.get("total", len(doc_rows))))
            index_kpi["indexed"].set_text(str(indexed.get("files", row.get("indexed", 0))))
            index_kpi["pending"].set_text(str(pending.get("files", row.get("pending", 0))))
            index_kpi["errors"].set_text(str(errors.get("files", row.get("errors", 0))))
            summary_chunks = sum(int(value.get("chunks") or 0) for value in summary.values() if isinstance(value, dict))
            index_kpi["chunks"].set_text(str(summary_chunks or row.get("chunks", 0)))
            index_docs_status.set_text(
                f"показано: {len(doc_rows)}/{docs.get('total', len(doc_rows))} · "
                f"фильтр: {index_status_select.value or 'ВСЕ'} · поиск: {(index_query_input.value or '').strip() or '—'}"
            )
            index_docs_grid.rows = doc_rows
            index_docs_grid.update()
            if render_main:
                state["rag_documents"] = docs
                _render()

        async def _open_index_dialog(row):
            if not isinstance(row, dict):
                return
            selected_index["row"] = dict(row)
            name = row.get("folder") or row.get("dataset_id") or "index"
            index_title.set_text(f"ИНДЕКС // {name}")
            index_subtitle.set_text(
                " · ".join(
                    part
                    for part in [
                        f"dataset_id: {row.get('dataset_id') or '—'}",
                        f"status: {row.get('status') or '—'}",
                        f"files: {row.get('indexed', 0)}/{row.get('total', 0)}",
                        f"chunks: {row.get('chunks', 0)}",
                    ]
                    if part
                )
            )
            index_query_input.value = ""
            index_status_select.value = ""
            index_query_input.update()
            index_status_select.update()
            index_dialog.open()
            await _refresh_index_dialog_documents()

        async def _quick_index_status(status: str):
            index_status_select.value = status
            index_status_select.update()
            await _refresh_index_dialog_documents()

        async def refresh_documents_only(render: bool = True, notify: bool = True):
            docs = await api_get(_documents_api_path())
            if not isinstance(docs, dict):
                if notify:
                    ui.notify(last_api_error_text("Ошибка загрузки документов"), type="negative")
                return
            docs["source"] = docs.get("source") or "api_active_profile"
            state["rag_documents"] = docs
            if render:
                _render()

        async def _quick_docs_status(status: str):
            doc_status_select.value = status
            doc_status_select.update()
            await refresh_documents_only()

        async def _set_sensitivity(payload):
            """W3.3 (ADR-9): пометить чувствительность датасета (гейт локал/облако)."""
            if not isinstance(payload, dict):
                return
            ds_id = str(payload.get("dataset_id", "") or "")
            level = str(payload.get("level", "") or "")
            if not ds_id or level not in ("P0", "P1", "P2"):
                return
            res = await api_patch(f"/api/rag/datasets/{quote(ds_id, safe='')}/sensitivity?sensitivity={level}")
            folder = payload.get("folder", "")
            if res is not None:
                ui.notify(f"✓ {folder}: данные → {level}", type="positive")
                add_log(f"[ДАННЫЕ] {folder or ds_id} → чувствительность {level}")
            else:
                ui.notify(last_api_error_text("Не удалось изменить чувствительность"), type="negative")

        async def _set_group(payload):
            """Пользовательская группа датасета — организация списка в САМОВАРе."""
            if not isinstance(payload, dict):
                return
            ds_id = str(payload.get("dataset_id", "") or "")
            grp = str(payload.get("group", "") or "").strip()[:60]
            if not ds_id:
                return
            res = await api_patch(f"/api/rag/datasets/{quote(ds_id, safe='')}/group?group={quote(grp, safe='')}")
            folder = payload.get("folder", "")
            if res is not None:
                ui.notify(f"✓ {folder}: группа → {grp or '(снята)'}", type="positive")
                add_log(f"[ГРУППА] {folder or ds_id} → {grp or '(снята)'}")
            else:
                ui.notify(last_api_error_text("Не удалось задать группу"), type="negative")

        async def _sync_row(row):
            folder = row.get("folder", "") if isinstance(row, dict) else str(row)
            if not folder:
                return
            add_log(f"[SYNC] Запуск: {folder}")
            d = await api_post(f"/api/rag/sync/{quote(folder, safe='')}")
            if d:
                ui.notify(
                    f"✓ SYNC {folder}: job {d.get('job_id','?')} +{d.get('new_files',0)} файлов",
                    type="positive"
                )
                add_log(f"[SYNC] {folder} → job {d.get('job_id')} +{d.get('new_files',0)} новых")
                await asyncio.sleep(2)
                await refresh_and_render()
            else:
                ui.notify(last_api_error_text(f"Ошибка SYNC {folder}"), type="negative")

        async def _parse_row(row):
            """СИНК для датасета без папки-источника: допарсить его PENDING-файлы."""
            ds_id = row.get("dataset_id", "") if isinstance(row, dict) else ""
            folder = row.get("folder", "?") if isinstance(row, dict) else "?"
            if not ds_id:
                return
            pending = row.get("pending", 0) if isinstance(row, dict) else 0
            if not pending:
                ui.notify(f"{folder}: PENDING-файлов нет — всё уже в индексе", type="info")
                return
            add_log(f"[СИНК] {folder}: допарсинг {pending} PENDING")
            d = await api_post(f"/api/rag/parse-batch/{quote(ds_id, safe='')}")
            if d:
                ui.notify(f"✓ {folder}: парсинг запущен ({pending} файлов)", type="positive")
                await asyncio.sleep(2)
                await refresh_and_render()
            else:
                ui.notify(last_api_error_text(f"Ошибка парсинга {folder}"), type="negative")

        async def _reset_row(row):
            folder    = row.get("folder", "") if isinstance(row, dict) else str(row)
            ds_id     = row.get("dataset_id", "") if isinstance(row, dict) else ""
            if not folder:
                return
            chunks_count = row.get("chunks", 0) if isinstance(row, dict) else 0
            ok = await ui.run_javascript(
                f"confirm('СБРОС {folder}: удалить индекс ({chunks_count} чанков) и переиндексировать с нуля?')"
            )
            if not ok:
                return
            add_log(f"[СБРОС] {folder}: удаление датасета {ds_id} ({chunks_count} чанков)")
            if ds_id:
                d_del = await api_delete(f"/api/rag/datasets/{quote(ds_id, safe='')}")
                if not d_del:
                    ui.notify(last_api_error_text(f"Ошибка удаления датасета {folder}"), type="negative")
                    return
            ui.notify(f"↺ {folder}: индекс удалён ({chunks_count} чанков) — запускаю полную переиндексацию", type="warning")
            await asyncio.sleep(0.5)
            d = await api_post(f"/api/rag/sync/{quote(folder, safe='')}")
            if d:
                add_log(f"[СБРОС] {folder} → job {d.get('job_id')} переиндексация")
                ui.notify(f"✓ Переиндексация запущена: job {d.get('job_id','?')}", type="positive")
                await asyncio.sleep(2)
                await refresh_and_render()
            else:
                ui.notify(last_api_error_text(f"Ошибка sync после сброса {folder}"), type="negative")

        async def refresh_and_render():
            await refresh_samovar()
            await refresh_documents_only(render=False, notify=False)
            _render()
            _render_live_logs()

        def _render_reindex_progress():
            """W5.2: прогресс реиндекса из push-снимка state["reindex"] (без HTTP)."""
            rx = state.get("reindex", {}) if isinstance(state.get("reindex"), dict) else {}
            rx_total = int(rx.get("total") or 0)
            rx_done = int(rx.get("completed") or 0)
            if rx.get("running") and rx_total > 0:
                reindex_progress.set_value(min(1.0, rx_done / rx_total))
                reindex_progress.style("width:220px;display:block;")
                cur = rx.get("current_doc") or {}
                cur_name = cur.get("doc") or cur.get("file") or cur.get("name") or ""
                pct = rx.get("percent")
                eta = rx.get("eta_text") or ""
                rate = rx.get("rate_per_min")
                head = f"реиндекс: {rx_done}/{rx_total}" + (f" ({pct:.0f}%)" if pct is not None else "")
                tail = []
                if eta:
                    tail.append(f"осталось {eta}")
                if rate:
                    tail.append(f"{rate:g} док/мин")
                if cur_name:
                    tail.append(cur_name[:40])
                reindex_progress_label.set_text(head + (" · " + " · ".join(tail) if tail else ""))
            elif rx.get("paused"):
                reindex_progress.style("width:220px;display:block;")
                reindex_progress_label.set_text(f"⏸ пауза: {rx_done}/{rx_total}")
            else:
                reindex_progress.style("width:220px;display:none;")
                reindex_progress_label.set_text("")

        async def refresh_live_logs():
            await refresh_proxy_logs(140)
            _render_live_logs()
            _render_reindex_progress()  # W5.2: прогресс из push-снимка (без HTTP)

        def _render_live_logs():
            lines = list(state.get("proxy_logs") or state.get("logs") or [])[-140:]
            if not lines:
                live_log_box.set_content("<pre>log buffer empty</pre>")
                live_log_status.set_text("empty")
                return
            live_log_status.set_text(f"{len(lines)} lines · live")
            live_log_box.set_content(f"<pre>{escape(chr(10).join(lines))}</pre>")

        def _render():
            sources  = state.get("sources", [])
            rag      = state.get("rag_health", {}) if isinstance(state.get("rag_health"), dict) else {}
            datasets = rag.get("datasets") or state.get("datasets", [])
            totals   = rag.get("totals") or {}
            jobs     = state.get("jobs", {})
            docs     = state.get("rag_documents", {}) if isinstance(state.get("rag_documents"), dict) else {}
            proxy_health = state.get("proxy_health", {}) if isinstance(state.get("proxy_health"), dict) else {}
            indexing_mode = state.get("indexing_mode", {}) if isinstance(state.get("indexing_mode"), dict) else {}
            proxy_status = str(proxy_health.get("status") or "unknown").lower()
            rag_status = str(rag.get("status") or "unknown").lower()
            qdrant = rag.get("qdrant", {}) if isinstance(rag.get("qdrant"), dict) else {}
            parse_blocked = proxy_status == "error" or qdrant.get("ok") is False
            ds_map   = {d["id"]: d for d in datasets}
            dataset_names = {d.get("name", "") for d in datasets}
            dataset_options = {"": "Все датасеты"}
            dataset_options.update(
                {
                    d.get("id", ""): d.get("name", d.get("id", ""))
                    for d in datasets
                    if d.get("id")
                }
            )
            if doc_dataset_select.options != dataset_options:
                doc_dataset_select.options = dataset_options
                if doc_dataset_select.value not in dataset_options:
                    doc_dataset_select.value = ""
                doc_dataset_select.update()

            # Селектор существующих датасетов для in-place индексации внешней папки.
            ext_ds_options = {
                d.get("id", ""): d.get("name", d.get("id", ""))
                for d in datasets
                if d.get("id")
            }
            if ext_dataset_select.options != ext_ds_options:
                ext_dataset_select.options = ext_ds_options
                if ext_dataset_select.value not in ext_ds_options:
                    ext_dataset_select.value = None
                ext_dataset_select.update()

            tot_src = tot_idx = tot_pending = tot_errors = tot_chunks = 0
            rows = []
            seen_ds = set()
            for src in sources:
                folder = src.get("folder", "")
                if not src.get("dataset_id") and any(name.startswith(f"{folder}_") for name in dataset_names):
                    continue
                ds      = ds_map.get(src.get("dataset_id", "")) or {}
                total   = ds.get("files", src.get("source_files", 0))
                indexed = ds.get("indexed_files", src.get("indexed_files", 0))
                pending = ds.get("pending_files", max(0, total - indexed))
                errors  = ds.get("error_files", 0)
                chunks  = ds.get("chunks", ds.get("chunk_count", 0) or 0)
                status  = ds.get("status", src.get("dataset_status", "NOT_CREATED"))
                tot_src    += total
                tot_idx    += indexed
                tot_pending += pending
                tot_errors  += errors
                tot_chunks += chunks
                if src.get("dataset_id"):
                    seen_ds.add(src.get("dataset_id"))

                folder_jobs = [
                    j for j in jobs.values()
                    if j.get("dataset_name") == f"{src['folder']}_Index"
                ]
                last_job = None
                if folder_jobs:
                    last_job = sorted(
                        folder_jobs,
                        key=lambda j: j.get("started_at", ""),
                        reverse=True
                    )[0]

                job_info = ""
                if last_job:
                    job_info = (
                        f"{last_job['status']} "
                        f"{last_job.get('processed',0)}/{last_job.get('total',0)}"
                    )

                rows.append({
                    "folder":     folder,
                    "dataset_id": src.get("dataset_id", ""),
                    "total":      total,
                    "indexed":    indexed,
                    "pending":    pending,
                    "errors":     errors,
                    "chunks":     chunks,
                    "status":     status,
                    "sensitivity": (ds_map.get(src.get("dataset_id", "")) or {}).get("sensitivity", "P0"),
                    "group_name": (ds_map.get(src.get("dataset_id", "")) or {}).get("group_name", ""),
                    "job_info":   job_info,
                    "can_sync":    not parse_blocked,
                    "sync_reason": "парсинг сейчас заблокирован (идёт другая задача)" if parse_blocked else "",
                })

            for ds in datasets:
                ds_id = ds.get("id", "")
                if not ds_id or ds_id in seen_ds:
                    continue
                total = ds.get("files", ds.get("doc_count", 0) or 0)
                indexed = ds.get("indexed_files", ds.get("doc_count", 0) or 0)
                pending = ds.get("pending_files", 0)
                errors = ds.get("error_files", 0)
                chunks = ds.get("chunks", ds.get("chunk_count", 0) or 0)
                tot_src += total
                tot_idx += indexed
                tot_pending += pending
                tot_errors += errors
                tot_chunks += chunks
                rows.append({
                    "folder":     ds.get("name", ds_id),
                    "dataset_id": ds_id,
                    "total":      total,
                    "indexed":    indexed,
                    "pending":    pending,
                    "errors":     errors,
                    "chunks":     chunks,
                    "status":     ds.get("status", ""),
                    "sensitivity": ds.get("sensitivity", "P0"),
                    "group_name": ds.get("group_name", ""),
                    "job_info":   "",
                    "can_sync":    False,
                    "sync_reason": "нет папки-источника в RAG_Content — датасет наполняется загрузкой файлов",
                })

            if totals:
                tot_src = totals.get("files", tot_src)
                tot_idx = totals.get("indexed_files", tot_idx)
                tot_pending = totals.get("pending_files", tot_pending)
                tot_errors = totals.get("error_files", tot_errors)
                tot_chunks = totals.get("chunks", tot_chunks)

            sam_kpi["ds"].set_text(str(totals.get("datasets", len(datasets) or len(sources))))
            sam_kpi["src"].set_text(str(tot_src))
            sam_kpi["idx"].set_text(str(tot_idx))
            sam_kpi["pend"].set_text(str(tot_pending))
            sam_kpi["err"].set_text(str(tot_errors))
            sam_kpi["chunks"].set_text(str(tot_chunks))
            scheduler_jobs = [
                (jid, j) for jid, j in jobs.items()
                if j.get("type") == "rag_parse_scheduler" or "Batch " in str(j.get("message", ""))
            ]
            active_scheduler_jobs = [
                (jid, j) for jid, j in scheduler_jobs
                if str(j.get("status", "")).upper() in {"QUEUED", "PARSING", "RUNNING"}
            ]
            scheduler_candidates = active_scheduler_jobs or scheduler_jobs
            last_scheduler = sorted(
                scheduler_candidates,
                key=lambda item: item[1].get("started_at", ""),
                reverse=True,
            )[0] if scheduler_candidates else None
            mode_state = indexing_mode.get("mode", {}) if isinstance(indexing_mode.get("mode"), dict) else {}
            mode_name = mode_state.get("mode") or ("indexing" if indexing_mode.get("active") else "chat")
            profile_name = indexing_mode.get("runtime_profile") or mode_state.get("runtime_profile") or "CHAT"
            memory_state = indexing_mode.get("memory_state", {}) if isinstance(indexing_mode.get("memory_state"), dict) else {}
            chat_allowed = indexing_mode.get("chat_generation_allowed", True)
            runtime_banner.set_text(
                " · ".join(
                    [
                        f"proxy: {proxy_status}",
                        f"rag: {rag_status}",
                        f"mode: {mode_name}",
                        f"profile: {profile_name}",
                        f"memory: {memory_state.get('state', 'UNKNOWN')}",
                        f"chat: {'allowed' if chat_allowed else 'paused'}",
                        "parse: paused (Qdrant/API health)" if parse_blocked else "parse: available",
                    ]
                )
            )
            if parse_blocked or active_scheduler_jobs:
                start_scheduler_btn.props("disabled")
            else:
                start_scheduler_btn.props(remove="disabled")
            scheduler_status.set_text(
                f"pending: {tot_pending} · errors: {tot_errors} · "
                f"job: {(last_scheduler[0][:12] + ' ' + last_scheduler[1].get('status','')) if last_scheduler else '—'}"
                + (" · старт заблокирован preflight guard" if parse_blocked else "")
            )
            sam_grid.rows = rows
            sam_grid.update()

            # Опции синка: известные папки-источники (где синк возможен)
            sync_folder_input.options = sorted({r["folder"] for r in rows if r.get("can_sync")})
            sync_folder_input.update()

            # Живость шедулера: активные parse-задачи рядом с кнопкой START
            active_jobs = [j for j in jobs.values() if str(j.get("status", "")).upper() in ("RUNNING", "QUEUED", "STARTED")]
            if active_jobs:
                current = active_jobs[0]
                scheduler_live_label.set_text(
                    f"● РАБОТАЕТ: {current.get('dataset_name', '?')} {current.get('processed', 0)}/{current.get('total', 0)}"
                    + (f" (+{len(active_jobs) - 1} в очереди)" if len(active_jobs) > 1 else "")
                )
                scheduler_live_label.style("color:var(--ok);font-size:.7rem;font-weight:700;")
            else:
                scheduler_live_label.set_text("○ не запущен")
                scheduler_live_label.style("color:var(--dim);font-size:.7rem;font-weight:700;")

            _render_reindex_progress()

            # Jobs
            job_rows = []
            for jid, j in jobs.items():
                dt_str = ""
                if j.get("started_at"):
                    try:
                        dt = datetime.fromisoformat(j["started_at"].replace("Z", ""))
                        dt_str = dt.strftime("%d.%m %H:%M")
                    except Exception:
                        dt_str = j["started_at"]
                job_rows.append({
                    "job_id":   jid[:12],
                    "dataset":  j.get("dataset_name", ""),
                    "status":   j.get("status", ""),
                    "progress": f"{j.get('processed',0)}/{j.get('total',0)}",
                    "started":  dt_str,
                    "message":  j.get("message", ""),
                })
            job_rows.sort(key=lambda r: r["started"], reverse=True)
            jobs_grid.rows = job_rows
            jobs_grid.update()

            doc_rows = []
            for item in docs.get("documents", []) if isinstance(docs, dict) else []:
                doc_rows.append(_doc_row(item))
            summary = docs.get("summary", {}) if isinstance(docs, dict) else {}
            docs_source = docs.get("source", "") if isinstance(docs, dict) else ""
            docs_total = docs.get("total", len(doc_rows)) if isinstance(docs, dict) else len(doc_rows)
            docs_status.set_text(
                f"shown: {len(doc_rows)}/{docs_total} · "
                + " · ".join(
                    f"{key}: {value.get('files', 0)}"
                    for key, value in summary.items()
                )
                + (f" · source: {docs_source}" if docs_source else "")
                or "INDEXED/PENDING/ERROR"
            )
            docs_grid.rows = doc_rows
            docs_grid.update()

        index_query_input.on("keydown.enter", lambda e: asyncio.create_task(_refresh_index_dialog_documents()))
        doc_query_input.on("keydown.enter", lambda e: asyncio.create_task(refresh_documents_only()))

        # Загружаем при входе без одноразового timer, чтобы обновление не
        # прилетало в уже удалённый slot при быстрой навигации.
        asyncio.create_task(refresh_and_render())
        asyncio.create_task(refresh_map())
        live_logs_timer = ui.timer(3.0, lambda: asyncio.create_task(refresh_live_logs()))
        context.client.on_disconnect(lambda *_: live_logs_timer.cancel())
