"""Root status page route."""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["status-page"])


@dataclass
class StatusPageState:
    crag_stats: dict
    proxy_start: float


_state: StatusPageState | None = None


def set_status_page_state(state: StatusPageState) -> None:
    global _state
    _state = state


def get_status_page_state() -> StatusPageState:
    if _state is None:
        raise RuntimeError("status page state is not configured")
    return _state


@router.get("/", response_class=HTMLResponse)
async def status_page():
    state = get_status_page_state()
    uptime = int(time.time() - state.proxy_start)
    h, m = divmod(uptime // 60, 60)
    crag_stats = state.crag_stats
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Л.Е.С.</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#08090b;color:#e2e8f0;font-family:'Courier New',monospace;padding:32px}}
.brand{{color:#3b82f6;font-size:1.4rem;font-weight:900;letter-spacing:2px}}
.sub{{color:#94a3b8;font-size:.7rem;margin-top:4px;margin-bottom:32px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#12151a;border:1px solid #2d3748;border-radius:8px;padding:16px}}
.val{{font-size:1.4rem;font-weight:900;color:#10b981}}
.lbl{{font-size:.6rem;text-transform:uppercase;color:#94a3b8;margin-top:4px;letter-spacing:.5px}}
.ok{{color:#10b981}}.err{{color:#ef4444}}.dim{{color:#94a3b8}}
a{{color:#3b82f6;text-decoration:none}}
</style></head><body>
<div class="brand">[O_O] Л.Е.С.</div>
<div class="sub">Локальная Экспертная Система · les.example.com · proxy :8050</div>
<div class="grid">
  <div class="card"><div class="val ok">UP</div><div class="lbl">Статус прокси</div></div>
  <div class="card"><div class="val">{h}ч {m}м</div><div class="lbl">Uptime</div></div>
  <div class="card"><div class="val">{crag_stats.get("verified",0)}</div><div class="lbl">CRAG Verified</div></div>
  <div class="card"><div class="val">{crag_stats.get("hallucination",0)}</div><div class="lbl">Hallucinations</div></div>
</div>
<div class="card" style="margin-bottom:12px">
  <div class="lbl" style="margin-bottom:8px">Эндпоинты</div>
  <div style="font-size:.75rem;line-height:2;color:#94a3b8">
    <a href="/api/health">/api/health</a> &nbsp;·&nbsp;
    <a href="/api/status">/api/status</a> &nbsp;·&nbsp;
    <a href="/api/metrics">/api/metrics</a> &nbsp;·&nbsp;
    <a href="/api/rag/datasets">/api/rag/datasets</a> &nbsp;·&nbsp;
    <a href="/api/diag">/api/diag</a> &nbsp;·&nbsp;
    <a href="/docs">/docs</a>
  </div>
</div>
<div class="dim" style="font-size:.65rem;margin-top:16px">
  С.О.В.У.Ш.К.А. UI → <a href="http://les.example.com:8051">:8051</a>
</div>
</body></html>""")
