from __future__ import annotations
"""
С.О.В.У.Ш.К.А. // v4.0 — NiceGUI Edition
==========================================
Полный переезд с FastAPI+HTML+JS на NiceGUI.

Запуск:
    uv run sovushka_ng.py
    # или
    python3 sovushka_ng.py

Порты:
    Совушка UI  → http://localhost:8051
    les-proxy   → http://localhost:8050  (бэкенд)
    MLX Host    → http://localhost:8080
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Optional, Union

import statistics
import httpx
from nicegui import app, ui

# ─────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────
PROXY_URL  = "http://localhost:8050"
MLX_URL    = "http://127.0.0.1:8080"
UI_PORT    = 8051
DARK_THEME = True

# ─────────────────────────────────────────
# CSS — сохраняем дух оригинала
# ─────────────────────────────────────────

def _html(content: str) -> "ui.html":
    return ui.html(content, sanitize=False)

CUSTOM_CSS = """
<style>
:root {
  --bg:       #08090b;
  --bg-panel: #12151a;
  --bg-mod:   #1a1e25;
  --text:     #ffffff;
  --dim:      #94a3b8;
  --border:   #2d3748;
  --accent:   #3b82f6;
  --ok:       #10b981;
  --pauk:     #8b5cf6;
  --warn:     #f59e0b;
  --err:      #ef4444;
  --font:     'Courier New', Courier, monospace;
}
body, .nicegui-content { font-family: var(--font) !important; }
.les-header {
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.les-brand { font-weight: 900; font-size: 1.1rem; color: var(--accent); }
.kpi-box {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px 20px;
  min-width: 120px;
}
.kpi-val  { font-size: 1.6rem; font-weight: 900; line-height: 1; }
.kpi-lbl  { font-size: .62rem; text-transform: uppercase; color: var(--dim); margin-top: 5px; letter-spacing: .5px; }
.card-les {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
}
.section-title {
  font-size: .68rem;
  font-weight: 900;
  text-transform: uppercase;
  color: var(--dim);
  letter-spacing: .4px;
}
.tag-ok   { background:rgba(16,185,129,.15); color:var(--ok);   border:1px solid rgba(16,185,129,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-warn { background:rgba(245,158,11,.15); color:var(--warn); border:1px solid rgba(245,158,11,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-err  { background:rgba(239,68,68,.15);  color:var(--err);  border:1px solid rgba(239,68,68,.3);  border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-dim  { background:var(--border); color:var(--dim); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-acc  { background:rgba(59,130,246,.15); color:var(--accent); border:1px solid rgba(59,130,246,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.tag-pauk { background:rgba(139,92,246,.15); color:var(--pauk);  border:1px solid rgba(139,92,246,.3); border-radius:10px; padding:2px 8px; font-size:.6rem; font-weight:700; }
.mode-rag  { background:rgba(16,185,129,.1); border:1px solid var(--ok);   color:var(--ok);   border-radius:4px; padding:5px 14px; font-weight:900; font-size:.7rem; cursor:pointer; }
.mode-code { background:rgba(139,92,246,.1); border:1px solid var(--pauk); color:var(--pauk); border-radius:4px; padding:5px 14px; font-weight:900; font-size:.7rem; cursor:pointer; }
.hbar { height:16px; background:var(--border); border-radius:4px; overflow:hidden; display:flex; }
.hbar-seg { height:100%; transition:width .5s; }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; background:var(--ok); }
.dot-warn { background:var(--warn); }
.dot-err  { background:var(--err); }
.dot-idle { background:var(--border); }
.mermaid-wrap { background:var(--bg-mod); border:1px solid var(--border); border-radius:8px; padding:16px; }
.output-table { width:100%; border-collapse:collapse; font-size:.75rem; }
.output-table th { padding:8px 12px; background:var(--bg-mod); border-bottom:1px solid var(--border); color:var(--dim); font-weight:700; text-transform:uppercase; font-size:.6rem; letter-spacing:.4px; text-align:left; }
.output-table td { padding:7px 12px; border-bottom:1px solid var(--border); color:var(--text); vertical-align:top; }
.output-table tr:hover td { background:var(--bg-mod); }
.chat-msg-user { align-self:flex-end; background:var(--border); border-right:3px solid var(--pauk); border-radius:6px; padding:10px 14px; max-width:80%; font-size:.8rem; line-height:1.5; }
.chat-msg-ai   { align-self:flex-start; background:var(--bg); border:1px solid var(--border); border-left:3px solid var(--accent); border-radius:6px; padding:10px 14px; max-width:85%; font-size:.8rem; line-height:1.5; }
.chat-msg-sys  { align-self:center; color:var(--dim); font-size:.7rem; border:1px solid var(--border); border-radius:4px; padding:4px 12px; }
.src-tag { font-size:.6rem; font-weight:700; padding:2px 6px; border:1px solid var(--ok); color:var(--ok); border-radius:4px; margin-right:4px; }
.src-tag-err { border-color:var(--err); color:var(--err); }
.typing::after { content:'▋'; animation:blink 1s step-end infinite; opacity:.7; margin-left:4px; }
@keyframes blink { 50%{opacity:0} }
</style>
"""

# ─────────────────────────────────────────
# СОСТОЯНИЕ ПРИЛОЖЕНИЯ
# ─────────────────────────────────────────
state = {
    "mode": "rag",
    "mode_model": "mlx-community/Qwen3-14B-4bit",
    "metrics": {},
    "status": {},
    "mlx_health": {},
    "datasets": [],
    "sources": [],
    "jobs": {},
    "chat_history": [],   # list of {role, text, srcs, crag}
    "logs": [],
    "mermaid_last": "",
    "output_template": None,  # образец таблицы выдачи
    "diag_results": [],       # последний прогон диагностики
    "diag_running": False,
}

# ─────────────────────────────────────────
# HTTP КЛИЕНТ
# ─────────────────────────────────────────
http = httpx.AsyncClient(timeout=30.0)


async def api_get(path: str, base: str = PROXY_URL) -> Optional[Union[dict, list]]:
    try:
        r = await http.get(f"{base}{path}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        add_log(f"[ERR] GET {path}: {e}")
        return None


async def api_post(path: str, data: dict = None, base: str = PROXY_URL) -> Optional[dict]:
    try:
        r = await http.post(f"{base}{path}", json=data or {})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        add_log(f"[ERR] POST {path}: {e}")
        return None


async def api_delete(path: str, base: str = PROXY_URL) -> Optional[dict]:
    try:
        r = await http.delete(f"{base}{path}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        add_log(f"[ERR] DELETE {path}: {e}")
        return None


# ─────────────────────────────────────────
# ЛОГИ
# ─────────────────────────────────────────
log_element = None  # заполняется после ui.log()

def add_log(msg: str):
    t = datetime.now().strftime("%H:%M:%S")
    line = f"> [{t}] {msg}"
    state["logs"].append(line)
    if len(state["logs"]) > 200:
        state["logs"] = state["logs"][-200:]
    if log_element is not None:
        log_element.push(line)


# ─────────────────────────────────────────
# ФОНОВЫЕ ЗАДАЧИ
# ─────────────────────────────────────────
async def refresh_metrics():
    d = await api_get("/api/metrics")
    if d:
        state["metrics"] = d
        add_log(f"[METRICS] CPU:{d.get('system',{}).get('cpu',0):.1f}% RAM:{d.get('system',{}).get('ram_used',0):.1f}GB")

async def refresh_status():
    d = await api_get("/api/status")
    if d:
        state["status"] = d
        mode = d.get("mode", {})
        if mode.get("mode"):
            state["mode"] = mode["mode"]

async def refresh_mlx():
    d = await api_get("/api/health", base=MLX_URL)
    if d:
        state["mlx_health"] = d
        add_log(f"[MLX] UP · main={d.get('main_model','?')}")
    else:
        state["mlx_health"] = {}

async def refresh_samovar():
    src = await api_get("/api/rag/sources")
    ds  = await api_get("/api/rag/datasets")
    if src is not None:
        state["sources"] = src
    if ds is not None:
        state["datasets"] = ds
    j = await api_get("/api/jobs")
    if j:
        state["jobs"] = j
    add_log(f"[С.А.М.О.В.А.Р.] {len(state['sources'])} папок")

async def bg_loop():
    """Главный фоновый цикл опроса"""
    tick = 0
    while True:
        await asyncio.sleep(5)
        tick += 1
        await refresh_metrics()
        if tick % 2 == 0:
            await refresh_status()
        if tick % 3 == 0:
            await refresh_mlx()
        if tick % 6 == 0:
            await refresh_samovar()


# ─────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────
def pct_bar_html(segments: list[tuple[float, str]], height: int = 16) -> str:
    """Генерирует HTML полосы прогресса из сегментов [(pct, color), ...]"""
    segs = "".join(
        f'<div class="hbar-seg" style="width:{p:.1f}%;background:{c};"></div>'
        for p, c in segments
    )
    return f'<div class="hbar" style="height:{height}px;">{segs}</div>'


def dot_html(status: str = "ok") -> str:
    cls = {"ok": "", "warn": " dot-warn", "err": " dot-err", "idle": " dot-idle"}.get(status, "")
    return f'<span class="dot{cls}"></span>'


def _status_color(s: str) -> str:
    s = (s or "").upper()
    if s in ("INDEXED", "READY", "COMPLETED"):
        return "ok"
    if s in ("PARSING", "SCANNING", "RUNNING"):
        return "warn"
    if s in ("FAILED", "ERROR"):
        return "err"
    return "idle"


def format_bytes(n: float) -> str:
    if n < 1:
        return f"{n*1024:.0f} MB"
    return f"{n:.1f} GB"


def parse_mermaid_from_ai(text: str) -> Optional[str]:
    """Извлекает блок mermaid из ответа ИИ если есть"""
    m = re.search(r"```mermaid\s*(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else None


def parse_table_from_ai(text: str) -> Optional[list[dict]]:
    """Извлекает JSON-таблицу из ответа ИИ если есть (ожидаем список словарей)"""
    m = re.search(r"```json\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


# ─────────────────────────────────────────
# СТРАНИЦА
# ─────────────────────────────────────────
@ui.page("/")
async def main_page():
    global log_element

    ui.add_head_html(CUSTOM_CSS)
    ui.query("body").style("background:#08090b;color:#fff;")

    # ── ХЕДЕР ──────────────────────────────
    with ui.element("header").classes("les-header w-full").style("position:sticky;top:0;z-index:999;"):
        with ui.row().classes("items-center gap-3"):
            _html('<span class="les-brand">[O_O] С.О.В.У.Ш.К.А.</span>')
            ui.label("v4.0 · NiceGUI").style("font-size:.65rem;color:var(--dim);font-weight:700;")

        with ui.row().classes("items-center gap-2"):
            mode_btn = ui.button(
                "РАГ",
                on_click=lambda: asyncio.create_task(toggle_mode(mode_btn))
            ).classes("mode-rag")
            mode_btn.props("no-caps flat")

            ui.button("↻", on_click=lambda: asyncio.create_task(full_refresh())).props("flat").style("color:var(--dim);")
            _th = {"dark": True}
            def _toggle_theme():
                _th["dark"] = not _th["dark"]
                d = _th["dark"]
                if d:
                    vs=["#08090b","#12151a","#1a1e25","#ffffff","#94a3b8","#2d3748","#3b82f6","#10b981","#ef4444","#f59e0b"]
                else:
                    vs=["#f0f2f5","#ffffff","#e8ecf0","#0d1117","#444d56","#c8d0d8","#0969da","#1a7f37","#cf222e","#9a6700"]
                ks=["--bg","--bg-panel","--bg-mod","--text","--dim","--border","--accent","--ok","--err","--warn"]
                js=";".join(f"document.documentElement.style.setProperty('{k}','{v}')" for k,v in zip(ks,vs))
                js+=f";document.body.style.background='{vs[0]}';document.body.style.color='{vs[3]}';"
                ui.run_javascript(js)
                theme_btn.set_text("☀" if d else "🌙")
            theme_btn = ui.button("🌙", on_click=_toggle_theme).props("flat").style("color:var(--dim);font-size:.85rem;")
            ui.button("⚙", on_click=lambda: settings_dialog.open()).props("flat").style("color:var(--dim);")

    # ── ВКЛАДКИ ────────────────────────────
    with ui.tabs().classes("w-full bg-transparent").style(
        "border-bottom:1px solid var(--border);font-family:var(--font);font-size:.75rem;font-weight:700;"
    ) as tabs:
        tab_overview = ui.tab("ОБЗОР")
        tab_samovar  = ui.tab("С.А.М.О.В.А.Р.")
        tab_prorab   = ui.tab("П.Р.О.Р.А.Б.")
        tab_chat     = ui.tab("AI ЧАТ")
        tab_mermaid  = ui.tab("ГРАФ / ДИАГРАММЫ")
        tab_diag     = ui.tab("🔬 ДИАГНОСТИКА")

    with ui.tab_panels(tabs, value=tab_overview).classes("w-full flex-1 overflow-auto").style(
        "background:var(--bg);min-height:0;"
    ):

        # ══════════════════════════════════════
        # ВКЛАДКА: ОБЗОР
        # ══════════════════════════════════════
        with ui.tab_panel(tab_overview):
            with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
                ui.label("Л.Е.С. // АРХИТЕКТУРА").style(
                    "font-size:1rem;font-weight:900;letter-spacing:1px;color:var(--text);"
                )

                # Модули системы
                modules = [
                    ("С.О.В.У.Ш.К.А.", "CORE UI",   "Интерфейс чата и управления", "ok",   tab_chat),
                    ("П.Р.О.Р.А.Б.",   "METRICS",   "Телеметрия узла",              "ok",   tab_prorab),
                    ("С.А.М.О.В.А.Р.", "RAG",       "Векторная база Qdrant",        "ok",   tab_samovar),
                    ("Т.О.С.К.А.",     "CRAG",      "Валидация ответов LLM",        "ok",   None),
                    ("В.О.Л.К.",       "AUTH",      "RBAC, аутентификация",         "idle", None),
                    ("К.О.Т.",         "TERM",      "Семантический фильтр",         "ok",   None),
                    ("С.У.Х.А.Р.И.К.","BACKUP",    "Снапшоты Qdrant",              "idle", None),
                    ("Е.Ж.И.К.",       "MAIL",      "Обработка почты IMAP",         "warn", None),
                ]

                with ui.grid(columns=4).classes("w-full gap-3"):
                    for name, tag, desc, status, target_tab in modules:
                        with ui.card().classes("card-les cursor-pointer").style(
                            "border-left:3px solid var(--accent);" if tag == "CORE UI" else ""
                        ) as card:
                            if target_tab:
                                card.on("click", lambda t=target_tab: tabs.set_value(t))

                            with ui.row().classes("items-center justify-between mb-2"):
                                ui.label(name).style("font-weight:900;font-size:.9rem;")
                                _html(f'<span class="tag-dim">{tag}</span>')

                            ui.label(desc).style("font-size:.7rem;color:var(--dim);margin-bottom:8px;")

                            with ui.row().classes("items-center gap-2"):
                                _html(dot_html(status))
                                color_map = {"ok": "var(--ok)", "warn": "var(--warn)", "idle": "var(--dim)"}
                                ui.label("LIVE" if status == "ok" else ("WAIT" if status == "warn" else "IDLE")).style(
                                    f"font-size:.6rem;font-weight:700;color:{color_map.get(status,'var(--dim)')};"
                                )

                # Стек
                with ui.card().classes("card-les w-full"):
                    ui.label("СТЕК").classes("section-title mb-3")
                    stack_items = [
                        ("Mac Mini M4 / 24 GB", "HOST"),
                        ("Docker: les-proxy :8050 · les-qdrant :6333", "DOCKER"),
                        ("MLX Host :8080 · Qwen3-14B + Qwen3-4B + bge-m3", "MLX"),
                        ("Ollama :11434 · qwen3:14b + bge-m3 (резерв)", "OLLAMA"),
                    ]
                    for text, tag in stack_items:
                        with ui.row().classes("items-center gap-3 py-1"):
                            _html(f'<span class="tag-acc">{tag}</span>')
                            ui.label(text).style("font-size:.75rem;color:var(--text);")

        # ══════════════════════════════════════
        # ВКЛАДКА: С.А.М.О.В.А.Р.
        # ══════════════════════════════════════
        with ui.tab_panel(tab_samovar):
            with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
                with ui.row().classes("items-center justify-between w-full"):
                    with ui.column().classes("gap-0"):
                        ui.label("С.А.М.О.В.А.Р. // ИНДЕКС ЗНАНИЙ").style(
                            "font-size:1rem;font-weight:900;letter-spacing:1px;"
                        )
                        ui.label("/api/rag/sources + /api/rag/datasets").style(
                            "font-size:.6rem;color:var(--dim);"
                        )
                    ui.button("↻ ОБНОВИТЬ", on_click=lambda: asyncio.create_task(refresh_and_render_samovar())).props(
                        "no-caps outline"
                    ).style("border-color:var(--accent);color:var(--accent);font-size:.7rem;")

                # KPI строка
                with ui.row().classes("w-full gap-3"):
                    sam_kpi = {}
                    for key, lbl, color in [
                        ("ds",     "Датасетов",      "var(--text)"),
                        ("src",    "Файлов в папках", "var(--text)"),
                        ("idx",    "В индексе",       "var(--ok)"),
                        ("pend",   "Ожидают",         "var(--warn)"),
                        ("chunks", "Чанков Qdrant",   "var(--text)"),
                    ]:
                        with ui.card().classes("kpi-box flex-1"):
                            v = ui.label("—").classes("kpi-val").style(f"color:{color};font-size:1.6rem;font-weight:900;")
                            ui.label(lbl).classes("kpi-lbl").style("font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;")
                            sam_kpi[key] = v

                # Дерево датасетов (ui.table)
                sam_tbl_cols = [
                    {"name":"folder",  "label":"Папка",   "field":"folder",  "align":"left",   "sortable":True},
                    {"name":"total",   "label":"Файлов",  "field":"total",   "align":"center", "sortable":True},
                    {"name":"indexed", "label":"В индексе","field":"indexed", "align":"center", "sortable":True},
                    {"name":"pending", "label":"Ожидают", "field":"pending", "align":"center", "sortable":True},
                    {"name":"chunks",  "label":"Чанков",  "field":"chunks",  "align":"center", "sortable":True},
                    {"name":"status",  "label":"Статус",  "field":"status",  "align":"left"},
                    {"name":"job_info","label":"Job",     "field":"job_info","align":"left"},
                    {"name":"actions", "label":"",        "field":"folder",  "align":"center"},
                ]
                sam_grid = ui.table(
                    columns=sam_tbl_cols, rows=[], row_key="folder"
                ).classes("w-full").style(
                    "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
                )
                sam_grid.add_slot("body-cell-indexed", """
                    <q-td :props="props">
                      <span :style="{color: props.value > 0 ? '#10b981' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
                    </q-td>""")
                sam_grid.add_slot("body-cell-pending", """
                    <q-td :props="props">
                      <span :style="{color: props.value > 0 ? '#f59e0b' : '#94a3b8', fontWeight:'700'}">{{ props.value }}</span>
                    </q-td>""")
                sam_grid.add_slot("body-cell-status", """
                    <q-td :props="props">
                      <span :style="{color: ['INDEXED','READY'].includes(props.value)?'#10b981':['PARSING','SCANNING'].includes(props.value)?'#f59e0b':'#94a3b8'}">
                        {{ props.value }}
                      </span>
                    </q-td>""")
                sam_grid.add_slot("body-cell-actions", """
                    <q-td :props="props" auto-width>
                      <q-btn flat dense size="xs" color="primary" icon="sync"
                             @click="$parent.$emit('sync', props.row)"
                             style="font-size:.6rem;padding:2px 6px;">SYNC</q-btn>
                    </q-td>""")
                sam_grid.on("sync", lambda e: asyncio.create_task(_sync_row(e.args)))

                async def _sync_row(row):
                    folder = row.get("folder","") if isinstance(row,dict) else str(row)
                    if not folder: return
                    add_log(f"[SYNC] Запуск: {folder}")
                    d = await api_post(f"/api/rag/sync/{folder}")
                    if d:
                        ui.notify(f"✓ SYNC {folder}: job {d.get('job_id','?')} +{d.get('new_files',0)} файлов", type="positive")
                        add_log(f"[SYNC] {folder} → job {d.get('job_id')} +{d.get('new_files',0)} новых")
                        await asyncio.sleep(2)
                        await refresh_and_render_samovar()
                    else:
                        ui.notify(f"Ошибка SYNC {folder}", type="negative")

                with ui.row().classes("gap-3 w-full"):
                    sync_folder_input = ui.input(
                        placeholder="Имя папки для синка..."
                    ).style(
                        "background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:var(--font);border-radius:4px;padding:6px 10px;font-size:.75rem;flex:1;"
                    ).classes("flex-1")

                    async def do_sync():
                        folder = sync_folder_input.value.strip()
                        if not folder:
                            ui.notify("Укажи имя папки", type="warning")
                            return
                        add_log(f"[SYNC] Запуск: {folder}")
                        d = await api_post(f"/api/rag/sync/{folder}")
                        if d:
                            ui.notify(f"SYNC запущен. Job: {d.get('job_id','?')} | +{d.get('new_files',0)} новых", type="positive")
                            add_log(f"[SYNC] {folder} → job {d.get('job_id')} +{d.get('new_files',0)} новых")
                            await asyncio.sleep(3)
                            await refresh_and_render_samovar()

                    ui.button("↻ SYNC", on_click=do_sync).props("no-caps outline").style(
                        "border-color:var(--accent);color:var(--accent);font-size:.7rem;"
                    )

                # History jobs — отдельная секция
                with ui.card().classes("card-les w-full"):
                    ui.label("ИСТОРИЯ JOBS").classes("section-title mb-3")
                    jobs_tbl_cols = [
                        {"name":"job_id",  "label":"Job",      "field":"job_id",  "align":"left"},
                        {"name":"dataset", "label":"Датасет",  "field":"dataset", "align":"left",   "sortable":True},
                        {"name":"status",  "label":"Статус",   "field":"status",  "align":"left",   "sortable":True},
                        {"name":"progress","label":"Файлов",   "field":"progress","align":"center"},
                        {"name":"started", "label":"Начало",   "field":"started", "align":"left",   "sortable":True},
                        {"name":"message", "label":"Сообщение","field":"message", "align":"left"},
                    ]
                    jobs_grid = ui.table(
                        columns=jobs_tbl_cols, rows=[], row_key="job_id"
                    ).classes("w-full").style(
                        "background:var(--bg-panel);color:var(--text);font-family:var(--font);"
                    )

                async def refresh_and_render_samovar():
                    await refresh_samovar()
                    _render_samovar()

                def _render_samovar():
                    sources   = state["sources"]
                    datasets  = state["datasets"]
                    jobs      = state["jobs"]
                    ds_map    = {d["id"]: d for d in datasets}

                    tot_src = tot_idx = tot_chunks = 0
                    rows = []
                    for src in sources:
                        total   = src.get("source_files", 0)
                        indexed = src.get("indexed_files", 0)
                        pending = max(0, total - indexed)
                        ds      = ds_map.get(src.get("dataset_id", "")) or {}
                        chunks  = ds.get("chunk_count", 0) or 0
                        status  = src.get("dataset_status", "NOT_CREATED")
                        tot_src    += total
                        tot_idx    += indexed
                        tot_chunks += chunks

                        # Найдём последний job
                        folder_jobs = [
                            j for j in jobs.values()
                            if j.get("dataset_name") == f"{src['folder']}_Index"
                        ]
                        last_job = None
                        if folder_jobs:
                            last_job = sorted(folder_jobs, key=lambda j: j.get("started_at",""), reverse=True)[0]

                        job_info = ""
                        if last_job:
                            job_info = f"{last_job['status']} {last_job.get('processed',0)}/{last_job.get('total',0)}"

                        rows.append({
                            "folder":   src.get("folder", ""),
                            "total":    total,
                            "indexed":  indexed,
                            "pending":  pending,
                            "chunks":   chunks,
                            "status":   status,
                            "job_info": job_info,
                        })

                    sam_kpi["ds"].set_text(str(len(sources)))
                    sam_kpi["src"].set_text(str(tot_src))
                    sam_kpi["idx"].set_text(str(tot_idx))
                    sam_kpi["pend"].set_text(str(max(0, tot_src - tot_idx)))
                    sam_kpi["chunks"].set_text(str(tot_chunks))
                    sam_grid.rows = rows
                    sam_grid.update()

                    # Jobs
                    job_rows = []
                    for jid, j in jobs.items():
                        dt_str = ""
                        if j.get("started_at"):
                            try:
                                dt = datetime.fromisoformat(j["started_at"].replace("Z",""))
                                dt_str = dt.strftime("%d.%m %H:%M")
                            except Exception:
                                dt_str = j["started_at"]
                        job_rows.append({
                            "job_id":   jid[:12],
                            "dataset":  j.get("dataset_name",""),
                            "status":   j.get("status",""),
                            "progress": f"{j.get('processed',0)}/{j.get('total',0)}",
                            "started":  dt_str,
                            "message":  j.get("message",""),
                        })
                    job_rows.sort(key=lambda r: r["started"], reverse=True)
                    jobs_grid.rows = job_rows
                    jobs_grid.update()

                # Загружаем при входе
                ui.timer(0.3, lambda: asyncio.create_task(refresh_and_render_samovar()), once=True)

        # ══════════════════════════════════════
        # ВКЛАДКА: П.Р.О.Р.А.Б.
        # ══════════════════════════════════════
        with ui.tab_panel(tab_prorab):
            with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-4"):
                with ui.row().classes("items-center justify-between w-full"):
                    ui.label("П.Р.О.Р.А.Б. // ДИАГНОСТИКА").style(
                        "font-size:1rem;font-weight:900;letter-spacing:1px;"
                    )
                    ui.label("/api/metrics · /api/status · MLX :8080  [5–15s]").style(
                        "font-size:.6rem;color:var(--dim);"
                    )

                # KPI строка
                with ui.row().classes("w-full gap-3"):
                    pro_kpi = {}
                    for key, lbl, color in [
                        ("files",  "Файлов",    "var(--text)"),
                        ("chunks", "Чанков",    "var(--text)"),
                        ("ram",    "RAM",        "var(--text)"),
                        ("cpu",    "CPU",        "var(--text)"),
                        ("queue",  "LLM Queue",  "var(--ok)"),
                    ]:
                        with ui.card().classes("kpi-box flex-1"):
                            v = ui.label("—").style(f"font-size:1.6rem;font-weight:900;color:{color};")
                            ui.label(lbl).style("font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;")
                            pro_kpi[key] = v

                # Метрики карточки
                with ui.grid(columns=3).classes("w-full gap-3"):

                    # RAM
                    with ui.card().classes("card-les"):
                        ui.label("RAM BREAKDOWN").classes("section-title mb-2")
                        ram_bar = _html(pct_bar_html([(33,"var(--err)"),(33,"var(--ok)"),(34,"var(--border)")]))
                        with ui.row().classes("justify-between mt-1"):
                            ui.label("Ollama").style("font-size:.6rem;color:var(--err);")
                            ui.label("Sys").style("font-size:.6rem;color:var(--ok);")
                            ui.label("Free").style("font-size:.6rem;color:var(--dim);")
                        ram_total_lbl = ui.label("— / — GB").style("font-size:.7rem;color:var(--dim);margin-top:4px;")

                    # Диск
                    with ui.card().classes("card-les"):
                        ui.label("ДИСК").classes("section-title mb-2")
                        disk_bar = _html(pct_bar_html([(20,"var(--accent)"),(80,"var(--border)")]))
                        disk_lbl = ui.label("— GB").style("font-size:.7rem;color:var(--dim);margin-top:4px;")

                    # Т.О.С.К.А. v2
                    with ui.card().classes("card-les"):
                        ui.label("Т.О.С.К.А. v2").classes("section-title mb-2")
                        crag_bar  = _html(pct_bar_html([(34,"var(--ok)"),(33,"var(--warn)"),(33,"var(--err)")]))
                        with ui.row().classes("justify-between mt-1"):
                            crag_v = ui.label("—% VERIF").style("font-size:.6rem;color:var(--ok);font-weight:700;")
                            crag_n = ui.label("—% N/D").style("font-size:.6rem;color:var(--warn);font-weight:700;")
                            crag_h = ui.label("—% HALL.").style("font-size:.6rem;color:var(--err);font-weight:700;")

                    # Latency
                    with ui.card().classes("card-les"):
                        ui.label("LATENCY").classes("section-title mb-2")
                        lat_lbl  = ui.label("— ms avg").style("font-size:1.2rem;font-weight:900;")
                        lat_info = ui.label("Search + Gen").style("font-size:.6rem;color:var(--dim);")

                    # MLX Host
                    with ui.card().classes("card-les col-span-2"):
                        with ui.row().classes("items-center justify-between mb-2"):
                            ui.label("MLX HOST :8080").classes("section-title")
                            mlx_badge = _html('<span class="tag-dim">—</span>')

                        mlx_models_container = ui.column().classes("gap-2 w-full")

                    # Ollama / Docker
                    with ui.card().classes("card-les"):
                        ui.label("OLLAMA — МОДЕЛИ").classes("section-title mb-2")
                        ollama_container = ui.column().classes("gap-1 w-full")

                    with ui.card().classes("card-les"):
                        ui.label("DOCKER КОНТЕЙНЕРЫ").classes("section-title mb-2")
                        docker_badge = ui.label("—").style("font-size:.7rem;font-weight:700;")
                        docker_container = ui.column().classes("gap-1 w-full")

                    # Errors
                    with ui.card().classes("card-les"):
                        ui.label("HTTP ERRORS").classes("section-title mb-2")
                        errors_lbl = ui.label("Нет ошибок").style("font-size:.7rem;color:var(--dim);")

                def _render_prorab():
                    m   = state["metrics"]
                    st  = state["status"]
                    mlx = state["mlx_health"]
                    s   = m.get("system", {})
                    p   = m.get("pipeline", {})
                    r   = m.get("rag", {})
                    q   = m.get("queue", {})
                    e   = m.get("errors", {})

                    # KPI
                    pro_kpi["files"].set_text(str(r.get("files", r.get("documents", 0))))
                    pro_kpi["chunks"].set_text(str(r.get("chunks", 0)))
                    pro_kpi["ram"].set_text(format_bytes(s.get("ram_used", 0)))
                    pro_kpi["cpu"].set_text(f"{s.get('cpu',0):.1f}%")
                    pro_kpi["queue"].set_text(str(q.get("llm_waiting", 0)))

                    # RAM bar
                    rt = s.get("ram_total", 24)
                    ru = s.get("ram_used", 0)
                    ro = s.get("ollama_ram", 0)
                    rs = max(0, ru - ro)
                    rf = max(0, rt - ru)
                    ram_bar.set_content(pct_bar_html([
                        (ro/rt*100, "var(--err)"),
                        (rs/rt*100, "var(--ok)"),
                        (rf/rt*100, "var(--border)"),
                    ]))
                    ram_total_lbl.set_text(f"{ru:.1f} / {rt:.1f} GB")

                    # Disk
                    du = s.get("disk_used", 0)
                    dt_ = s.get("disk_total", 512) or 512
                    dp = du / dt_ * 100
                    disk_bar.set_content(pct_bar_html([
                        (dp, "var(--accent)"),
                        (100-dp, "var(--border)"),
                    ]))
                    disk_lbl.set_text(f"{du:.0f} / {dt_:.0f} GB")

                    # CRAG v2
                    cv = p.get("crag_verified_rate", p.get("crag_pass_rate", 0))
                    cn = p.get("crag_nodata_rate", 0)
                    ch = p.get("crag_halluc_rate", max(0, 1 - cv - cn))
                    crag_bar.set_content(pct_bar_html([
                        (cv*100, "var(--ok)"),
                        (cn*100, "var(--warn)"),
                        (ch*100, "var(--err)"),
                    ]))
                    crag_v.set_text(f"{cv*100:.0f}% VERIF")
                    crag_n.set_text(f"{cn*100:.0f}% N/D")
                    crag_h.set_text(f"{ch*100:.0f}% HALL.")

                    # Latency
                    ls = p.get("latency_search", [])
                    lg = p.get("latency_gen", [])
                    if ls or lg:
                        combined = [(ls[i] if i < len(ls) else 0) + (lg[i] if i < len(lg) else 0)
                                    for i in range(max(len(ls), len(lg)))]
                        avg = sum(combined) / len(combined) if combined else 0
                        lat_lbl.set_text(f"{avg*1000:.0f} ms avg")

                    # MLX Host
                    if mlx:
                        mlx_badge.set_content('<span class="tag-ok">UP</span>')
                        engines = []
                        def _n(v): return v.get("path",str(v)) if isinstance(v,dict) else str(v or "")
                        def _l(v,d=True): return v.get("loaded",d) if isinstance(v,dict) else d
                        if mlx.get("main_model") or mlx.get("model"):
                            engines.append(("MAIN", _n(mlx.get("main_model") or mlx.get("model")),
                                            _l(mlx.get("main_model") or mlx.get("model"), True), "var(--accent)"))
                        if mlx.get("val_model"):
                            engines.append(("VAL", _n(mlx["val_model"]),
                                            _l(mlx["val_model"], False), "var(--pauk)"))
                        if mlx.get("embed_model") or mlx.get("embedding_model"):
                            engines.append(("EMBED", _n(mlx.get("embed_model") or mlx.get("embedding_model")) or "bge-m3",
                                            True, "var(--ok)"))
                        mlx_models_container.clear()
                        for label, name, loaded, color in engines:
                            with mlx_models_container:
                                with ui.row().classes("items-center justify-between w-full py-1").style(
                                    "border-bottom:1px solid var(--border);"
                                ):
                                    with ui.column().classes("gap-0"):
                                        ui.label(name or "—").style(
                                            f"font-size:.72rem;font-weight:700;color:var(--text);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                                        )
                                        _html(f'<span class="tag-dim" style="color:{color};">{label}</span>')
                                    _html(
                                        f'<span class="{"tag-ok" if loaded else "tag-dim"}">{"LIVE" if loaded else "IDLE"}</span>'
                                    )
                    else:
                        mlx_badge.set_content('<span class="tag-err">DOWN</span>')
                        mlx_models_container.clear()
                        with mlx_models_container:
                            ui.label("MLX Host недоступен").style("font-size:.7rem;color:var(--err);")

                    # Ollama
                    ollama_container.clear()
                    models = st.get("ollama", {}).get("models", [])
                    if not models:
                        with ollama_container:
                            ui.label("Нет активных моделей").style("font-size:.7rem;color:var(--dim);")
                    else:
                        for mod in models:
                            with ollama_container:
                                with ui.row().classes("items-center justify-between py-1").style(
                                    "border-bottom:1px solid var(--border);"
                                ):
                                    with ui.column().classes("gap-0"):
                                        ui.label(mod["name"]).style("font-size:.72rem;font-weight:700;")
                                        ui.label(f"RAM: {mod.get('size_gb','?')} GB").style(
                                            "font-size:.6rem;color:var(--dim);"
                                        )
                                    _html('<span class="tag-ok">LIVE</span>')

                    # Docker
                    containers = st.get("containers", [])
                    all_ok = all(c.get("ok") for c in containers) if containers else False
                    docker_badge.set_text(f"{len(containers)} UP" if all_ok else "ПРОБЛЕМА")
                    docker_badge.style(f"color:{'var(--ok)' if all_ok else 'var(--err)'};")
                    docker_container.clear()
                    for c in containers:
                        with docker_container:
                            with ui.row().classes("items-center justify-between py-1").style(
                                "border-bottom:1px solid var(--border);"
                            ):
                                ui.label(c["name"]).style("font-size:.72rem;font-weight:700;")
                                _html(
                                    f'<span class="{"tag-ok" if c.get("ok") else "tag-err"}">'
                                    f'{c.get("status","?").split()[0]}</span>'
                                )

                    # Errors
                    if e:
                        errors_lbl.set_text(" | ".join(f"{k}: {v}" for k, v in e.items()))
                        errors_lbl.style("color:var(--err);")
                    else:
                        errors_lbl.set_text("Нет ошибок")
                        errors_lbl.style("color:var(--dim);")

                # Таймер обновления П.Р.О.Р.А.Б.
                ui.timer(5, lambda: _render_prorab())
                ui.timer(0.3, lambda: _render_prorab(), once=True)

        # ══════════════════════════════════════

        # ══════════════════════════════════════
        # ВКЛАДКА: AI ЧАТ
        # ══════════════════════════════════════
        with ui.tab_panel(tab_chat):
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
                                clear_btn = ui.button(
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

                                # Кнопки-переключатели форматов
                                OUTPUT_FORMATS = {
                                    "text":      ("📝", "Текст",       "Свободный текст, абзацы"),
                                    "spec":      ("📋", "Спецификация","Таблица изделий: поз./марка/кол-во"),
                                    "schema":    ("🗂", "Схема",       "Иерархия/классификатор в виде дерева"),
                                    "structure": ("🏗", "Структура",   "JSON-объект с вложенностью"),
                                    "table":     ("📊", "Таблица",     "Произвольная таблица (AG Grid)"),
                                    "mermaid":   ("🔀", "Диаграмма",   "Mermaid: flowchart/sequence/ER"),
                                    "svg":       ("🖼", "SVG",         "Векторная схема/план"),
                                    "template":  ("📎", "По образцу",  "Структура из загруженного файла"),
                                }

                                out_mode_val = {"v": "text"}  # mutable ref

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
                                    # Показываем/скрываем секции
                                    mermaid_opts_row.set_visibility(key == "mermaid")
                                    svg_opts_row.set_visibility(key == "svg")
                                    spec_opts_row.set_visibility(key == "spec")
                                    schema_opts_row.set_visibility(key == "schema")
                                    template_row.set_visibility(key == "template")
                                    _update_prompt_preview()

                                for key in OUTPUT_FORMATS:
                                    format_btns[key].on("click", lambda k=key: select_format(k))

                                # Выбираем текст по умолчанию
                                # (вызывается после рендера)

                            # ── 2. ПАРАМЕТРЫ ФОРМАТОВ (контекстные) ──
                            with ui.card().classes("card-les w-full"):
                                _html('<div class="section-title" style="margin-bottom:8px;">② ПАРАМЕТРЫ</div>')

                                # Параметры Mermaid
                                mermaid_opts_row = ui.column().classes("w-full gap-2")
                                with mermaid_opts_row:
                                    mermaid_type = ui.select(
                                        ["flowchart TD", "flowchart LR", "sequenceDiagram",
                                         "erDiagram", "gantt", "classDiagram", "mindmap"],
                                        value="flowchart TD",
                                        label="Тип диаграммы"
                                    ).style("font-size:.72rem;width:100%;")
                                mermaid_opts_row.set_visibility(False)

                                # Параметры SVG
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

                                # Параметры Спецификации
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

                                # Параметры Схемы (дерево)
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

                                # Загрузка образца
                                template_row = ui.column().classes("w-full gap-2")
                                with template_row:
                                    ui.label("Загрузи файл-образец (JSON, CSV, XLSX — первые 3 строки как шаблон)").style(
                                        "font-size:.65rem;color:var(--dim);"
                                    )
                                    template_upload = ui.upload(
                                        auto_upload=True,
                                        on_upload=lambda e: asyncio.create_task(load_output_template(e))
                                    ).props("flat accept=.json,.csv,.xlsx").classes("w-full")
                                    template_lbl = ui.label("").style("font-size:.65rem;color:var(--ok);")

                                    # Превью загруженного шаблона
                                    template_preview = _html("").style(
                                        "font-size:.65rem;color:var(--dim);max-height:80px;overflow:auto;"
                                        "background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px;"
                                        "white-space:pre;font-family:var(--font);"
                                    )
                                template_row.set_visibility(False)

                                # Общий переключатель: хочу ли я вывод на отдельной панели
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

                                detail_extra = ui.textarea(
                                    label="Дополнительные требования"
                                ).props("rows=2").style(
                                    "font-size:.72rem;width:100%;background:var(--bg);"
                                    "border:1px solid var(--border);color:var(--text);border-radius:4px;"
                                )

                                # Обновляем список датасетов
                                async def _load_datasets_select():
                                    await refresh_samovar()
                                    names = [s.get("folder","") for s in state["sources"]]
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

            # ── ПАНЕЛЬ РЕЗУЛЬТАТА (под сплиттером) ──────
            result_panel = ui.column().classes("w-full")

        # ─────────────────────────────────────────
        # ЛОГИКА AI ЧАТ
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
                    import tempfile, openpyxl
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
                # Показываем превью первой строки
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
            """Собирает системный промпт из формы."""
            mode = out_mode_val["v"]
            depth_map = {
                "Кратко (1-2 абзаца)":              "Ответь кратко — 1-2 абзаца.",
                "Стандарт (3-5 абзацев)":           "Ответь развёрнуто — 3-5 абзацев.",
                "Подробно (развёрнутый ответ)":     "Дай полный развёрнутый ответ со всеми деталями.",
                "Максимум (полный анализ)":         "Проведи максимально подробный анализ. Не сокращай.",
            }
            style_map = {
                "Русский (технический)":        "Пиши профессиональным техническим языком.",
                "Русский (нормативный ГОСТ)":   "Пиши в нормативном стиле ГОСТ: чёткие формулировки, без лирики.",
                "Краткие тезисы":               "Отвечай тезисами — каждый пункт одна мысль.",
                "Для презентации":              "Формат для слайдов: заголовок + маркированный список.",
            }

            parts = []
            depth_inst = depth_map.get(detail_depth.value, "")
            style_inst = style_map.get(detail_lang.value, "")
            if depth_inst:
                parts.append(depth_inst)
            if style_inst:
                parts.append(style_inst)

            if mode == "text":
                pass  # без доп. инструкций

            elif mode == "spec":
                gost_str = " строго по форме ГОСТ 21.110-2013" if spec_gost.value else ""
                group_str = " Группируй по разделам." if spec_group.value else ""
                type_str = spec_type.value
                parts.append(
                    f"\n\nВЫВЕДИ ОТВЕТ В ФОРМАТЕ СПЕЦИФИКАЦИИ{gost_str}.\n"
                    f"Тип: {type_str}.{group_str}\n"
                    f"Верни JSON-массив объектов. Обязательные поля для оборудования: "
                    f"поз (позиция), обозначение, наименование, тип_марка, ед_изм, кол_во, масса_ед, примечание.\n"
                    f"Для ведомостей: обозначение, наименование, примечание.\n"
                    f"Оберни в ```json ... ```"
                )

            elif mode == "schema":
                depth = int(schema_depth.value) if schema_depth.value else 3
                fmt = schema_format.value
                if fmt == "JSON дерево":
                    parts.append(
                        f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ ИЕРАРХИЧЕСКОЙ СХЕМЫ (JSON дерево, глубина {depth}).\n"
                        f"Структура узла: {{\"name\": str, \"children\": [...], \"desc\": str (опц)}}.\n"
                        f"Оберни в ```json ... ```"
                    )
                elif fmt == "YAML":
                    parts.append(
                        f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ YAML-ДЕРЕВА (глубина {depth}).\n"
                        f"Оберни в ```yaml ... ```"
                    )
                else:
                    parts.append(
                        f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ {fmt.upper()} (глубина {depth} уровней)."
                    )

            elif mode == "structure":
                parts.append(
                    "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ СТРУКТУРИРОВАННОГО JSON-ОБЪЕКТА.\n"
                    "Используй вложенные объекты и массивы. Оберни в ```json ... ```"
                )

            elif mode == "table":
                parts.append(
                    "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ ТАБЛИЦЫ — JSON-массив объектов.\n"
                    "Оберни в ```json ... ```"
                )

            elif mode == "mermaid":
                mtype = mermaid_type.value if hasattr(mermaid_type, 'value') else "flowchart TD"
                parts.append(
                    f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ MERMAID-ДИАГРАММЫ типа {mtype}.\n"
                    f"Оберни в ```mermaid ... ```\n"
                    f"Пиши на русском языке. Используй короткие метки узлов."
                )

            elif mode == "svg":
                stype = svg_type.value
                ssize = svg_size.value
                w, h = ssize.split("×") if "×" in ssize else ("800","600")
                parts.append(
                    f"\n\nВЫВЕДИ ОТВЕТ В ВИДЕ SVG-СХЕМЫ ({stype}).\n"
                    f"Размер viewBox: 0 0 {w} {h}. Тёмный фон #1a1e25, белый текст #ffffff, "
                    f"акцент синий #3b82f6, зелёный #10b981, красный #ef4444.\n"
                    f"Используй rect, circle, line, path, text, foreignObject для меток.\n"
                    f"Оберни в ```svg ... ```"
                )

            elif mode == "template":
                tmpl = state.get("output_template")
                if tmpl:
                    sample = tmpl[:3]
                    parts.append(
                        f"\n\nОТВЕЧАЙ СТРОГО ПО СТРУКТУРЕ ОБРАЗЦА (JSON-массив).\n"
                        f"Образец (первые строки):\n```json\n{json.dumps(sample, ensure_ascii=False, indent=2)}\n```\n"
                        f"Сохраняй все поля. Оберни ответ в ```json ... ```"
                    )
                else:
                    parts.append("\n\nОТВЕЧАЙ В ВИДЕ JSON-МАССИВА ОБЪЕКТОВ. Оберни в ```json ... ```")

            # Дополнительные требования
            if detail_extra.value.strip():
                parts.append(f"\n\nДОПОЛНИТЕЛЬНО: {detail_extra.value.strip()}")

            return " ".join(p for p in parts[:2]) + "".join(parts[2:])

        def _update_prompt_preview():
            q = chat_input.value.strip() or "[текст запроса]"
            extra = _build_extra_prompt(q)
            preview_text = (q + extra)[:800] + ("…" if len(q + extra) > 800 else "")
            prompt_preview.set_content(
                f'<pre style="margin:0;font-size:.63rem;color:var(--dim);white-space:pre-wrap;">'
                f'{preview_text}</pre>'
            )

        # Обновляем превью при изменении инпута
        chat_input.on("input", lambda: _update_prompt_preview())

        def _clear_chat():
            chat_column.clear()
            with chat_column:
                _html('<div class="chat-msg-sys">Чат очищен.</div>')
            result_panel.clear()
            state["chat_history"].clear()
            add_log("[ЧАТ] История очищена")

        async def _do_send(question: str):
            """Общая логика отправки запроса и отрисовки результата."""
            send_btn.props("disabled")
            apply_btn.props("disabled")
            out_mode = out_mode_val["v"]

            # Пузырь пользователя
            with chat_column:
                safe_q = question.replace("<", "&lt;").replace(">", "&gt;")
                _html(f'<div class="chat-msg-user">{safe_q}</div>')
            chat_scroll.scroll_to(percent=1)
            add_log(f'[AI] Запрос: "{question[:60]}"')

            # Плейсхолдер ИИ
            with chat_column:
                ai_placeholder = _html('<div class="chat-msg-ai typing">Обрабатываю...</div>')
            chat_scroll.scroll_to(percent=1)

            extra_prompt = _build_extra_prompt(question)
            full_q = question + extra_prompt

            # Фильтр по датасету
            ds_filter = None
            if detail_dataset.value and detail_dataset.value != "(все датасеты)":
                ds_filter = detail_dataset.value

            payload = {"question": full_q}
            if ds_filter:
                payload["dataset_filter"] = ds_filter

            try:
                d = await api_post("/api/chat", payload)
                if d:
                    ans  = d.get("answer", d.get("response", "Нет ответа"))
                    srcs = d.get("sources", [])
                    crag = d.get("crag_status", "")

                    state["chat_history"].append({"role": "user", "text": question})
                    state["chat_history"].append({"role": "ai", "text": ans, "srcs": srcs, "crag": crag})

                    # Теги источников
                    srcs_html = ""
                    if srcs:
                        tags = "".join(
                            f'<span class="src-tag">{s.get("file", s) if isinstance(s, dict) else s}</span>'
                            for s in srcs
                        )
                        srcs_html = f'<div class="msg-srcs" style="margin-top:8px;">{tags}</div>'
                    if crag:
                        cls = "src-tag" if crag == "VERIFIED" else "src-tag src-tag-err"
                        srcs_html += f'<span class="{cls}" style="margin-left:4px;">Т.О.С.К.А.: {crag}</span>'

                    # Краткий ответ в пузыре
                    short_ans = ans if len(ans) < 600 else ans[:600] + "…"
                    ai_placeholder.set_content(
                        f'<div class="chat-msg-ai">{short_ans.replace(chr(10), "<br>")}{srcs_html}</div>'
                    )

                    # Детальный вывод на отдельной панели
                    if separate_output_sw.value:
                        result_panel.clear()
                        _render_result(ans, out_mode, result_panel)

                    add_log(f"[AI] Формат:{out_mode} CRAG:{crag or 'N/A'} src:{len(srcs)}")
                else:
                    ai_placeholder.set_content(
                        '<div class="chat-msg-ai" style="color:var(--err);">Ошибка запроса к бэкенду</div>'
                    )
            except Exception as ex:
                ai_placeholder.set_content(
                    f'<div class="chat-msg-ai" style="color:var(--err);">Ошибка: {ex}</div>'
                )
            finally:
                send_btn.props(remove="disabled")
                apply_btn.props(remove="disabled")
                chat_scroll.scroll_to(percent=1)

        async def send_chat():
            q = chat_input.value.strip()
            if not q:
                return
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

        def _render_result(ans: str, mode: str, container):
            """Рендерит результат в зависимости от формата."""
            with container:
                with ui.card().classes("card-les w-full"):

                    # ── ТЕКСТ ──
                    if mode == "text":
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html('<div class="section-title">РЕЗУЛЬТАТ // ТЕКСТ</div>')
                            ui.button("📋 Копировать", on_click=lambda: ui.clipboard.write(ans)).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                        ui.markdown(ans).style("font-size:.8rem;line-height:1.6;color:var(--text);")

                    # ── СПЕЦИФИКАЦИЯ ──
                    elif mode == "spec":
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html('<div class="section-title">РЕЗУЛЬТАТ // СПЕЦИФИКАЦИЯ</div>')
                        data = parse_table_from_ai(ans)
                        if data:
                            _render_spec_table(data, container=None, inline=True)
                        else:
                            ui.markdown(ans).style("font-size:.78rem;")

                    # ── СХЕМА ──
                    elif mode == "schema":
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html('<div class="section-title">РЕЗУЛЬТАТ // СХЕМА</div>')
                        # Пробуем JSON-дерево
                        data = _parse_json_from_ai(ans)
                        if data:
                            _render_tree(data, container=None)
                        else:
                            # Fallback — markdown
                            ui.markdown(ans).style("font-size:.78rem;")

                    # ── СТРУКТУРА / ТАБЛИЦА / ОБРАЗЕЦ ──
                    elif mode in ("structure", "table", "template"):
                        label_map = {"structure":"СТРУКТУРА", "table":"ТАБЛИЦА", "template":"ПО ОБРАЗЦУ"}
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html(f'<div class="section-title">РЕЗУЛЬТАТ // {label_map[mode]}</div>')
                        data = parse_table_from_ai(ans) or _parse_json_from_ai(ans)
                        if isinstance(data, list) and data:
                            keys = list(data[0].keys()) if isinstance(data[0], dict) else ["значение"]
                            cols = [{"headerName": k, "field": k, "flex": 1, "filter": True, "sortable": True, "resizable": True} for k in keys]
                            rows = data if isinstance(data[0], dict) else [{"значение": str(r)} for r in data]
                            grid = ui.aggrid({
                                "columnDefs": cols,
                                "rowData": rows,
                                "domLayout": "autoHeight",
                                "defaultColDef": {"resizable": True},
                                "pagination": True,
                                "paginationPageSize": 20,
                            }).classes("w-full")
                            grid.style(
                                "--ag-background-color:var(--bg-panel);"
                                "--ag-header-background-color:var(--bg-mod);"
                                "--ag-border-color:var(--border);"
                                "font-family:var(--font);font-size:.72rem;"
                            )
                            with ui.row().classes("gap-2 mt-2"):
                                ui.button("📋 JSON", on_click=lambda d=data: ui.clipboard.write(json.dumps(d, ensure_ascii=False, indent=2))).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                                ui.button("📋 CSV", on_click=lambda d=data: ui.clipboard.write(_to_csv(d))).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                        elif isinstance(data, dict):
                            ui.markdown(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```").style("font-size:.75rem;")
                        else:
                            ui.markdown(ans).style("font-size:.78rem;")

                    # ── MERMAID ──
                    elif mode == "mermaid":
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html('<div class="section-title">РЕЗУЛЬТАТ // ДИАГРАММА</div>')
                        mermaid_code = parse_mermaid_from_ai(ans)
                        if mermaid_code:
                            state["mermaid_last"] = mermaid_code
                            ui.mermaid(mermaid_code)
                            with ui.row().classes("gap-2 mt-2"):
                                ui.button("📋 Копировать код", on_click=lambda c=mermaid_code: ui.clipboard.write(c)).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                                ui.button("→ В редактор", on_click=lambda: tabs.set_value(tab_mermaid)).props("no-caps flat").style("font-size:.65rem;color:var(--pauk);")
                        else:
                            ui.markdown(ans).style("font-size:.78rem;")

                    # ── SVG ──
                    elif mode == "svg":
                        with ui.row().classes("items-center justify-between mb-2"):
                            _html('<div class="section-title">РЕЗУЛЬТАТ // SVG СХЕМА</div>')
                        svg_code = _parse_svg_from_ai(ans)
                        if svg_code:
                            _html(svg_code).style(
                                "width:100%;overflow:auto;background:var(--bg-mod);"
                                "border:1px solid var(--border);border-radius:4px;padding:8px;"
                            )
                            with ui.row().classes("gap-2 mt-2"):
                                ui.button("📋 Копировать SVG", on_click=lambda c=svg_code: ui.clipboard.write(c)).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                                ui.button("⬇ Скачать .svg", on_click=lambda c=svg_code: _download_svg(c)).props("no-caps flat").style("font-size:.65rem;color:var(--ok);")
                        else:
                            ui.markdown(ans).style("font-size:.78rem;")
                            ui.label("⚠ SVG-блок не найден в ответе. Попробуй уточнить запрос.").style(
                                "font-size:.7rem;color:var(--warn);"
                            )

        # ── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ РЕНДЕРА ──

        def _parse_json_from_ai(text: str):
            m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
            # Пробуем без тройных кавычек
            try:
                start = text.find("{") if "{" in text else text.find("[")
                if start >= 0:
                    end = text.rfind("}") if "{" in text else text.rfind("]")
                    return json.loads(text[start:end+1])
            except Exception:
                pass
            return None

        def _parse_svg_from_ai(text: str) -> Optional[str]:
            m = re.search(r"```svg\s*(.*?)```", text, re.DOTALL)
            if m:
                return m.group(1).strip()
            m2 = re.search(r"(<svg[\s\S]*?</svg>)", text, re.IGNORECASE)
            return m2.group(1).strip() if m2 else None

        def _to_csv(data: list[dict]) -> str:
            if not data:
                return ""
            keys = list(data[0].keys())
            lines = [",".join(keys)]
            for row in data:
                lines.append(",".join(f'"{str(row.get(k,""))}"' for k in keys))
            return "\n".join(lines)

        def _download_svg(svg_code: str):
            # NiceGUI: отдаём через JS download
            import base64
            b64 = base64.b64encode(svg_code.encode()).decode()
            ui.run_javascript(
                f'const a=document.createElement("a");'
                f'a.href="data:image/svg+xml;base64,{b64}";'
                f'a.download="sovushka_schema.svg";a.click();'
            )

        def _render_spec_table(data: list[dict], container, inline: bool = False):
            """Рендерит спецификацию в формате ГОСТ 21.110 с нумерацией."""
            if not data:
                return
            keys = list(data[0].keys())
            # Если есть поз — сортируем по ней
            if "поз" in keys:
                try:
                    data = sorted(data, key=lambda r: int(str(r.get("поз", 0)).split(".")[0]))
                except Exception:
                    pass

            cols = []
            COL_LABELS = {
                "поз": "Поз.", "обозначение": "Обозначение", "наименование": "Наименование",
                "тип_марка": "Тип/Марка", "ед_изм": "Ед.изм.", "кол_во": "Кол-во",
                "масса_ед": "Масса ед.", "примечание": "Примечание",
            }
            for k in keys:
                w = 60 if k in ("поз","ед_изм","кол_во","масса_ед") else 1
                flex = None if k in ("поз","ед_изм","кол_во","масса_ед") else 1
                col = {
                    "headerName": COL_LABELS.get(k, k),
                    "field": k,
                    "resizable": True,
                    "filter": True,
                    "sortable": True,
                }
                if flex:
                    col["flex"] = flex
                else:
                    col["width"] = w
                cols.append(col)

            grid = ui.aggrid({
                "columnDefs": cols,
                "rowData": data,
                "domLayout": "autoHeight",
                "defaultColDef": {"resizable": True},
                "pagination": True,
                "paginationPageSize": 25,
                "rowClassRules": {
                    # Заголовки разделов выделяем
                    "font-bold": "params.data.наименование && !params.data.поз",
                },
            }).classes("w-full")
            grid.style(
                "--ag-background-color:var(--bg-panel);"
                "--ag-header-background-color:var(--bg-mod);"
                "--ag-border-color:var(--border);"
                "font-family:var(--font);font-size:.72rem;"
            )
            with ui.row().classes("gap-2 mt-2"):
                ui.button("📋 JSON", on_click=lambda d=data: ui.clipboard.write(json.dumps(d, ensure_ascii=False, indent=2))).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                ui.button("📋 CSV", on_click=lambda d=data: ui.clipboard.write(_to_csv(d))).props("no-caps flat").style("font-size:.65rem;color:var(--accent);")
                ui.label(f"{len(data)} позиций").style("font-size:.65rem;color:var(--dim);align-self:center;")

        def _render_tree(data, container, level: int = 0):
            """Рекурсивно рендерит JSON-дерево."""
            if isinstance(data, dict):
                name = data.get("name", data.get("title", data.get("id", "—")))
                desc = data.get("desc", data.get("description", ""))
                children = data.get("children", data.get("items", []))
                indent = level * 16
                with ui.row().classes("items-start gap-1").style(f"margin-left:{indent}px;"):
                    _html(
                        f'<span style="color:var(--accent);font-weight:700;font-size:.75rem;">{"▶" if children else "•"}</span>'
                        f'<span style="font-size:.75rem;font-weight:{"700" if level==0 else "400"};color:var(--text);">{name}</span>'
                        + (f'<span style="font-size:.65rem;color:var(--dim);margin-left:4px;">{desc}</span>' if desc else "")
                    )
                for child in (children if isinstance(children, list) else []):
                    _render_tree(child, container, level + 1)
            elif isinstance(data, list):
                for item in data:
                    _render_tree(item, container, level)

        # Инициализация — выбираем формат "text" после рендера
        ui.timer(0.1, lambda: select_format("text"), once=True)
        # Обновляем список датасетов для select
        ui.timer(1.0, lambda: asyncio.create_task(_load_datasets_select()), once=True)

        # Enter для отправки
        chat_input.on(
            "keydown.enter.prevent",
            lambda e: asyncio.create_task(send_chat()) if not (e.args or {}).get("shiftKey") else None
        )

        # ВКЛАДКА: ГРАФ / ДИАГРАММЫ
        # ══════════════════════════════════════
        with ui.tab_panel(tab_mermaid):
            with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):
                ui.label("ГРАФ / ДИАГРАММЫ").style("font-size:1rem;font-weight:900;letter-spacing:1px;")
                ui.label("Mermaid-генератор: редактируй код вручную или получай из AI ЧАТ").style(
                    "font-size:.65rem;color:var(--dim);"
                )

                DEFAULT_MERMAID = """flowchart TD
    A([Запрос]) --> B{РАГ?}
    B -->|Да| C[Векторный поиск\nQdrant]
    B -->|Нет| D[LLM напрямую]
    C --> E[Контекст + промпт]
    E --> F[MLX Qwen3-14B]
    F --> G{Т.О.С.К.А.\nвалидация}
    G -->|VERIFIED| H([Ответ])
    G -->|NO_DATA| I([Нет данных])
    G -->|HALLUCINATION| J([Заблокировано])"""

                with ui.splitter(value=40).classes("w-full").style("height:500px;") as spl:
                    with spl.before:
                        with ui.column().classes("w-full h-full gap-2 p-2"):
                            ui.label("КОД ДИАГРАММЫ").classes("section-title")
                            mermaid_editor = ui.codemirror(
                                value=state.get("mermaid_last") or DEFAULT_MERMAID,
                                language="markdown",
                            ).classes("w-full flex-1").style(
                                "background:var(--bg-mod);border:1px solid var(--border);border-radius:4px;font-size:.75rem;min-height:400px;"
                            )

                            with ui.row().classes("gap-2"):
                                def render_mermaid():
                                    code = mermaid_editor.value
                                    state["mermaid_last"] = code
                                    mermaid_view.set_content(code)

                                ui.button("▶ Отрисовать", on_click=render_mermaid).props("no-caps outline").style(
                                    "font-size:.7rem;border-color:var(--ok);color:var(--ok);"
                                )

                                templates = {
                                    "Флоучарт Л.Е.С.": DEFAULT_MERMAID,
                                    "Последовательность RAG": """sequenceDiagram
    participant U as Пользователь
    participant P as les-proxy
    participant Q as Qdrant
    participant M as MLX Host
    participant T as Т.О.С.К.А.
    U->>P: Запрос
    P->>Q: Векторный поиск
    Q-->>P: Топ-5 чанков
    P->>M: Промпт + контекст
    M-->>P: Ответ LLM
    P->>T: Валидация
    T-->>P: VERIFIED
    P-->>U: Ответ""",
                                    "ER-диаграмма": """erDiagram
    DATASET {
        string id PK
        string name
        string status
        int chunk_count
    }
    SOURCE_FOLDER {
        string folder PK
        string dataset_id FK
        int source_files
        int indexed_files
    }
    JOB {
        string job_id PK
        string dataset_name FK
        string status
        int processed
        int total
    }
    DATASET ||--o{ SOURCE_FOLDER : "имеет"
    DATASET ||--o{ JOB : "запускает" """,
                                }
                                tmpl_select = ui.select(
                                    list(templates.keys()),
                                    label="Шаблон"
                                ).style("font-size:.7rem;flex:1;")

                                def load_template():
                                    key = tmpl_select.value
                                    if key and key in templates:
                                        mermaid_editor.set_value(templates[key])
                                        render_mermaid()

                                ui.button("Загрузить", on_click=load_template).props("no-caps flat").style(
                                    "font-size:.7rem;color:var(--accent);"
                                )

                    with spl.after:
                        with ui.card().classes("card-les w-full h-full mermaid-wrap").style("overflow:auto;"):
                            ui.label("ПРЕВЬЮ").classes("section-title mb-3")
                            mermaid_view = ui.mermaid(state.get("mermaid_last") or DEFAULT_MERMAID)

    # ── ТЕРМИНАЛ ЛОГОВ ──────────────────────
    ui.separator().style("border-color:var(--border);")
    with ui.element("footer").style(
        "background:#000;font-family:var(--font);font-size:.7rem;height:120px;overflow-y:auto;"
        "border-top:1px solid var(--border);flex-shrink:0;width:100%;padding:8px 18px;"
    ):
        log_element = ui.log(max_lines=100).classes("w-full h-full").style(
            "background:transparent;color:var(--ok);font-family:var(--font);font-size:.7rem;border:none;"
        )
        add_log("[С.О.В.У.Ш.К.А.] v4.0 NiceGUI Edition. Инициализация...")

    # ── ДИАЛОГ НАСТРОЕК ─────────────────────
    with ui.dialog() as settings_dialog, ui.card().style(
        "background:var(--bg-panel);border:1px solid var(--border);min-width:480px;padding:24px;"
    ):
        ui.label("⚙ НАСТРОЙКИ Л.Е.С.").style("font-size:.95rem;font-weight:900;margin-bottom:16px;")

        set_llm  = ui.input("LLM Модель",    value="").style(
            "background:var(--bg);color:var(--text);font-family:var(--font);width:100%;"
        )
        set_embed = ui.input("Embedding Модель", value="").style(
            "background:var(--bg);color:var(--text);font-family:var(--font);width:100%;"
        )
        set_url  = ui.input("Ollama / MLX URL",  value="").style(
            "background:var(--bg);color:var(--text);font-family:var(--font);width:100%;"
        )

        async def _load_settings():
            d = await api_get("/api/settings")
            if d:
                set_llm.set_value(d.get("llm_model",""))
                set_embed.set_value(d.get("embed_model",""))
                set_url.set_value(d.get("ollama_url",""))

        ui.timer(0.1, lambda: asyncio.create_task(_load_settings()), once=True)

        ui.separator().style("border-color:var(--border);margin:12px 0;")
        ui.label("⚠ Опасная зона").style("color:var(--err);font-size:.65rem;font-weight:900;text-transform:uppercase;")

        async def _reset_all():
            ok = await ui.run_javascript("confirm('Сбросить ВСЕ датасеты? Необратимо!')")
            if ok:
                d = await api_delete("/api/rag/datasets")
                ui.notify(f"Сброс: {d}", type="warning") if d else None
                await refresh_samovar()

        ui.button("☢ Сбросить ВСЕ датасеты", on_click=_reset_all).props("no-caps").style(
            "border:1px solid var(--err);color:var(--err);background:transparent;margin-top:8px;"
        )

        with ui.row().classes("justify-end gap-2 mt-4"):
            ui.button("Отмена", on_click=settings_dialog.close).props("no-caps flat").style("color:var(--dim);")

            async def save_settings():
                d = await api_post("/api/settings", {
                    "llm_model":   set_llm.value,
                    "embed_model": set_embed.value,
                    "ollama_url":  set_url.value,
                })
                add_log(f"[SETTINGS] Сохранено: LLM={set_llm.value}")
                ui.notify("Настройки сохранены, прокси перезапускается...", type="positive")
                settings_dialog.close()

            ui.button("💾 Сохранить", on_click=save_settings).props("no-caps").style(
                "border:1px solid var(--accent);color:var(--accent);background:transparent;"
            )


    # ── РЕЖИМ ───────────────────────────────
    async def toggle_mode(btn):
        next_mode = "code" if state["mode"] == "rag" else "rag"
        next_model = "mlx-community/Qwen3-14B-4bit"
        btn.set_text("...")
        add_log(f"[РЕЖИМ] Переключение → {next_mode.upper()}")
        try:
            await api_post("/api/mode", {"mode": next_mode, "model": next_model})
            try:
                await api_post("/api/switch_model", {"model": next_model, "mode": next_mode}, base=MLX_URL)
                add_log(f"[MLX] switch_model → {next_model}")
            except Exception as e:
                add_log(f"[MLX] switch_model недоступен: {e}")
            state["mode"] = next_mode
            if next_mode == "code":
                btn.set_text("КОД")
                btn.classes(remove="mode-rag", add="mode-code")
            else:
                btn.set_text("РАГ")
                btn.classes(remove="mode-code", add="mode-rag")
            add_log(f"[РЕЖИМ] {next_mode.upper()} активен.")
        except Exception as e:
            add_log(f"[РЕЖИМ] Ошибка: {e}")
            btn.set_text("РАГ" if state["mode"] == "rag" else "КОД")

    async def full_refresh():
        add_log("[REFRESH] Полное обновление...")
        await asyncio.gather(
            refresh_metrics(),
            refresh_status(),
            refresh_mlx(),
            refresh_samovar(),
        )
        add_log("[REFRESH] Готово.")


        # ══════════════════════════════════════
        # ВКЛАДКА: 🔬 ДИАГНОСТИКА
        # ══════════════════════════════════════
        with ui.tab_panel(tab_diag):
            with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-4"):

                # ── Заголовок и кнопка ──────────────────
                with ui.row().classes("items-center justify-between w-full"):
                    with ui.column().classes("gap-0"):
                        ui.label("🔬 ДИАГНОСТИКА СИСТЕМЫ").style(
                            "font-size:1rem;font-weight:900;letter-spacing:1px;"
                        )
                        diag_ts_lbl = ui.label("Последний прогон: —").style(
                            "font-size:.6rem;color:var(--dim);"
                        )
                    with ui.row().classes("gap-2"):
                        diag_run_btn = ui.button(
                            "▶ ЗАПУСТИТЬ ДИАГНОСТИКУ",
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

                # ── Визуализация — карточки чеков ────────
                diag_cards = ui.grid(columns=2).classes("w-full gap-3")

                # ── Mermaid-схема состояния ───────────────
                with ui.card().classes("card-les w-full"):
                    with ui.row().classes("items-center justify-between mb-2"):
                        _html('<div class="section-title">ТОПОЛОГИЯ // СТАТУС УЗЛОВ</div>')
                        ui.label("Обновляется после диагностики").style("font-size:.6rem;color:var(--dim);")
                    diag_mermaid = ui.mermaid(
                        "graph LR\n"
                        "  UI([С.О.В.У.Ш.К.А.\n:8051]) --> P[les-proxy\n:8050]\n"
                        "  P --> Q[(Qdrant\n:6333)]\n"
                        "  P --> M[MLX Host\n:8080]\n"
                        "  P --> O[Ollama\n:11434]\n"
                        "  M --> B[bge-m3\nEmbeddings]\n"
                        "  M --> L[Qwen3-14B\nLLM]\n"
                        "  M --> V[Qwen3-4B\nValidator]"
                    ).classes("w-full")

                # ── Лог диагностики ───────────────────────
                with ui.card().classes("card-les w-full"):
                    _html('<div class="section-title" style="margin-bottom:8px;">ЛОГ ПРОГОНА</div>')
                    diag_log_el = ui.log(max_lines=80).classes("w-full").style(
                        "background:var(--bg);color:var(--ok);font-family:var(--font);"
                        "font-size:.68rem;height:160px;border:none;"
                    )

        # ── Вспомогательные функции диагностики ──────────

        def _diag_kpi_box(val: str, lbl: str, color: str):
            with ui.card().classes("kpi-box flex-1"):
                v = ui.label(val).style(f"font-size:1.6rem;font-weight:900;color:{color};")
                ui.label(lbl).style("font-size:.62rem;text-transform:uppercase;color:var(--dim);margin-top:4px;")
            return v

        STATUS_ICON  = {"ok": "✓", "warn": "⚠", "err": "✗"}
        STATUS_COLOR = {"ok": "var(--ok)", "warn": "var(--warn)", "err": "var(--err)"}
        STATUS_TAG   = {"ok": "tag-ok", "warn": "tag-warn", "err": "tag-err"}

        def _render_diag_cards():
            results = state["diag_results"]
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

        def _build_diag_mermaid(results: list) -> str:
            """Строит Mermaid-диаграмму с цветами по статусу каждого узла."""
            # Маппинг name → node_id для mermaid
            node_map = {
                "Qdrant :6333":          ("QD", "Qdrant\n:6333"),
                "Qdrant индекс":         ("QI", "Qdrant\nindex"),
                "MLX Host :8080":        ("ML", "MLX Host\n:8080"),
                "Ollama :11434":         ("OL", "Ollama\n:11434"),
                "RAM":                   ("RAM", "RAM"),
                "CPU":                   ("CPU", "CPU"),
                "Диск":                  ("DSK", "Диск"),
                "Docker":                ("DK", "Docker"),
                "Chat latency (тест)":   ("CH", "Chat\nlatency"),
                "Сеть (интернет)":       ("NET", "Интернет"),
            }
            status_style = {"ok": "fill:#10b981,color:#fff", "warn": "fill:#f59e0b,color:#000", "err": "fill:#ef4444,color:#fff"}

            result_map = {r["name"]: r["status"] for r in results}

            lines = ["graph LR"]
            styles = []
            idx = 0

            # Базовые узлы
            lines.append('  UI([С.О.В.У.Ш.К.А.\n:8051])')
            lines.append('  P[les-proxy\n:8050]')
            lines.append('  UI --> P')

            for name, (nid, label) in node_map.items():
                st = result_map.get(name, "idle")
                shape_open, shape_close = "[", "]"
                if nid in ("QD", "QI"):
                    shape_open, shape_close = "[(", ")]"
                elif nid in ("RAM", "CPU", "DSK"):
                    shape_open, shape_close = "{{", "}}"
                elif nid == "NET":
                    shape_open, shape_close = "([", "])"
                lines.append(f'  {nid}{shape_open}"{label}"{shape_close}')
                if st in status_style:
                    styles.append(f'  style {nid} {status_style[st]}')
                idx += 1

            # Связи
            lines += [
                "  P --> QD", "  QD --> QI",
                "  P --> ML", "  ML --> OL",
                "  P --> CH",
                "  P --> RAM", "  P --> CPU", "  P --> DSK",
                "  UI --> NET",
                "  DK --> P", "  DK --> QD",
            ]
            lines += styles
            return "\n".join(lines)

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
                    # Fallback: делаем локальную диагностику если прокси не поддерживает
                    diag_log_el.push("> [WARN] /api/diag не найден — запуск встроенной диагностики")
                    d = await _run_local_diag()

                state["diag_results"] = d.get("checks", [])
                overall = d.get("overall", "warn")
                ok_c    = d.get("ok_count", 0)
                warn_c  = d.get("warn_count", 0)
                err_c   = d.get("err_count", 0)
                total_ms = d.get("total_ms", 0)
                ts      = d.get("timestamp", "—")

                # Обновляем KPI
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

                # Карточки
                _render_diag_cards()

                # Обновляем Mermaid-схему
                mermaid_code = _build_diag_mermaid(state["diag_results"])
                diag_mermaid.set_content(mermaid_code)

                # Лог
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
                diag_run_btn.set_text("▶ ЗАПУСТИТЬ ДИАГНОСТИКУ")

        async def _run_local_diag() -> dict:
            """Встроенная диагностика без /api/diag (fallback)."""
            import time
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

            async def chk_proxy():
                r = await api_get("/api/health")
                ok = r is not None
                return ("ok" if ok else "err"), ("UP" if ok else "DOWN"), "UP", ""
            await _chk("les-proxy :8050", chk_proxy())

            async def chk_mlx():
                r = await api_get("/api/health", base=MLX_URL)
                if not r:
                    return "err", "DOWN", "UP", "MLX Host недоступен"
                model = r.get("main_model") or r.get("model", "?")
                loaded = r.get("main_loaded", True)
                return ("ok" if loaded else "warn"), model, "loaded", ""
            await _chk("MLX Host :8080", chk_mlx())

            async def chk_qdrant():
                r = await api_get("/api/metrics")
                if not r:
                    return "warn", "—", "—", "metrics недоступны"
                rag = r.get("rag", {})
                st = rag.get("status", "?")
                chunks = rag.get("chunks", 0)
                ok = st in ("ready", "ok")
                return ("ok" if ok else "warn"), f"{chunks} chunks / {st}", "ready", ""
            await _chk("Qdrant (через proxy)", chk_qdrant())

            async def chk_samovar():
                r = await api_get("/api/rag/datasets")
                if r is None:
                    return "err", "—", "—", "datasets недоступны"
                indexed = [d for d in r if d.get("status") in ("INDEXED","READY")]
                return "ok", f"{len(indexed)}/{len(r)} indexed", "≥1", ""
            await _chk("Датасеты RAG", chk_samovar())

            async def chk_mode():
                r = await api_get("/api/mode")
                if not r:
                    return "warn", "—", "rag|code", ""
                return "ok", r.get("mode","?"), "rag|code", ""
            await _chk("Режим (mode)", chk_mode())

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


    # Начальный запрос при загрузке страницы
    ui.timer(0.5, lambda: asyncio.create_task(full_refresh()), once=True)


# ─────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────
app.on_startup(lambda: asyncio.create_task(bg_loop()))

ui.run(
    port=UI_PORT,
    title="С.О.В.У.Ш.К.А. // v4.0",
    favicon="🦉",
    dark=True,
    reload=False,
    host="0.0.0.0",
    show=False,
)
