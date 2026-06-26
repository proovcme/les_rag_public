"""
С.О.В.У.Ш.К.А. v5.0 — Модульная точка входа
"""
import asyncio
import contextlib
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from fastapi import Request
from nicegui import app, ui
from starlette.responses import HTMLResponse, RedirectResponse

from sovushka.config import QDRANT_VISUALIZER_PORT, STORAGE_SECRET, UI_PORT
from sovushka.state import bg_loop
from sovushka.styles import CUSTOM_CSS, theme_vars_css
from sovushka.auth import register_login_page, get_auth
from sovushka.lite_bridge import register_lite_bridge_routes
from sovushka.m5_display import register_m5_display_routes
from sovushka.trust import trusted_role_for_request


# ── Статические файлы ──
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.add_static_files("/static", str(static_dir))

# Регистрируем /login (отдельная страница, без обвязки main_page)
register_login_page()
# W5.4/5.5: HTML-шеллы lite_chat/lite_admin удалены — мост, рантайм-роуты,
# статика вьювера CAD/BIM и редиректы (`/`→`/classic`, `/les`→`/les/classic`)
# живут в lite_bridge. M5-экран сохранён.
register_lite_bridge_routes()
register_m5_display_routes()


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "sovushka"}


@app.get("/verify-image")
async def verify_image(token: str):
    """Рендер скана для артефакта верификации — same-origin (8051), без кросс-порта/куки."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from proxy.services import verify_service

    p = verify_service.image_path(token)
    if p is None:
        raise HTTPException(404, "нет рендера — повтори «проверь объёмы …»")
    return FileResponse(p, media_type="image/png")


def _start_qdrant_visualizer() -> None:
    """Serve the static Qdrant visualizer on its own local port."""
    with contextlib.suppress(OSError):
        with socket.create_connection(("127.0.0.1", QDRANT_VISUALIZER_PORT), timeout=0.2):
            return

    visualizer_dir = Path(__file__).resolve().parent / "qdrant_visualizer"
    if not visualizer_dir.exists():
        return

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            return

    handler = partial(QuietHandler, directory=str(visualizer_dir))
    server = ThreadingHTTPServer(("0.0.0.0", QDRANT_VISUALIZER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


@app.get("/graph")
async def knowledge_graph_page():
    """W5.7: граф знаний same-origin — данные ходят через /lite-api без CORS."""
    graph_file = Path(__file__).resolve().parent / "qdrant_visualizer" / "index.html"
    if not graph_file.exists():
        return RedirectResponse(f"http://127.0.0.1:{QDRANT_VISUALIZER_PORT}/")
    return HTMLResponse(graph_file.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


_COSMOS_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Граф ЛЕС</title>
<style>
 html,body{margin:0;height:100%;background:#0e1116;color:#e6e9ee;overflow:hidden;
   font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif}
 #graph{position:absolute;inset:0}
 #hud{position:fixed;top:14px;left:14px;background:rgba(22,26,33,.86);border:1px solid #262b35;
   border-radius:10px;padding:10px 14px;font-size:13px;z-index:5;line-height:1.5}
 #hud .m{color:#8b93a1;font-size:12px}
 #note{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);color:#8b93a1;
   font-size:14px;text-align:center;z-index:5;max-width:70%}
 .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#34d399;margin-right:5px}
</style></head><body>
<div id="graph"></div>
<div id="hud"><div><span class="dot"></span>Граф ссылок НТД</div><div class="m" id="meta">…</div></div>
<div id="note">Загрузка графа…</div>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph"></script>
<script>
(async () => {
  const note = document.getElementById('note')
  const API = (location.port === '8050') ? '/api' : '/lite-api'
  try {
    const r = await fetch(`${API}/rag/graph/edges`).then(x => x.json()).catch(() => ({edges: []}))
    const edges = (r && r.edges) || []
    if (!edges.length) { note.textContent = 'Рёбер нет — нужен лексический индекс и документы с номерами НТД.'; return }
    const nm = new Map()
    const nd = (id) => { let v = nm.get(id); if (!v) { v = {id: id, deg: 0}; nm.set(id, v); } return v; }
    const links = []
    for (const e of edges) { nd(e.source).deg++; nd(e.target).deg++; links.push({source: e.source, target: e.target}); }
    const nodes = Array.from(nm.values())
    if (typeof ForceGraph3D === 'undefined') { note.textContent = '3d-force-graph не загрузился (CDN).'; return }
    const G = ForceGraph3D()(document.getElementById('graph'))
      .backgroundColor('#0e1116')
      .graphData({nodes: nodes, links: links})
      .nodeLabel(n => n.id + ' · ' + n.deg + ' связей')
      .nodeVal(n => 0.7 + Math.sqrt(n.deg) * 0.7)
      .nodeColor(n => 'hsl(' + (162 - Math.min(n.deg, 28)) + ', 70%, ' + (42 + Math.min(n.deg, 26)) + '%)')
      .nodeOpacity(0.9)
      .linkColor(() => 'rgba(110,231,183,0.42)')
      .linkWidth(0.8)
      .linkOpacity(0.5)
      .linkDirectionalParticles(1)
      .linkDirectionalParticleWidth(1.1)
      .linkDirectionalParticleColor(() => '#9ff5d0')
      .enableNodeDrag(false)
      .warmupTicks(60)
    try { G.d3Force('charge').strength(-130); } catch (e) {}
    try { G.d3Force('link').distance(36); } catch (e) {}
    note.remove()
    document.getElementById('meta').textContent = nodes.length + ' узлов · ' + edges.length + ' рёбер · 3D';
    let a = 0; const dist = 1200;
    G.cameraPosition({z: dist});
    setInterval(() => { a += 0.0016; G.cameraPosition({x: dist * Math.sin(a), z: dist * Math.cos(a)}); }, 30);
  } catch (err) { note.textContent = 'Ошибка графа: ' + (err && err.message || err); }
})()
</script></body></html>"""


@app.get("/graph-cosmos")
async def cosmos_graph_page():
    """3D-граф ссылок НТД (3d-force-graph): узлы из /api/rag/graph/edges (same-origin /lite-api),
    зелёные/крупнее по числу связей, авто-вращение. /graph — legacy-фолбэк."""
    return HTMLResponse(_COSMOS_HTML, headers={"Cache-Control": "no-store"})


def _build_qdrant_visualizer_panel(visualizer_url: str) -> None:
    with ui.column().classes("w-full h-full gap-0").style("background:var(--bg);"):
        with ui.row().classes("items-center justify-between w-full px-4 py-2").style(
            "border-bottom:1px solid var(--border);background:var(--bg-panel);"
        ):
            ui.label("Граф знаний ЛЕС").style(
                "font-size:14px;font-weight:500;color:var(--text);"
            )
            ui.button("ОТКРЫТЬ В ОТДЕЛЬНОЙ ВКЛАДКЕ", on_click=lambda: ui.navigate.to(visualizer_url, new_tab=True)).props(
                "flat no-caps dense"
            ).style("color:var(--accent);font-size:.62rem;font-family:var(--font);")

        ui.element("iframe").props(f'src="{visualizer_url}"').classes("w-full flex-1").style(
            "border:0;background:#060913;min-height:calc(100vh - 88px);"
        )


def _apply_theme() -> None:
    """Inject theme CSS before rendering the page body."""
    _dark = app.storage.user.get("dark_theme", True)
    ui.add_head_html(theme_vars_css(_dark))
    ui.add_head_html(CUSTOM_CSS)
    # WCAG 3.1.1 Language of Page: интерфейс и контент русские — помечаем
    # документ lang=ru, иначе скринридеры читают кириллицу как английский.
    ui.add_head_html("<script>document.documentElement.lang='ru'</script>")
    ui.query("body").style("background:var(--bg);color:var(--text);margin:0;")
    ui.query(".nicegui-content").classes("p-0 m-0 w-full").style("max-width:none;")


def _resolve_auth(request: Request):
    is_auth, role, holder = get_auth()

    trusted_role = trusted_role_for_request(request)

    if not is_auth and not trusted_role:
        return False, None, None, False

    if not is_auth and trusted_role:
        role = trusted_role
        holder = "Trusted Network"

    is_admin = (role == "admin")
    return True, role, holder, is_admin


@ui.page("/classic")
async def classic_chat_page(request: Request):
    from sovushka.components.header import build_header
    from sovushka.pages.chat import build_chat
    from sovushka.pages.history import build_history

    allowed, role, holder, is_admin = _resolve_auth(request)
    if not allowed:
        return RedirectResponse("/login")

    _apply_theme()

    # Public shell: only chat/history. It stays lean and avoids mounting admin pages.
    with ui.column().classes("w-full h-screen no-wrap gap-0"):
        tabs, tr = build_header(
            is_admin,
            role,
            holder,
            admin_tabs=False,
            admin_link=is_admin,
        )

        tab_chat = tr["chat"]
        tab_history = tr["history"]

        def _save_chat_tab(e):
            try:
                val = e.args if isinstance(e.args, str) else (e.args[0] if isinstance(e.args, (list, tuple)) and e.args else None)
                if val:
                    app.storage.user["last_chat_tab"] = str(val)
            except Exception:
                pass

        tabs.on("update:model-value", _save_chat_tab)

        with ui.tab_panels(tabs, value=tab_chat).classes("w-full flex-1").style(
            "background:var(--bg);overflow-y:auto;padding:0;"
        ):
            with ui.tab_panel(tab_chat):
                build_chat(is_admin, tabs, None)
            with ui.tab_panel(tab_history):
                build_history(tabs, tab_chat)

    _last_tab = app.storage.user.get("last_chat_tab", "AI ЧАТ")
    _target = {"AI ЧАТ": tab_chat, "ИСТОРИЯ": tab_history}.get(_last_tab)
    if _target and _target != tab_chat:
        tabs.set_value(_target)


@ui.page("/les/classic")
@ui.page("/les/classic/")
async def classic_admin_page(request: Request):
    from sovushka.components.header import build_header
    from sovushka.components.logterm import build_log_terminal
    from sovushka.pages.diag import build_diag
    from sovushka.pages.samovar import build_samovar
    from sovushka.pages.volk import build_volk

    allowed, role, holder, is_admin = _resolve_auth(request)
    if not allowed:
        return RedirectResponse("/login")

    if not is_admin:
        return RedirectResponse("/")

    _apply_theme()

    # Layout: Header (со встроенными табами) + Content + Footer
    with ui.column().classes("w-full h-screen no-wrap gap-0"):
        # W5.7: граф знаний same-origin (/lite-api, без CORS). Cosmos.gl GPU-граф (/graph → legacy-фолбэк).
        visualizer_url = "/graph-cosmos"

        # Единая полоса: лого + табы + контролы
        tabs, tr = build_header(
            is_admin,
            role,
            holder,
            include_chat=False,
            chat_link=True,
            visualizer_url=visualizer_url,
        )

        tab_diag       = tr.get("diag")
        tab_samovar    = tr.get("samovar")
        tab_qdrant_viz = tr.get("qdrant_viz")
        tab_volk       = tr.get("volk")

        # Персистим активный таб
        def _save_tab(e):
            try:
                val = e.args if isinstance(e.args, str) else (e.args[0] if isinstance(e.args, (list, tuple)) and e.args else None)
                if val:
                    app.storage.user["last_tab"] = str(val)
            except Exception:
                pass
        tabs.on("update:model-value", _save_tab)

        # Контент — Состояние (landing) / Датасеты / Визуал
        _default_tab = tab_diag
        with ui.tab_panels(tabs, value=_default_tab).classes("w-full flex-1").style(
            "background:var(--bg);overflow-y:auto;padding:0;"
        ):
            with ui.tab_panel(tab_diag):
                build_diag()
            with ui.tab_panel(tab_samovar):
                build_samovar()
            with ui.tab_panel(tab_qdrant_viz):
                _build_qdrant_visualizer_panel(visualizer_url)
            with ui.tab_panel(tab_volk):
                build_volk()

        # Подвал (Лог)
        build_log_terminal()

    # Восстанавливаем последний активный таб
    _last_tab = app.storage.user.get("last_tab", "Состояние")
    _tab_map = {
        "Состояние": tab_diag,
        "Датасеты":  tab_samovar,
        "Визуал":    tab_qdrant_viz,
        "Доступ":    tab_volk,
    }
    _target = _tab_map.get(_last_tab)
    if _target and _target != _default_tab:
        tabs.set_value(_target)



if __name__ in {"__main__", "__mp_main__"}:
    # Фоновые задачи запускаем при старте UI
    app.on_startup(lambda: asyncio.create_task(bg_loop()))
    app.on_startup(_start_qdrant_visualizer)
    
    ui.run(
        port=UI_PORT,
        title="Л.Е.С. v5.0",
        dark=True,
        show=False,
        storage_secret=STORAGE_SECRET,
        reload=False,
        reconnect_timeout=180,  # длинные RAG-запросы не должны срывать страницу
    )
