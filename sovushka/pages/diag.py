"""
С.О.В.У.Ш.К.А. v5.0 — вкладка Д.И.А.Г.Н.О.З.
"""
from __future__ import annotations

import asyncio
import time
from nicegui import ui

from sovushka.state import state, api_get, api_post, add_log
from sovushka.config import MLX_URL
from sovushka.components.charts import _html, esc


def _build_diag_map_html(results: list) -> str:
    """Строит компактную HTML-карту контура с живыми статусами узлов."""
    result_map = {r["name"]: r for r in results}

    def st(*names: str) -> str:
        for name in names:
            if name in result_map:
                return result_map[name].get("status", "idle")
        return "idle"

    def safe_status(value: str) -> str:
        return value if value in {"ok", "warn", "err", "idle"} else "idle"

    def node(title: str, subtitle: str, status: str, *, hub: bool = False) -> str:
        status = safe_status(status)
        label = {"ok": "OK", "warn": "WARN", "err": "ERR", "idle": "WAIT"}[status]
        hub_cls = " diag-node-hub" if hub else ""
        return (
            f'<div class="diag-node diag-node-{status}{hub_cls}">'
            f'  <div class="diag-node-head">'
            f'    <span class="diag-node-dot"></span>'
            f'    <span class="diag-node-title">{esc(title)}</span>'
            f'    <span class="diag-node-state">{label}</span>'
            f'  </div>'
            f'  <div class="diag-node-sub">{esc(subtitle)}</div>'
            f'</div>'
        )

    def group(title: str, items: list[str]) -> str:
        return (
            '<div class="diag-map-group">'
            f'  <div class="diag-map-group-title">{esc(title)}</div>'
            f'  <div class="diag-map-group-body">{"".join(items)}</div>'
            '</div>'
        )

    ingress = [
        node("Сеть", "интернет / доступы", st("Интернет", "Сеть (интернет)")),
        node("С.О.В.У.Ш.К.А.", "NiceGUI :8051", "ok"),
    ]
    proxy = node("les-proxy", "FastAPI :8050", st("les-proxy :8050"), hub=True)
    groups = [
        group("RAG-память", [
            node("Qdrant", "векторы :6333", st("Qdrant :6333")),
            node("Qwen index", "chunks = points", st("Qdrant индекс", "Qdrant :6333")),
            node("SQLite", "метабаза", st("SQLite метабаза")),
        ]),
        group("Модели", [
            node("MLX Host", "локальный inference :8080", st("MLX Backend", "MLX Host :8080")),
            node("Latency", "health / chat", st("MLX latency", "Chat latency (тест)")),
            node("Т.О.С.К.А.", "quality gate", st("Т.О.С.К.А. статистика")),
        ]),
        group("Хост", [
            node("RAM", "память", st("RAM")),
            node("CPU", "нагрузка", st("CPU")),
            node("Диск", "свободное место", st("Диск")),
            node("Docker", "runtime отсутствует", st("Docker runtime", "Docker")),
        ]),
    ]

    return (
        '<div class="diag-live-map">'
        f'  <div class="diag-map-stack">{"".join(ingress)}</div>'
        '  <div class="diag-map-arrow" aria-hidden="true"></div>'
        f'  <div class="diag-map-proxy">{proxy}</div>'
        '  <div class="diag-map-arrow" aria-hidden="true"></div>'
        f'  <div class="diag-map-groups">{"".join(groups)}</div>'
        '</div>'
    )


def _build_acronym_glossary_html() -> str:
    """Возвращает компактный словарь системных сокращений."""
    items = [
        ("Л.Е.С.", "Локальная Единая Система", "ядро и рабочий контур"),
        ("С.О.В.У.Ш.К.А.", "Система Обработки и Выдачи: Умная, Шаблонизированная, Классифицированная, Автоматизированная", "интерфейс"),
        ("С.А.М.О.В.А.Р.", "Система Автономной Машинной Обработки Внутренних Архивов RAG", "индекс знаний"),
        ("П.Р.О.Р.А.Б.", "Программа Регулярной Оценки Работы Автономной Базы", "метрики"),
        ("Д.И.А.Г.Н.О.З.", "Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья", "проверки"),
        ("Т.О.С.К.А.", "Терминал Оценки, Самопроверки и Контроля Архитектуры", "валидация"),
        ("В.О.Л.К.", "Внутренний Охранный Локальный Контур", "доступ"),
        ("Е.Ж.И.К.", "Единый Журнал Импорта Корреспонденции", "почта (IMAP-сбор писем в RAG)"),
        ("С.У.Х.А.Р.И.К.", "Система Управления Холодными Архивами и Резервными Источниками Комплекса", "резервные копии"),
        ("П.А.У.К.", "Постоянный Активный Удалённый Канал", "сеть / туннель доступа (keepalive)"),
        ("К.О.Т.", "Классификатор Областей и Терминов", "таксономия доменов и синонимов"),
        ("RAG", "Retrieval-Augmented Generation", "ответ с поиском по источникам"),
        ("CRAG", "Corrective RAG", "контроль достоверности ответа"),
        ("MLX", "Apple MLX / Metal runtime", "локальные модели"),
    ]
    cards = []
    for code, full, role in items:
        cards.append(
            '<div class="diag-acronym-item">'
            f'  <div class="diag-acronym-code">{esc(code)}</div>'
            f'  <div class="diag-acronym-full">{esc(full)}</div>'
            f'  <div class="diag-acronym-role">{esc(role)}</div>'
            '</div>'
        )
    return '<div class="diag-acronym-grid">' + "".join(cards) + "</div>"


def _normalize_diag_payload(payload: dict) -> dict:
    """Сглаживает старый контракт /api/diag под no-Docker runtime без рестарта proxy."""
    normalized = dict(payload or {})
    raw_checks = list((payload or {}).get("checks", []))
    mlx_health_ok = any(
        raw.get("name") == "MLX latency" and "MLX health OK" in str(raw.get("message", ""))
        for raw in raw_checks
    )
    checks = []
    for raw in raw_checks:
        item = dict(raw)
        name = item.get("name", "")
        value_msg = f"{item.get('value', '')} {item.get('message', '')}".lower()
        docker_missing = (
            name == "Docker"
            and item.get("status") == "err"
            and ("no such file" in value_msg or "not found" in value_msg or "docker" in value_msg)
        )
        if docker_missing:
            item.update(
                name="Docker runtime",
                status="ok",
                value="removed",
                expected="no Docker",
                message="Qdrant/proxy/UI/MLX run on host LaunchAgents",
            )
        elif name == "MLX Backend" and item.get("status") == "err" and mlx_health_ok:
            item.update(
                status="warn",
                value="main idle",
                expected="health OK",
                message="MLX health отвечает; основная модель загружается лениво",
            )
        elif (
            name == "Т.О.С.К.А. статистика"
            and item.get("status") == "err"
            and str(item.get("value", "")).startswith("V:0 N:0 H:0")
        ):
            item.update(
                status="warn",
                expected="first validation sample",
                message="статистики валидации ещё нет",
            )
        checks.append(item)

    ok_count = sum(1 for result in checks if result.get("status") == "ok")
    warn_count = sum(1 for result in checks if result.get("status") == "warn")
    err_count = sum(1 for result in checks if result.get("status") == "err")
    normalized.update(
        checks=checks,
        ok_count=ok_count,
        warn_count=warn_count,
        err_count=err_count,
        overall="ok" if err_count == 0 and warn_count <= 1 else ("warn" if err_count == 0 else "err"),
    )
    return normalized


def build_diag():
    """Строит содержимое вкладки Д.И.А.Г.Н.О.З. Вызывать внутри with ui.tab_panel(tab_diag)."""
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):

        # ── Заголовок и кнопка ──────────────────
        with ui.row().classes("items-center justify-between w-full"):
            with ui.column().classes("gap-0"):
                ui.label("Д.И.А.Г.Н.О.З.").style(
                    "font-size:1rem;font-weight:900;letter-spacing:1px;"
                )
                ui.label("Диспетчер Инфраструктурного Анализа Готовности, Нагрузки, Ошибок и Здоровья").style(
                    "font-size:.62rem;color:var(--dim);"
                )
                diag_ts_lbl = ui.label("Последний прогон: —").style(
                    "font-size:.6rem;color:var(--dim);"
                )
            with ui.row().classes("gap-2"):
                diag_run_btn = ui.button(
                    "▶ ЗАПУСТИТЬ ПРОВЕРКУ",
                    on_click=lambda: asyncio.create_task(run_diag())
                ).props("no-caps").style(
                    "background:rgba(59,130,246,.15);border:1px solid var(--accent);"
                    "color:var(--accent);font-family:var(--font);font-weight:900;font-size:.75rem;"
                )
                ui.button(
                    "📋 В ЛОГ",
                    on_click=lambda: _diag_to_log()
                ).props("no-caps flat").style("font-size:.7rem;color:var(--dim);")

        # ── Итоговые KPI диагностики ─────────────
        with ui.row().classes("w-full gap-3"):
            diag_overall = _html(
                '<div class="kpi-box flex-1" style="text-align:center;">'
                '<div class="kpi-val" style="font-size:2rem;">—</div>'
                '<div class="kpi-lbl">ОБЩИЙ СТАТУС</div></div>'
            )
            diag_ok_kpi   = _diag_kpi_box("—", "ОК",          "var(--ok)")
            diag_warn_kpi = _diag_kpi_box("—", "ПРЕДУПРЕЖДЕНИЙ", "var(--warn)")
            diag_err_kpi  = _diag_kpi_box("—", "ОШИБОК",      "var(--err)")
            diag_time_kpi = _diag_kpi_box("—", "ВРЕМЯ (мс)",  "var(--dim)")

        # ── Живая схема состояния ────────────────
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between mb-2"):
                _html('<div class="section-title">ЖИВАЯ КАРТА КОНТУРА</div>')
                ui.label("Цвет узла = результат последнего прогона").style("font-size:.6rem;color:var(--dim);")
            with ui.element("div").classes("diag-map-wrap"):
                diag_map = _html(_build_diag_map_html([])).classes("w-full")

        # ── С.У.Х.А.Р.И.К. Резервные копии ────────
        with ui.card().classes("card-les w-full"):
            with ui.row().classes("items-center justify-between w-full mb-2"):
                with ui.column().classes("gap-0"):
                    _html('<div class="section-title">С.У.Х.А.Р.И.К. — РЕЗЕРВНЫЕ КОПИИ</div>')
                    ui.label("Управление снапшотами Qdrant и SQLite метабазой (ротация 3 копии)").style(
                        "font-size:.62rem;color:var(--dim);"
                    )
                with ui.row().classes("gap-2"):
                    backup_create_btn = ui.button(
                        "⚡ СОЗДАТЬ БЭКАП",
                        on_click=lambda: asyncio.create_task(create_backup())
                    ).props("no-caps").style(
                        "background:rgba(16,185,129,.15);border:1px solid var(--ok);"
                        "color:var(--ok);font-family:var(--font);font-weight:900;font-size:.75rem;"
                    )
                    backup_restore_btn = ui.button(
                        "♻ ВОССТАНОВИТЬ",
                        on_click=lambda: asyncio.create_task(open_restore_dialog())
                    ).props("no-caps").style(
                        "background:rgba(245,181,74,.12);border:1px solid var(--warn);"
                        "color:var(--warn);font-family:var(--font);font-weight:900;font-size:.75rem;"
                    )

            # Контейнер для списков
            backup_lists_el = ui.column().classes("w-full gap-3")

        # ── Словарь сокращений ───────────────────
        with ui.card().classes("card-les w-full"):
            _html('<div class="section-title" style="margin-bottom:8px;">СЛОВАРЬ АКРОНИМОВ</div>')
            _html(_build_acronym_glossary_html()).classes("w-full")

        # ── Визуализация — карточки чеков ────────
        diag_cards = ui.grid(columns=2).classes("w-full gap-3")

        # ── Лог диагностики ───────────────────────
        with ui.card().classes("card-les w-full"):
            _html('<div class="section-title" style="margin-bottom:8px;">ЛОГ ПРОГОНА</div>')
            diag_log_el = ui.log(max_lines=80).classes("w-full").style(
                "background:var(--bg);color:var(--ok);font-family:var(--font);"
                "font-size:.68rem;height:160px;border:none;"
            )

        # Таймер для начальной загрузки бэкапов
        ui.timer(0.1, lambda: asyncio.create_task(load_backups()), once=True)

    # ── Вспомогательные функции диагностики ──────────

    STATUS_ICON  = {"ok": "✓", "warn": "⚠", "err": "✗"}
    STATUS_COLOR = {"ok": "var(--ok)", "warn": "var(--warn)", "err": "var(--err)"}
    STATUS_TAG   = {"ok": "tag-ok", "warn": "tag-warn", "err": "tag-err"}

    async def load_backups():
        data = await api_get("/api/backup/status")
        backup_lists_el.clear()
        if not data:
            with backup_lists_el:
                ui.label("Не удалось загрузить статус бэкапов").style("color:var(--err);font-size:.75rem;")
            return

        sqlite_backups = data.get("sqlite_backups", [])
        qdrant_snapshots = data.get("qdrant_snapshots", [])
        profile = data.get("profile", "unknown")
        collection = data.get("collection_name", "unknown")

        with backup_lists_el:
            with ui.row().classes("w-full gap-3"):
                # Столбец SQLite
                with ui.column().classes("flex-1 gap-2"):
                    ui.label(f"SQLite Метабаза ({profile})").style("font-size:.75rem;font-weight:900;color:var(--accent);")
                    if not sqlite_backups:
                        ui.label("Нет доступных копий SQLite").style("font-size:.7rem;color:var(--dim);")
                    for b in sqlite_backups:
                        size_mb = b['size_bytes'] / (1024 * 1024)
                        dt = b['created_at'].split('.')[0].replace('T', ' ')
                        with ui.row().classes("items-center justify-between w-full p-2 rounded").style(
                            "background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
                        ):
                            with ui.column().classes("gap-0"):
                                ui.label(b['name']).style("font-size:.7rem;font-weight:700;color:var(--text);")
                                ui.label(f"{size_mb:.1f} MB | {dt}").style("font-size:.6rem;color:var(--dim);")
                            ui.button(
                                "✗",
                                on_click=lambda _, name=b['name']: asyncio.create_task(delete_backup_item("sqlite", name))
                            ).props("flat dense").style("color:var(--err);font-weight:900;")

                # Столбец Qdrant
                with ui.column().classes("flex-1 gap-2"):
                    ui.label(f"Qdrant Снапшоты ({collection})").style("font-size:.75rem;font-weight:900;color:var(--accent);")
                    if not qdrant_snapshots:
                        ui.label("Нет доступных снапшотов Qdrant").style("font-size:.7rem;color:var(--dim);")
                    for s in qdrant_snapshots:
                        size_mb = s['size_bytes'] / (1024 * 1024)
                        dt = s['created_at'].split('.')[0].replace('T', ' ')
                        with ui.row().classes("items-center justify-between w-full p-2 rounded").style(
                            "background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
                        ):
                            with ui.column().classes("gap-0"):
                                ui.label(s['name']).style("font-size:.7rem;font-weight:700;color:var(--text);")
                                ui.label(f"{size_mb:.1f} MB | {dt}").style("font-size:.6rem;color:var(--dim);")
                            ui.button(
                                "✗",
                                on_click=lambda _, name=s['name']: asyncio.create_task(delete_backup_item("qdrant", name))
                            ).props("flat dense").style("color:var(--err);font-weight:900;")

    async def create_backup():
        backup_create_btn.props("disabled")
        backup_create_btn.set_text("⌛ Создание...")
        ui.notify("Запущено создание резервной копии SQLite & Qdrant...", type="info")
        res = await api_post("/api/backup/create")
        backup_create_btn.props(remove="disabled")
        backup_create_btn.set_text("⚡ СОЗДАТЬ БЭКАП")
        if res:
            sqlite_ok = res.get("sqlite", {}).get("ok")
            qdrant_ok = res.get("qdrant", {}).get("ok")
            if sqlite_ok and qdrant_ok:
                ui.notify("Резервная копия SQLite и Qdrant успешно создана", type="positive")
            else:
                ui.notify("Создание бэкапа завершилось с ошибками", type="warning")
            await load_backups()
        else:
            ui.notify("Ошибка при создании резервной копии", type="negative")

    async def open_restore_dialog():
        data = await api_get("/api/backup/archives") or {}
        archives = data.get("archives", [])
        with ui.dialog() as dlg, ui.card().style(
            "background:var(--bg-panel);border:1px solid var(--border);min-width:480px;max-width:640px;max-height:74vh;padding:16px;"
        ):
            ui.label("Восстановление из архива").style("font-weight:900;font-size:.85rem;")
            ui.label("Перезапишет ЖИВОЙ индекс Qdrant и метабазу SQLite. .env не трогается. Сервис перезапустится.").style(
                "font-size:.64rem;color:var(--warn);line-height:1.4;margin-bottom:6px;"
            )
            if not archives:
                ui.label("Полных off-disk архивов нет (backup_runtime.sh → /Volumes/Data или storage/backups).").style(
                    "font-size:.66rem;color:var(--dim);"
                )
            with ui.scroll_area().style("max-height:48vh;width:100%;"):
                for a in archives:
                    gb = a.get("size_bytes", 0) / (1024 ** 3)
                    dt = str(a.get("created_at", "")).split(".")[0].replace("T", " ")
                    meta = (f"{gb:.1f} GB · {len(a.get('snapshots', []))} снапшотов"
                            + ("  · +SQLite" if a.get("has_sqlite") else "") + f" · {dt}")
                    with ui.row().classes("items-center justify-between w-full p-2 rounded").style(
                        "background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);"
                    ):
                        with ui.column().classes("gap-0"):
                            ui.label(a["name"]).style("font-size:.72rem;font-weight:700;color:var(--text);")
                            ui.label(meta).style("font-size:.6rem;color:var(--dim);")
                        ui.button("Восстановить",
                                  on_click=lambda _, p=a["path"], n=a["name"]: asyncio.create_task(confirm_restore(p, n, dlg))
                                  ).props("no-caps dense").style(
                            "background:rgba(245,181,74,.15);border:1px solid var(--warn);color:var(--warn);font-size:.66rem;"
                        )
            ui.button("Закрыть", on_click=dlg.close).props("flat dense no-caps").style("color:var(--dim);margin-top:6px;")
        dlg.open()

    async def confirm_restore(path: str, name: str, parent_dlg):
        with ui.dialog() as c, ui.card().style(
            "background:var(--bg-panel);border:1px solid var(--err);padding:16px;max-width:460px;"
        ):
            ui.label("Точно восстановить?").style("font-weight:900;color:var(--err);font-size:.8rem;")
            ui.label(f"Архив «{name}». ПЕРЕЗАПИШЕТ текущий индекс и метабазу. Прежняя метабаза сохранится "
                     "рядом как .pre_restore. Сервис перезапустится.").style(
                "font-size:.66rem;color:var(--text);line-height:1.4;"
            )
            with ui.row().classes("gap-2 justify-end w-full").style("margin-top:8px;"):
                ui.button("Отмена", on_click=c.close).props("flat dense no-caps").style("color:var(--dim);")
                ui.button("Восстановить", on_click=lambda: asyncio.create_task(do_restore(path, c, parent_dlg))
                          ).props("dense no-caps").style("background:var(--err);color:#fff;font-weight:700;font-size:.66rem;")
        c.open()

    async def do_restore(path: str, c, parent_dlg):
        c.close(); parent_dlg.close()
        res = await api_post("/api/backup/restore", {"archive_path": path})
        if res and res.get("status") == "launched":
            ui.notify(f"Восстановление запущено: {res.get('archive')}. Сервис перезапустится…", type="warning", timeout=10000)
        else:
            ui.notify("Не удалось запустить восстановление", type="negative")

    async def delete_backup_item(type_str: str, name: str):
        res = await api_post("/api/backup/delete", {"type": type_str, "name": name})
        if res and res.get("status") == "ok":
            ui.notify(f"Удалено успешно: {name}", type="positive")
            await load_backups()
        else:
            ui.notify(f"Ошибка при удалении {name}", type="negative")

    def _render_diag_cards():
        results = state.get("diag_results", [])
        diag_cards.clear()
        with diag_cards:
            for r in results:
                s = r["status"]
                color = STATUS_COLOR.get(s, "var(--dim)")
                icon  = STATUS_ICON.get(s, "?")
                tag   = STATUS_TAG.get(s, "tag-dim")
                with ui.card().classes("card-les").style(
                    f"border-left:3px solid {color};"
                ):
                    with ui.row().classes("items-center justify-between mb-1"):
                        ui.label(r["name"]).style(
                            "font-size:.78rem;font-weight:900;color:var(--text);"
                        )
                        _html(f'<span class="{tag}">{icon} {s.upper()}</span>')
                    with ui.row().classes("items-center gap-3"):
                        ui.label(r["value"]).style(
                            f"font-size:.85rem;font-weight:900;color:{color};"
                        )
                        ui.label(f"ожидалось: {r['expected']}").style(
                            "font-size:.6rem;color:var(--dim);"
                        )
                    if r.get("message"):
                        ui.label(r["message"]).style(
                            "font-size:.65rem;color:var(--dim);margin-top:2px;"
                        )
                    ui.label(f"⏱ {r['latency_ms']} ms").style(
                        "font-size:.6rem;color:var(--border-hl, #4a5568);margin-top:4px;"
                    )

    async def run_diag():
        if state["diag_running"]:
            ui.notify("Диагностика уже запущена", type="warning")
            return

        state["diag_running"] = True
        diag_run_btn.props("disabled")
        diag_run_btn.set_text("⌛ Диагностика...")
        diag_log_el.clear()

        add_log("[DIAG] ▶ Запуск диагностики системы...")
        diag_log_el.push("> [С.О.В.У.Ш.К.А.] Запуск диагностики...")

        try:
            d = await api_get("/api/diag")

            if d is None:
                diag_log_el.push("> [WARN] /api/diag не найден — запуск встроенной диагностики")
                d = await _run_local_diag()
            else:
                d = _normalize_diag_payload(d)

            state["diag_results"] = d.get("checks", [])
            overall = d.get("overall", "warn")
            ok_c    = d.get("ok_count", 0)
            warn_c  = d.get("warn_count", 0)
            err_c   = d.get("err_count", 0)
            total_ms = d.get("total_ms", 0)
            ts      = d.get("timestamp", "—")

            overall_icon = {"ok": "✓ ОК", "warn": "⚠ WARN", "err": "✗ ОШИБКИ"}.get(overall, "?")
            overall_color = STATUS_COLOR.get(overall, "var(--dim)")
            diag_overall.set_content(
                f'<div class="kpi-box flex-1" style="text-align:center;border-color:{overall_color};">'
                f'<div class="kpi-val" style="font-size:2rem;color:{overall_color};">{overall_icon}</div>'
                f'<div class="kpi-lbl">ОБЩИЙ СТАТУС</div></div>'
            )
            diag_ok_kpi.set_text(str(ok_c))
            diag_warn_kpi.set_text(str(warn_c))
            diag_err_kpi.set_text(str(err_c))
            diag_time_kpi.set_text(f"{total_ms:.0f}")
            diag_ts_lbl.set_text(f"Последний прогон: {ts}")

            _render_diag_cards()

            diag_map.set_content(_build_diag_map_html(state["diag_results"]))

            for r in state["diag_results"]:
                icon = STATUS_ICON.get(r["status"], "?")
                line = (f"> [{icon}] {r['name']:30s}  "
                        f"{r['value']:25s}  {r['latency_ms']:6.1f}ms"
                        + (f"  ← {r['message']}" if r.get('message') else ""))
                diag_log_el.push(line)
                add_log(f"[DIAG] {icon} {r['name']}: {r['value']}")

            diag_log_el.push(
                f"> [═══] Итог: {ok_c}✓ {warn_c}⚠ {err_c}✗  "
                f"| Статус: {overall.upper()}  | Время: {total_ms:.0f} мс"
            )
            add_log(f"[DIAG] Завершено: {ok_c}✓ {warn_c}⚠ {err_c}✗ за {total_ms:.0f}мс")

        except Exception as ex:
            diag_log_el.push(f"> [ERR] Критическая ошибка диагностики: {ex}")
            add_log(f"[DIAG] ОШИБКА: {ex}")
        finally:
            state["diag_running"] = False
            diag_run_btn.props(remove="disabled")
            diag_run_btn.set_text("▶ ЗАПУСТИТЬ ПРОВЕРКУ")

    async def _run_local_diag() -> dict:
        """Встроенная диагностика — имена чеков соответствуют карте в _build_diag_map_html."""
        results = []
        t0 = time.time()

        async def _chk(name, coro):
            t = time.time()
            try:
                status, value, expected, msg = await coro
            except Exception as e:
                status, value, expected, msg = "err", "exception", "—", str(e)
            ms = round((time.time() - t) * 1000, 1)
            results.append({"name": name, "status": status, "value": str(value),
                             "expected": str(expected), "message": msg, "latency_ms": ms})

        # ── Прокси (les-proxy) ──
        async def chk_proxy():
            r = await api_get("/api/health")
            ok = r is not None
            return ("ok" if ok else "err"), ("UP" if ok else "DOWN"), "UP", ""
        await _chk("les-proxy :8050", chk_proxy())

        # ── MLX Host — имя совпадает с node_map ──
        async def chk_mlx():
            r = await api_get("/api/health", base=MLX_URL)
            if not r:
                return "err", "DOWN", "UP", "MLX Host недоступен"
            m = r.get("main_model") or r.get("model", "?")
            if isinstance(m, dict):
                model_name = m.get("path", "?")
                is_loaded = m.get("loaded", False)
            else:
                model_name = str(m)
                is_loaded = r.get("main_loaded", True)
            status = "ok" if is_loaded else "warn"
            val_str = f"{model_name} [{'LIVE' if is_loaded else 'IDLE'}]"
            return status, val_str, "LIVE", ""
        await _chk("MLX Host :8080", chk_mlx())

        # ── Qdrant — имя совпадает с node_map ──
        async def chk_qdrant():
            r = await api_get("/api/metrics")
            if not r:
                return "warn", "DOWN", "UP", "metrics недоступны"
            rag = r.get("rag", {})
            st = rag.get("status", "?")
            chunks = rag.get("chunks", 0)
            ok = st in ("ready", "ok")
            return ("ok" if ok else "warn"), f"{chunks} chunks / {st}", "ready", ""
        await _chk("Qdrant :6333", chk_qdrant())

        # ── Qdrant индекс ──
        async def chk_qdrant_idx():
            r = await api_get("/api/rag/datasets")
            if r is None:
                return "err", "—", "—", "datasets недоступны"
            indexed = [d for d in r if d.get("status") in ("INDEXED", "READY")]
            total = len(r)
            ok_flag = len(indexed) > 0
            return ("ok" if ok_flag else "warn"), f"{len(indexed)}/{total} indexed", "≥1", ""
        await _chk("Qdrant индекс", chk_qdrant_idx())

        # ── MLX loaded models ──
        async def chk_mlx_models():
            r = await api_get("/api/status")
            if not r:
                return "warn", "—", "status", "status недоступен"
            mlx = r.get("mlx", {})
            models = mlx.get("models", [])
            if models:
                return "ok", f"{len(models)} loaded", "0+ guarded", ""
            return "ok", "0 loaded", "0+ guarded", "Модели выгружены до запроса"
        await _chk("MLX loaded models", chk_mlx_models())

        # ── Docker intentionally absent in the current host-launchd runtime ──
        async def chk_no_docker():
            return "ok", "removed", "no Docker", "Qdrant/proxy/UI/MLX run on host LaunchAgents"
        await _chk("Docker runtime", chk_no_docker())

        # ── RAM / CPU / Диск из метрик ──
        metrics_data = state.get("metrics", {})
        sys_m = metrics_data.get("system", {})

        async def chk_ram():
            ram_used = sys_m.get("ram_used", 0)
            ram_total = sys_m.get("ram_total", 24) or 24
            pct = ram_used / ram_total * 100
            if pct > 90:
                return "err", f"{ram_used:.1f}/{ram_total:.0f} GB ({pct:.0f}%)", "<90%", "Критически мало RAM"
            if pct > 75:
                return "warn", f"{ram_used:.1f}/{ram_total:.0f} GB ({pct:.0f}%)", "<75%", ""
            return "ok", f"{ram_used:.1f}/{ram_total:.0f} GB ({pct:.0f}%)", "<75%", ""
        await _chk("RAM", chk_ram())

        async def chk_cpu():
            cpu = sys_m.get("cpu", 0)
            if cpu > 90:
                return "err", f"{cpu:.1f}%", "<90%", "Высокая нагрузка"
            if cpu > 70:
                return "warn", f"{cpu:.1f}%", "<70%", ""
            return "ok", f"{cpu:.1f}%", "<70%", ""
        await _chk("CPU", chk_cpu())

        async def chk_disk():
            du = sys_m.get("disk_used", 0)
            dt = sys_m.get("disk_total", 512) or 512
            pct = du / dt * 100
            if pct > 90:
                return "err", f"{du:.0f}/{dt:.0f} GB", "<90%", "Диск почти заполнен"
            if pct > 75:
                return "warn", f"{du:.0f}/{dt:.0f} GB", "<75%", ""
            return "ok", f"{du:.0f}/{dt:.0f} GB", "<75%", ""
        await _chk("Диск", chk_disk())

        # ── Сеть ──
        async def chk_net():
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as c:
                    resp = await c.get("https://api.ipify.org")
                    return "ok", "Доступна", "UP", ""
            except Exception as e:
                return "err", "Недоступна", "UP", str(e)
        await _chk("Сеть (интернет)", chk_net())

        total_ms = round((time.time() - t0) * 1000, 1)
        ok_c   = sum(1 for r in results if r["status"] == "ok")
        warn_c = sum(1 for r in results if r["status"] == "warn")
        err_c  = sum(1 for r in results if r["status"] == "err")
        overall = "ok" if err_c == 0 and warn_c <= 1 else ("warn" if err_c == 0 else "err")
        import time as _t
        return {
            "overall": overall, "ok_count": ok_c, "warn_count": warn_c,
            "err_count": err_c, "total_ms": total_ms,
            "timestamp": _t.strftime("%Y-%m-%dT%H:%M:%S"),
            "checks": results,
        }

    def _diag_to_log():
        results = state.get("diag_results", [])
        if not results:
            add_log("[DIAG] Нет данных — сначала запусти диагностику")
            ui.notify("Сначала запусти диагностику", type="warning")
            return
        add_log("─" * 60)
        add_log("[DIAG] ОТЧЁТ ДИАГНОСТИКИ СИСТЕМЫ Л.Е.С.")
        add_log("─" * 60)
        for r in results:
            icon = STATUS_ICON.get(r["status"], "?")
            add_log(f"[DIAG] {icon} {r['name']}: {r['value']}  ({r['latency_ms']}ms)"
                    + (f" — {r['message']}" if r.get("message") else ""))
        add_log("─" * 60)
        ui.notify("Результаты записаны в лог", type="positive")


def _diag_kpi_box(val: str, lbl: str, color: str):
    """Хелпер для отрисовки KPI."""
    with ui.card().classes("kpi-box flex-1"):
        v = ui.label(val).style(f"font-size:1.6rem;font-weight:900;color:{color};")
        ui.label(lbl).style("font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;")
    return v
