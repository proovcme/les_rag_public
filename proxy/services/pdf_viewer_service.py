"""Self-contained read-only PDF viewer shell for LES/LIST.

The viewer deliberately uses the existing PyMuPDF page renderer instead of a
browser PDF plugin or a CDN dependency.  It therefore behaves the same in a
normal browser and the Windows Tauri/WebView2 shell, while the original PDF is
only opened for reading by the guarded API endpoints.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


PDF_VIEWER_SCHEMA = "list.pdf_viewer.v1"


def pdf_file_info(source_path: str | Path) -> dict:
    import fitz

    path = Path(source_path).expanduser().resolve()
    if path.suffix.lower() != ".pdf":
        raise ValueError("Viewer доступен только для PDF")
    if not path.is_file():
        raise FileNotFoundError("PDF не найден")
    with fitz.open(str(path)) as document:
        if document.page_count < 1:
            raise ValueError("PDF не содержит страниц")
        first = document[0].rect
        return {
            "schema": PDF_VIEWER_SCHEMA,
            "name": path.name,
            "page_count": document.page_count,
            "first_page_size_pt": [round(first.width, 2), round(first.height, 2)],
        }


def _safe_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def viewer_html(
    *,
    path_id: str,
    file_name: str,
    page_count: int,
    initial_page: int = 1,
    highlight_bbox: Iterable[float] | None = None,
) -> str:
    total = max(1, int(page_count))
    page = max(1, min(int(initial_page or 1), total))
    bbox = None
    if highlight_bbox is not None:
        values = [round(float(value), 3) for value in highlight_bbox]
        if len(values) == 4:
            bbox = values
    config = _safe_json({
        "schema": PDF_VIEWER_SCHEMA,
        "path": str(path_id),
        "name": str(file_name),
        "pageCount": total,
        "initialPage": page,
        "highlightBbox": bbox,
    })
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Л.И.С.Т. PDF</title>
  <style>
    :root {{ color-scheme: light; --bg:#eef3f7; --panel:#fff; --text:#18242e; --dim:#647482;
      --accent:#0f8b68; --line:rgba(0,0,0,.12); --shadow:0 12px 34px rgba(20,36,50,.14); }}
    * {{ box-sizing:border-box; }}
    html,body {{ margin:0; min-height:100%; background:var(--bg); color:var(--text);
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      -webkit-font-smoothing:antialiased; }}
    body {{ display:grid; grid-template-rows:auto minmax(0,1fr); height:100vh; overflow:hidden; }}
    .toolbar {{ position:sticky; top:0; z-index:5; display:flex; align-items:center; gap:6px;
      min-height:52px; padding:6px 10px; background:rgba(255,255,255,.94);
      box-shadow:0 1px 0 var(--line),0 8px 24px rgba(20,36,50,.08); backdrop-filter:blur(12px); }}
    .name {{ min-width:0; flex:1 1 180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      font-size:12px; font-weight:800; }}
    button,.open {{ display:inline-flex; align-items:center; justify-content:center; min-width:40px;
      min-height:40px; padding:0 11px; border:0; border-radius:9px; background:transparent;
      color:var(--text); font:700 12px/1 inherit; text-decoration:none; cursor:pointer;
      transition-property:background-color,color,scale,opacity; transition-duration:.14s; }}
    button:hover,.open:hover {{ color:var(--accent); background:rgba(15,139,104,.09); }}
    button:active,.open:active {{ scale:.96; }}
    button:disabled {{ opacity:.32; cursor:default; scale:1; }}
    .page-control {{ display:flex; align-items:center; gap:4px; color:var(--dim); font-size:12px;
      font-variant-numeric:tabular-nums; white-space:nowrap; }}
    #page {{ width:58px; min-height:36px; border:0; border-radius:8px; background:#edf2f5;
      box-shadow:inset 0 0 0 1px var(--line); color:var(--text); text-align:center;
      font:750 12px/1 inherit; font-variant-numeric:tabular-nums; }}
    .zoom {{ min-width:54px; color:var(--dim); font-variant-numeric:tabular-nums; }}
    .stage {{ min-height:0; overflow:auto; overscroll-behavior:contain; padding:18px;
      scroll-behavior:smooth; }}
    .paper {{ width:100%; min-height:180px; display:flex; justify-content:center; align-items:flex-start; }}
    #page-image {{ display:block; width:100%; height:auto; max-width:none; background:#fff;
      border-radius:3px; outline:1px solid rgba(0,0,0,.10); box-shadow:var(--shadow);
      transition-property:opacity,filter; transition-duration:.16s; }}
    #page-image.loading {{ opacity:.48; filter:blur(1px); }}
    .status {{ position:fixed; right:14px; bottom:12px; padding:5px 9px; border-radius:8px;
      background:rgba(24,36,46,.86); color:#fff; font-size:11px; opacity:0;
      transition-property:opacity,transform; transition-duration:.16s; transform:translateY(4px); }}
    .status.visible {{ opacity:1; transform:translateY(0); }}
    @media (max-width:680px) {{
      .toolbar {{ flex-wrap:wrap; }} .name {{ flex-basis:100%; order:-1; }} .stage {{ padding:10px; }}
      .open {{ margin-left:auto; }}
    }}
  </style>
</head>
<body>
  <header class="toolbar" aria-label="Управление PDF">
    <div class="name" id="name"></div>
    <button id="prev" aria-label="Предыдущая страница" title="Предыдущая страница">&#8592;</button>
    <div class="page-control"><input id="page" type="number" min="1"><span id="total"></span></div>
    <button id="next" aria-label="Следующая страница" title="Следующая страница">&#8594;</button>
    <button id="zoom-out" aria-label="Уменьшить" title="Уменьшить">&#8722;</button>
    <button class="zoom" id="zoom" title="Вернуть масштаб 100%">100%</button>
    <button id="zoom-in" aria-label="Увеличить" title="Увеличить">&#43;</button>
    <a class="open" id="open" target="_blank" rel="noopener">Оригинал</a>
  </header>
  <main class="stage" id="stage"><div class="paper"><img id="page-image" alt="Страница PDF"></div></main>
  <div class="status" id="status" role="status"></div>
  <script id="viewer-config" type="application/json">{config}</script>
  <script>
    const cfg = JSON.parse(document.getElementById('viewer-config').textContent);
    const api = location.pathname.startsWith('/lite-api/') ? '/lite-api' : '/api';
    const image = document.getElementById('page-image');
    const pageInput = document.getElementById('page');
    const stage = document.getElementById('stage');
    const status = document.getElementById('status');
    let page = cfg.initialPage;
    let zoom = 100;
    let statusTimer = null;
    document.getElementById('name').textContent = cfg.name;
    document.getElementById('total').textContent = `из ${{cfg.pageCount}}`;
    pageInput.max = String(cfg.pageCount);

    function notify(text) {{
      status.textContent = text; status.classList.add('visible');
      clearTimeout(statusTimer); statusTimer = setTimeout(() => status.classList.remove('visible'), 1300);
    }}
    function boundedPage(value) {{ return Math.max(1, Math.min(cfg.pageCount, Number(value) || 1)); }}
    function render() {{
      page = boundedPage(page); pageInput.value = String(page);
      document.getElementById('prev').disabled = page <= 1;
      document.getElementById('next').disabled = page >= cfg.pageCount;
      document.getElementById('zoom').textContent = `${{zoom}}%`;
      const params = new URLSearchParams({{path:cfg.path,page:String(page),width:String(Math.min(1800,Math.round(1100*zoom/100)))}});
      if (cfg.highlightBbox && page === cfg.initialPage) params.set('highlight_bbox', cfg.highlightBbox.join(','));
      image.classList.add('loading');
      image.style.width = `${{zoom}}%`;
      image.src = `${{api}}/rag/file/pdf-preview?${{params.toString()}}`;
      const raw = new URLSearchParams({{path:cfg.path}});
      document.getElementById('open').href = `${{api}}/rag/file/raw?${{raw.toString()}}#page=${{page}}`;
    }}
    image.addEventListener('load', () => image.classList.remove('loading'));
    image.addEventListener('error', () => {{ image.classList.remove('loading'); notify('Страница недоступна'); }});
    document.getElementById('prev').addEventListener('click', () => {{ page -= 1; stage.scrollTo(0,0); render(); }});
    document.getElementById('next').addEventListener('click', () => {{ page += 1; stage.scrollTo(0,0); render(); }});
    pageInput.addEventListener('change', () => {{ page = boundedPage(pageInput.value); stage.scrollTo(0,0); render(); }});
    document.getElementById('zoom-out').addEventListener('click', () => {{ zoom=Math.max(50,zoom-25); render(); }});
    document.getElementById('zoom-in').addEventListener('click', () => {{ zoom=Math.min(200,zoom+25); render(); }});
    document.getElementById('zoom').addEventListener('click', () => {{ zoom=100; render(); }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'ArrowLeft' && page > 1) {{ page -= 1; render(); }}
      if (event.key === 'ArrowRight' && page < cfg.pageCount) {{ page += 1; render(); }}
    }});
    render();
  </script>
</body>
</html>"""
