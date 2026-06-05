"""Lightweight static admin shell for Sovushka.

The default admin route should be cheap to open while memory is under pressure.
The richer NiceGUI console remains available at /les/classic.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from sovushka.lite_chat import _client_is_loopback
from sovushka.trust import trusted_role_for_request


LOCAL_RUNTIME_ACTIONS = {
    "start_indexer",
    "stop_indexer",
    "restart_proxy",
    "restart_mlx",
    "restart_qdrant",
    "restart_ui",
}


def local_runtime_action_allowed(*, is_loopback: bool, is_trusted_network: bool = False) -> bool:
    return is_loopback or is_trusted_network


def _local_runtime_request_allowed(request: Request) -> bool:
    return local_runtime_action_allowed(
        is_loopback=_client_is_loopback(request),
        is_trusted_network=bool(trusted_role_for_request(request)),
    )


def _runtime_result_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_runtime_result_payload(item) for item in value]
    try:
        return asdict(value)
    except TypeError:
        return value


def _runtime_action(name: str) -> Callable[[], Any]:
    from tools import les_runtime_control

    actions: dict[str, Callable[[], Any]] = {
        "start_indexer": lambda: les_runtime_control.start_service("indexer"),
        "stop_indexer": lambda: les_runtime_control.stop_service("indexer"),
        "restart_proxy": lambda: les_runtime_control.restart_service("proxy"),
        "restart_mlx": lambda: les_runtime_control.restart_service("mlx"),
        "restart_qdrant": lambda: les_runtime_control.restart_service("qdrant"),
        "restart_ui": lambda: les_runtime_control.restart_service("ui", False),
    }
    return actions[name]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _reindex_paths() -> dict[str, Path]:
    root = _repo_root()
    artifacts = root / "artifacts" / "reindex_runs"
    return {
        "artifacts": artifacts,
        "state": artifacts / "reindex_state_ntd_fire_index__ntd_hvac_index.json",
        "pid": artifacts / "guarded_reindex_hvac_fire.pid.json",
    }


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        status = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
        if status.startswith("Z"):
            return False
    except Exception:
        pass
    return True


def guarded_reindex_status_payload() -> dict[str, Any]:
    paths = _reindex_paths()
    pid_info: dict[str, Any] = {}
    if paths["pid"].exists():
        try:
            pid_info = json.loads(paths["pid"].read_text(encoding="utf-8"))
        except Exception:
            pid_info = {}
    pid = int(pid_info.get("pid") or 0)
    running = _pid_running(pid)

    state: dict[str, Any] = {}
    if paths["state"].exists():
        try:
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
        except Exception as error:
            state = {"error": str(error)}

    completed = state.get("completed") if isinstance(state, dict) else {}
    completed_count = len(completed) if isinstance(completed, dict) else 0
    return {
        "running": running,
        "pid": pid if running else None,
        "pid_file": str(paths["pid"]),
        "state_file": str(paths["state"]),
        "completed": completed_count,
        "total": 194,
        "remaining": max(0, 194 - completed_count),
        "updated_at": state.get("updated_at") if isinstance(state, dict) else None,
        "runs": len(state.get("runs") or []) if isinstance(state, dict) else 0,
        "last_log": pid_info.get("log_path"),
        "last_started_at": pid_info.get("started_at"),
    }


async def lite_runtime_status(request: Request) -> JSONResponse:
    if not _local_runtime_request_allowed(request):
        return JSONResponse({"detail": "Local runtime status requires trusted local access"}, status_code=403)

    from tools import les_runtime_control

    statuses = await asyncio.to_thread(
        les_runtime_control.all_statuses,
        ["qdrant", "mlx", "proxy", "indexer", "ui"],
    )
    return JSONResponse({"services": _runtime_result_payload(statuses)})


async def lite_reindex_status(request: Request) -> JSONResponse:
    if not _local_runtime_request_allowed(request):
        return JSONResponse({"detail": "Local reindex status requires trusted local access"}, status_code=403)
    return JSONResponse(guarded_reindex_status_payload())


async def lite_runtime_action(action: str, request: Request) -> JSONResponse:
    if action not in LOCAL_RUNTIME_ACTIONS:
        return JSONResponse({"detail": f"Unknown action: {action}"}, status_code=404)
    if not _local_runtime_request_allowed(request):
        return JSONResponse({"detail": "Local runtime actions require trusted local access"}, status_code=403)

    result = await asyncio.to_thread(_runtime_action(action))
    return JSONResponse({"action": action, "result": _runtime_result_payload(result)})


def lite_admin_html() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Л.Е.С. Lite Admin</title>
  <style>
    :root {
      --bg: #07090c;
      --panel: #10161d;
      --panel2: #151d26;
      --text: #f4f7fb;
      --dim: #9fb0c1;
      --muted: #6f8193;
      --line: #263748;
      --accent: #38bdf8;
      --ok: #22c55e;
      --warn: #f59e0b;
      --err: #ef4444;
      --font: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      background: #07090c;
      color: var(--text);
      font-family: var(--font);
    }
    button, input, select { font: inherit; }
    .topbar {
      min-height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(16, 22, 29, .96);
      position: sticky;
      top: 0;
      z-index: 3;
    }
    .brand-title {
      color: var(--accent);
      font-size: .92rem;
      font-weight: 900;
      letter-spacing: .08em;
    }
    .brand-sub {
      color: var(--dim);
      font-size: .62rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .chips {
      display: flex;
      gap: 6px;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
    .chip {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 4px 8px;
      color: var(--dim);
      background: rgba(7, 9, 12, .35);
      font-size: .58rem;
      font-weight: 900;
      white-space: nowrap;
    }
    .ok { color: var(--ok); border-color: rgba(34,197,94,.45); }
    .warn { color: var(--warn); border-color: rgba(245,158,11,.45); }
    .err { color: var(--err); border-color: rgba(239,68,68,.45); }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 12px;
      padding: 12px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      align-items: start;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(16, 22, 29, .72);
      padding: 12px;
      min-width: 0;
    }
    .panel-wide { grid-column: span 3; }
    .title {
      color: var(--dim);
      text-transform: uppercase;
      font-size: .58rem;
      font-weight: 900;
      margin-bottom: 8px;
    }
    .value {
      font-size: 1.35rem;
      font-weight: 900;
      overflow-wrap: anywhere;
    }
    .hint {
      color: var(--muted);
      font-size: .66rem;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid rgba(38, 55, 72, .55);
      padding: 7px 0;
      min-width: 0;
    }
    .row:last-child { border-bottom: 0; }
    .row-main { min-width: 0; }
    .row-name {
      color: var(--text);
      font-size: .72rem;
      font-weight: 800;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .row-meta {
      color: var(--muted);
      font-size: .58rem;
      overflow-wrap: anywhere;
    }
    .actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    .actions select { width: auto; min-width: 120px; }
    button, .linkbtn {
      min-height: 32px;
      border: 1px solid rgba(56,189,248,.45);
      border-radius: 7px;
      color: var(--accent);
      background: rgba(56,189,248,.08);
      padding: 7px 10px;
      cursor: pointer;
      font-weight: 900;
      font-size: .62rem;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    button:hover, .linkbtn:hover { background: rgba(56,189,248,.16); }
    button:disabled { opacity: .45; cursor: wait; }
    .danger { color: var(--err); border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.08); }
    .safe { color: var(--ok); border-color: rgba(34,197,94,.45); background: rgba(34,197,94,.08); }
    .side {
      position: sticky;
      top: 70px;
      align-self: start;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .log {
      min-height: 150px;
      max-height: 360px;
      overflow: auto;
      white-space: pre-wrap;
      color: var(--dim);
      font-size: .62rem;
      line-height: 1.42;
      border: 1px solid rgba(38,55,72,.65);
      border-radius: 7px;
      background: rgba(7,9,12,.48);
      padding: 8px;
    }
    .auth {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 10;
      background: rgba(7, 9, 12, .92);
      align-items: center;
      justify-content: center;
      padding: 18px;
    }
    .auth-card {
      width: min(420px, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 18px;
    }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: rgba(7, 9, 12, .72);
      color: var(--text);
      padding: 8px 10px;
      outline: none;
      font-size: .76rem;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }
    .form-grid .wide { grid-column: span 3; }
    .checkline {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--dim);
      font-size: .68rem;
      font-weight: 800;
    }
    .checkline input { width: auto; }
    .viewer-shell {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 260px;
      gap: 10px;
      margin-top: 10px;
      align-items: stretch;
    }
    .viewer-canvas-wrap {
      min-height: 360px;
      border: 1px solid rgba(38,55,72,.65);
      border-radius: 7px;
      background: #05070a;
      overflow: hidden;
    }
    #cadBimCanvas {
      width: 100%;
      height: 360px;
      display: block;
    }
    .viewer-side {
      min-height: 360px;
      border: 1px solid rgba(38,55,72,.65);
      border-radius: 7px;
      background: rgba(7,9,12,.48);
      padding: 8px;
      overflow: auto;
    }
    @media (max-width: 1020px) {
      .layout { grid-template-columns: 1fr; }
      .side { position: static; }
      .grid { grid-template-columns: 1fr; }
      .panel-wide { grid-column: span 1; }
      .viewer-shell { grid-template-columns: 1fr; }
      .viewer-side { min-height: 180px; }
    }
    @media (max-width: 640px) {
      .topbar { align-items: flex-start; flex-direction: column; }
      .chips { justify-content: flex-start; }
      .layout { padding: 10px; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <div>
      <div class="brand-title">Л.Е.С. LITE ADMIN</div>
      <div class="brand-sub">статическая админка без NiceGUI client state</div>
    </div>
    <div class="chips">
      <span id="authChip" class="chip">AUTH ...</span>
      <span id="profileChip" class="chip">PROFILE ...</span>
      <span id="memoryChip" class="chip">MEM ...</span>
      <span id="jobsChip" class="chip">JOBS ...</span>
    </div>
  </header>

  <main class="layout">
    <section class="grid">
      <div class="panel panel-wide">
        <div class="title">Dispatcher / Reindex</div>
        <div id="campaignValue" class="value">...</div>
        <div id="campaignHint" class="hint"></div>
        <div class="actions">
          <button id="startReindexBtn" type="button" class="safe">START</button>
          <button id="pauseReindexBtn" type="button">PAUSE</button>
          <button id="resumeReindexBtn" type="button">RESUME</button>
          <button id="refreshBtn" type="button">REFRESH</button>
        </div>
        <div id="dispatcherList" class="hint"></div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Watcher</div>
        <div id="watcherValue" class="value">...</div>
        <div id="watcherHint" class="hint"></div>
        <div id="watcherGroups" class="hint"></div>
      </div>

      <div class="panel panel-wide">
        <div class="title">CAD/BIM JSON</div>
        <div id="speckleHint" class="hint">CAD/BIM JSON параметры ещё не загружены.</div>
        <div class="form-grid">
          <input id="speckleBaseUrl" class="wide" type="url" placeholder="https://speckle.example.com">
          <input id="speckleGraphqlUrl" class="wide" type="url" placeholder="https://speckle.example.com/graphql">
          <input id="speckleToken" class="wide" type="password" placeholder="Speckle API token">
          <input id="speckleSourcePath" class="wide" type="text" placeholder="RAG_Content/CAD_BIM/JSON/model.json">
          <select id="speckleSourceType">
            <option value="">AUTO</option>
            <option value="autocad">AutoCAD / DWG</option>
            <option value="revit">Revit / RVT</option>
            <option value="ifc">IFC</option>
            <option value="excel">Excel / Power BI</option>
            <option value="generic">Generic</option>
          </select>
          <input id="speckleTimeout" type="number" min="0.5" max="60" step="0.5" value="5" title="WAKE TIMEOUT">
          <label class="checkline"><input id="speckleEnabled" type="checkbox"> enabled</label>
          <label class="checkline wide"><input id="speckleClear" type="checkbox"> сбросить Speckle token</label>
        </div>
        <div class="actions">
          <button id="speckleSaveBtn" type="button" class="safe">SAVE SPECKLE</button>
          <button id="speckleCheckBtn" type="button">CHECK SPECKLE</button>
          <button id="speckleImportBtn" type="button">IMPORT JSON GRAPH</button>
          <button id="cadBimSyncBtn" type="button">SYNC CAD/BIM</button>
        </div>
      </div>

      <div class="panel panel-wide">
        <div class="title">VIZOR</div>
        <div id="cadBimViewerHint" class="hint">JSON graph не загружен.</div>
        <div class="actions">
          <select id="cadBimViewMode" title="VIEW MODE">
            <option value="auto">AUTO</option>
            <option value="geometry">2D</option>
            <option value="graph">GRAPH</option>
          </select>
          <button id="cadBimViewBtn" type="button">VIEW JSON</button>
          <button id="cadBimObcViewBtn" type="button">OPEN OBC VIEWER</button>
        </div>
        <div class="viewer-shell">
          <div class="viewer-canvas-wrap">
            <canvas id="cadBimCanvas" width="960" height="360"></canvas>
          </div>
          <div class="viewer-side">
            <div id="cadBimViewerStats" class="hint"></div>
            <div id="cadBimViewerLayers" class="hint"></div>
          </div>
        </div>
      </div>

      <div class="panel panel-wide">
        <div class="title">External Providers</div>
        <div id="providerHint" class="hint">OpenRouter и OpenAI-compatible параметры ещё не загружены.</div>
        <div class="form-grid">
          <input id="openrouterBaseUrl" class="wide" type="url" placeholder="https://openrouter.ai/api/v1">
          <input id="openrouterModel" class="wide" type="text" placeholder="openrouter model id">
          <input id="openrouterKey" class="wide" type="password" placeholder="OpenRouter API key">
          <label class="checkline wide"><input id="openrouterClear" type="checkbox"> сбросить OpenRouter key</label>
          <input id="openaiBaseUrl" class="wide" type="url" placeholder="OpenAI-compatible base URL">
          <input id="openaiModel" class="wide" type="text" placeholder="OpenAI-compatible model id">
          <input id="openaiKey" class="wide" type="password" placeholder="OpenAI-compatible API key">
          <label class="checkline wide"><input id="openaiClear" type="checkbox"> сбросить OpenAI-compatible key</label>
        </div>
        <div class="actions">
          <button id="providerSaveBtn" type="button" class="safe">SAVE PROVIDERS</button>
        </div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Е.Ж.И.К. Mail</div>
        <div id="mailHint" class="hint">IMAP параметры ещё не загружены.</div>
        <div class="form-grid">
          <input id="mailHost" type="text" placeholder="imap.yandex.ru">
          <input id="mailPort" type="number" min="1" max="65535" step="1" placeholder="993">
          <select id="mailSsl">
            <option value="true">SSL</option>
            <option value="false">NO SSL</option>
          </select>
          <input id="mailLogin" class="wide" type="text" placeholder="mail@yandex.ru">
          <input id="mailPassword" class="wide" type="password" placeholder="пароль приложения">
          <input id="mailFolders" class="wide" type="text" placeholder="INBOX">
          <input id="mailCount" type="number" min="1" max="200" step="1" value="50" title="MAIL COUNT">
          <label class="checkline wide"><input id="mailOcr" type="checkbox"> OCR вложений</label>
        </div>
        <div class="actions">
          <button id="mailYandexBtn" type="button">YANDEX PRESET</button>
          <button id="mailSaveBtn" type="button" class="safe">SAVE MAIL</button>
          <button id="mailImportBtn" type="button">IMPORT+INDEX</button>
          <button id="mailAppleBtn" type="button">APPLE MAIL 10</button>
        </div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Jobs</div>
        <div id="jobsValue" class="value">...</div>
        <div id="jobsList" class="hint"></div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Memory</div>
        <div id="memoryValue" class="value">...</div>
        <div id="memoryHint" class="hint"></div>
        <div class="actions">
          <button id="unloadMlxBtn" type="button">UNLOAD MLX</button>
          <a class="linkbtn" href="/">ЧАТ</a>
          <a class="linkbtn" href="/classic">CLASSIC CHAT</a>
          <a class="linkbtn" href="/les/classic">CLASSIC ADMIN</a>
        </div>
        <div id="memoryRecommendations" class="hint"></div>
        <div id="memoryConsumers" class="hint"></div>
      </div>
    </section>

    <aside class="side">
      <div class="panel">
        <div class="title">Runtime</div>
        <div id="runtimeList" class="hint">Локальный статус доступен с localhost или trusted-сети.</div>
      </div>
      <div class="panel">
        <div class="title">Log</div>
        <div id="log" class="log"></div>
      </div>
    </aside>
  </main>

  <div id="authPanel" class="auth">
    <div class="auth-card">
      <div class="brand-title">В.О.Л.К.</div>
      <div class="hint">Введите admin key. На localhost или trusted-сети доступ может открыться без ключа.</div>
      <div style="height:12px"></div>
      <input id="keyInput" type="password" placeholder="les_xxxxxxxxxxxxxxxx">
      <div style="height:10px"></div>
      <button id="loginBtn" type="button">ВОЙТИ</button>
      <div id="authError" class="hint" style="color:var(--err);min-height:18px;margin-top:8px"></div>
    </div>
  </div>

  <script>
    const isLocalUi = location.port === "8051";
    const API_BASE = isLocalUi ? "/lite-api" : "";
    const KEY_STORAGE = "les_lite_api_key";
    const ROLE_STORAGE = "les_lite_role";
    const HOLDER_STORAGE = "les_lite_holder";
    const state = {
      key: localStorage.getItem(KEY_STORAGE) || "",
      role: localStorage.getItem(ROLE_STORAGE) || "",
      holder: localStorage.getItem(HOLDER_STORAGE) || "",
      busy: false,
      mailDirty: false,
      mailPasswordSet: false,
      providerDirty: false,
      openrouterKeySet: false,
      openaiKeySet: false,
      speckleDirty: false,
      speckleTokenSet: false,
      cadBimViewerPayload: null,
    };
    const el = (id) => document.getElementById(id);

    function apiPath(path) {
      if (!API_BASE) return path;
      return API_BASE + path.replace(/^\/api(?=\/)/, "");
    }

    function headers(json = true) {
      const out = { "Accept": "application/json" };
      if (json) out["Content-Type"] = "application/json";
      if (state.key) out["X-API-Key"] = state.key;
      return out;
    }

    async function request(path, options = {}) {
      const response = await fetch(apiPath(path), {
        ...options,
        headers: { ...headers(options.body !== undefined), ...(options.headers || {}) },
      });
      const text = await response.text();
      let payload = {};
      try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { detail: text }; }
      if (!response.ok) {
        const detail = payload.detail || payload.error || ("HTTP " + response.status);
        const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
        error.status = response.status;
        throw error;
      }
      return payload;
    }

    async function bootstrapTrustedAccess() {
      try {
        const trust = await request("/api/auth/trust");
        if (trust.trusted) {
          if (state.key) {
            localStorage.removeItem(KEY_STORAGE);
            localStorage.removeItem(ROLE_STORAGE);
            localStorage.removeItem(HOLDER_STORAGE);
          }
          state.key = "";
          state.role = trust.role || "admin";
          state.holder = trust.holder || "trusted-network";
          showAuth(false);
          chip("authChip", "TRUSTED", "ok");
          log("trusted access -> " + (trust.client_ip || trust.source || "?"));
        } else {
          log("trust miss -> peer=" + (trust.peer_ip || "-") + " client=" + (trust.client_ip || "-"));
        }
      } catch (error) {
        log("trust check error: " + error.message);
      }
    }

    function fingerprint() {
      const items = [
        navigator.userAgent || "",
        (navigator.languages || [navigator.language || ""]).join(","),
        screen.width + "x" + screen.height + "x" + (screen.colorDepth || 24),
        navigator.hardwareConcurrency || 0,
        Intl.DateTimeFormat().resolvedOptions().timeZone || "",
        navigator.platform || "",
      ];
      let h = 5381;
      const s = items.join("|");
      for (let i = 0; i < s.length; i++) h = (((h << 5) + h) ^ s.charCodeAt(i)) >>> 0;
      return "fp_" + h.toString(16).padStart(8, "0");
    }

    function log(line) {
      const ts = new Date().toLocaleTimeString();
      el("log").textContent = `[${ts}] ${line}\n` + el("log").textContent;
    }

    function chip(id, text, cls) {
      const node = el(id);
      node.textContent = text;
      node.className = "chip" + (cls ? " " + cls : "");
    }

    function showAuth(show, message = "") {
      el("authPanel").style.display = show ? "flex" : "none";
      el("authError").textContent = message;
    }

    function fmt(n) {
      return Number(n || 0).toLocaleString("ru-RU");
    }

    function chipNode(text, cls = "") {
      const node = document.createElement("span");
      node.className = "chip" + (cls ? " " + cls : "");
      node.textContent = text || "";
      return node;
    }

    function rowNode(name, meta, badge, cls = "") {
      const row = document.createElement("div");
      row.className = "row";
      const main = document.createElement("div");
      main.className = "row-main";
      const title = document.createElement("div");
      title.className = "row-name";
      title.textContent = name || "";
      const detail = document.createElement("div");
      detail.className = "row-meta";
      detail.textContent = meta || "";
      main.append(title, detail);
      row.append(main, chipNode(badge || "", cls));
      return row;
    }

    function setRows(id, rows, emptyText = "Нет данных") {
      const node = el(id);
      if (!rows.length) {
        node.replaceChildren(chipNode(emptyText, "ok"));
        return;
      }
      node.replaceChildren(...rows);
    }

    async function login() {
      const key = el("keyInput").value.trim();
      if (!key) {
        showAuth(true, "Введите ключ доступа");
        return;
      }
      el("loginBtn").disabled = true;
      try {
        const result = await request("/api/auth/verify", {
          method: "POST",
          body: JSON.stringify({ key, fingerprint: fingerprint() }),
        });
        state.key = key;
        state.role = result.role || "user";
        state.holder = result.holder || "";
        localStorage.setItem(KEY_STORAGE, state.key);
        localStorage.setItem(ROLE_STORAGE, state.role);
        localStorage.setItem(HOLDER_STORAGE, state.holder);
        showAuth(false);
        log("auth ok: " + (state.holder || state.role));
        await refreshAll();
      } catch (error) {
        showAuth(true, error.message);
      } finally {
        el("loginBtn").disabled = false;
      }
    }

    async function refreshAll() {
      try {
        const [mode, dispatcher, watcher, routePlan, settings, jobs] = await Promise.all([
          request("/api/indexing-mode"),
          request("/api/runtime/dispatcher/status"),
          request("/api/rag/watch/status?source_root=RAG_Content&limit=20"),
          request("/api/rag/watch/reindex-plan?source_root=RAG_Content&limit=50"),
          request("/api/settings"),
          request("/api/jobs/summary?limit=8"),
        ]);
        showAuth(false);
        renderHeader(mode, dispatcher);
        renderDispatcher(dispatcher);
        renderWatcher(watcher, routePlan);
        renderSpeckleSettings(settings);
        renderProviderSettings(settings);
        renderMailSettings(settings);
        renderJobs(jobs);
        renderMemory(dispatcher);
        log("refresh ok");
      } catch (error) {
        if (error.status === 401 && !state.key) {
          chip("authChip", "KEY REQUIRED", "warn");
          showAuth(true);
          log("auth required");
          return;
        }
        if (error.status === 401 || error.status === 403) {
          localStorage.removeItem(KEY_STORAGE);
          state.key = "";
          chip("authChip", "AUTH FAIL", "err");
          showAuth(true, error.message);
          return;
        }
        log("refresh error: " + error.message);
      }
    }

    function renderHeader(mode, dispatcher) {
      const dispatcherMemory = dispatcher?.memory?.pressure || {};
      const memory = dispatcherMemory.state ? dispatcherMemory : (mode.memory_state || {});
      const admission = mode.chat_admission || {};
      const profile = dispatcher?.runtime_profile || mode.runtime_profile || "?";
      const memState = memory.state || "?";
      chip("authChip", state.key ? (state.role || "KEY") : "TRUSTED", "ok");
      chip("profileChip", profile, admission.allowed === false ? "err" : "ok");
      chip("memoryChip", memState, memState === "GREEN" ? "ok" : memState === "YELLOW" ? "warn" : "err");
      chip("jobsChip", (admission.active_jobs || 0) + " JOBS", admission.active_jobs ? "warn" : "ok");
    }

    function renderDispatcher(data) {
      const services = data.services || [];
      setRows("runtimeList", services.map((svc) => rowNode(
        svc.title || svc.key || "service",
        `${svc.label || ""} | pid ${svc.pid || svc.port_pid || "-"} | :${svc.port || "-"}`,
        svc.health || (svc.running ? "UP" : "DOWN"),
        svc.running && svc.health === "ok" ? "ok" : svc.running ? "warn" : "err"
      )), "NO SERVICES");

      const reindex = data.reindex || {};
      const cls = reindex.running ? "warn" : reindex.remaining === 0 && reindex.total ? "ok" : "";
      const label = reindex.running ? "RUNNING" : reindex.paused ? "PAUSED" : reindex.complete ? "DONE" : "IDLE";
      el("campaignValue").textContent = `${fmt(reindex.completed)} / ${fmt(reindex.total || 0)}`;
      el("campaignHint").textContent =
        `${label} | remaining=${fmt(reindex.remaining)} | pid=${reindex.pid || "-"} | ${reindex.last_log || ""}`;
      setRows("dispatcherList", [
        rowNode(label, `updated=${reindex.updated_at || "-"} | current=${reindex.current_doc?.event || reindex.last_event?.event || "-"}`, reindex.running ? "ACTIVE" : "IDLE", cls),
        rowNode("Guard", `min_free=${reindex.guard?.min_free_gb ?? "?"}GB | max_swap=${reindex.guard?.max_swap_pct ?? "?"}%`, reindex.supports_pause ? "PAUSABLE" : "LEGACY", reindex.supports_pause ? "ok" : "warn"),
      ]);

      const actions = data.actions || {};
      el("startReindexBtn").disabled = !actions.can_start;
      el("pauseReindexBtn").disabled = !actions.can_pause;
      el("resumeReindexBtn").disabled = !actions.can_resume;
      if (actions.blocked_reason) log("dispatcher block: " + actions.blocked_reason);
    }

    function renderWatcher(watcher, routePlan) {
      const counts = watcher.counts || {};
      el("watcherValue").textContent =
        `${fmt(counts.new)} new / ${fmt(counts.changed)} changed / ${fmt(counts.route_changed)} route`;
      el("watcherHint").textContent =
        `source=${watcher.source_root || "RAG_Content"} | pending=${fmt(watcher.pending_changes)} | route_changes=${fmt(routePlan.pending_route_changes)}`;
      const groupRows = (routePlan.groups || []).map((group) => rowNode(
        `${group.current_dataset_name || "?"} -> ${group.target_dataset_name || "?"}`,
        `${fmt(group.files)} files | ${(Number(group.bytes || 0) / 1024 / 1024).toFixed(1)} MB`,
        "ROUTE",
        "warn"
      ));
      const sampleRows = (watcher.samples || []).slice(0, 8).map((sample) => rowNode(
        sample.relative_path || "",
        `${sample.state} | ${sample.current?.dataset_name || "new"} -> ${sample.dataset_name || ""}`,
        sample.state || "",
        sample.state === "route_changed" ? "warn" : sample.state === "new" ? "ok" : ""
      ));
      setRows("watcherGroups", [...groupRows, ...sampleRows], "NO CHANGES");
    }

    function renderJobs(data) {
      const jobs = data.jobs || [];
      el("jobsValue").textContent = `${fmt(data.active_count || 0)} active / ${fmt(data.count || jobs.length)} shown`;
      setRows("jobsList", jobs.map((job) => rowNode(
        `${job.type || "job"} ${job.id || ""}`,
        `${job.processed || 0}/${job.total || 0} | ${job.message || job.dataset_name || ""}`,
        job.status || "",
        String(job.status || "").toLowerCase() === "completed" ? "ok" : String(job.status || "").toLowerCase() === "failed" ? "err" : "warn"
      )), "NO JOBS");
    }

    function setMailValue(id, value) {
      const node = el(id);
      if (document.activeElement === node) return;
      node.value = value == null ? "" : String(value);
    }

    function setProviderValue(id, value) {
      const node = el(id);
      if (document.activeElement === node) return;
      node.value = value == null ? "" : String(value);
    }

    function setSpeckleValue(id, value) {
      const node = el(id);
      if (document.activeElement === node) return;
      node.value = value == null ? "" : String(value);
    }

    function renderSpeckleSettings(settings) {
      if (state.speckleDirty) return;
      const speckle = settings.speckle || {};
      state.speckleTokenSet = Boolean(speckle.api_token_set);
      setSpeckleValue("speckleBaseUrl", speckle.base_url || "https://speckle.example.com");
      setSpeckleValue("speckleGraphqlUrl", speckle.graphql_url || "https://speckle.example.com/graphql");
      setSpeckleValue("speckleToken", "");
      setSpeckleValue("speckleSourcePath", "");
      setSpeckleValue("speckleSourceType", "");
      el("speckleToken").placeholder = speckle.api_token_set
        ? "token уже задан; оставь пустым, чтобы не менять"
        : "Speckle API token";
      setSpeckleValue("speckleTimeout", speckle.wake_timeout_sec || 5);
      el("speckleEnabled").checked = speckle.enabled !== false;
      el("speckleClear").checked = false;
      el("speckleHint").textContent =
        `CAD/BIM JSON first | Speckle ${speckle.base_url || "https://speckle.example.com"} | token=${speckle.api_token_set ? "set" : "missing"} | sources=JSON/DWG/DXF/RVT/IFC`;
    }

    function renderProviderSettings(settings) {
      if (state.providerDirty) return;
      const providers = settings.providers || {};
      const openrouter = providers.openrouter || {};
      const openai = providers.openai_compatible || {};
      state.openrouterKeySet = Boolean(openrouter.api_key_set);
      state.openaiKeySet = Boolean(openai.api_key_set);
      setProviderValue("openrouterBaseUrl", openrouter.base_url || "https://openrouter.ai/api/v1");
      setProviderValue("openrouterModel", openrouter.model || "");
      setProviderValue("openrouterKey", "");
      el("openrouterKey").placeholder = openrouter.api_key_set
        ? "key уже задан; оставь пустым, чтобы не менять"
        : "OpenRouter API key";
      el("openrouterClear").checked = false;
      setProviderValue("openaiBaseUrl", openai.base_url || "");
      setProviderValue("openaiModel", openai.model || "");
      setProviderValue("openaiKey", "");
      el("openaiKey").placeholder = openai.api_key_set
        ? "key уже задан; оставь пустым, чтобы не менять"
        : "OpenAI-compatible API key";
      el("openaiClear").checked = false;
      el("providerHint").textContent =
        `OpenRouter key=${openrouter.api_key_set ? "set" : "missing"} | OpenAI-compatible key=${openai.api_key_set ? "set" : "missing"}`;
    }

    function renderMailSettings(settings) {
      if (state.mailDirty) return;
      const mail = settings.mail || {};
      state.mailPasswordSet = Boolean(mail.imap_password_set);
      setMailValue("mailHost", mail.imap_host || "");
      setMailValue("mailPort", mail.imap_port || 993);
      setMailValue("mailSsl", mail.imap_ssl === false ? "false" : "true");
      setMailValue("mailLogin", mail.imap_login || "");
      setMailValue("mailPassword", "");
      el("mailPassword").placeholder = mail.imap_password_set
        ? "пароль уже задан; оставь пустым, чтобы не менять"
        : "пароль приложения";
      setMailValue("mailFolders", mail.imap_folders || "INBOX");
      el("mailOcr").checked = mail.attachment_ocr_enabled !== false;
      el("mailHint").textContent = mail.imap_host
        ? `IMAP ${mail.imap_host}:${mail.imap_port || 993} | login=${mail.imap_login || "-"} | password=${mail.imap_password_set ? "set" : "missing"}`
        : "IMAP не настроен. Для Яндекса используйте пароль приложения и включенный IMAP-доступ.";
    }

    function renderMemory(data) {
      const pressure = data.memory?.pressure || {};
      const mem = pressure.memory || {};
      el("memoryValue").textContent = `${mem.ram_free_gb ?? "?"} GB free`;
      el("memoryHint").textContent = pressure.reason || `swap=${mem.swap_pct ?? "?"}%`;

      const recommendations = data.memory?.recommendations || {};
      const actions = (recommendations.actions || []).map((action) => rowNode(
        action.label || action.kind || "recommendation",
        action.reason || "",
        action.kind || "INFO",
        action.kind === "wait" ? "warn" : ""
      ));
      setRows("memoryRecommendations", actions, "NO RECOMMENDATIONS");

      const preflight = data.memory?.preflight || {};
      const top = (preflight.top_processes || []).slice(0, 10);
      setRows("memoryConsumers", top.map((proc) => rowNode(
        `pid ${proc.pid} · ${Number(proc.rss_mb || 0).toFixed(0)} MB`,
        `${proc.les_owned ? "LES | " : ""}${proc.protected ? "protected | " : ""}${proc.command || ""}`,
        proc.les_owned ? "LES" : proc.protected ? "SYS" : "APP",
        proc.les_owned ? "ok" : proc.protected ? "warn" : ""
      )), "NO PROCESSES");
    }

    async function post(path, body) {
      const data = await request(path, { method: "POST", body: JSON.stringify(body || {}) });
      log(path + " -> ok");
      return data;
    }

    async function runtimeAction(action) {
      const response = await fetch("/lite-runtime/action/" + action, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "runtime action failed");
      log(action + " -> " + JSON.stringify(data.result?.message || data.result?.ok || data.result).slice(0, 180));
      await refreshAll();
    }

    async function startReindex() {
      const data = await post("/api/runtime/dispatcher/reindex/start", {});
      log("dispatcher reindex -> " + (data.status || data.reindex?.running || "ok"));
      await refreshAll();
    }

    async function pauseReindex() {
      const data = await post("/api/runtime/dispatcher/reindex/pause", { reason: "lite admin" });
      log("dispatcher pause -> " + (data.status || "requested"));
      await refreshAll();
    }

    async function resumeReindex() {
      const data = await post("/api/runtime/dispatcher/reindex/resume", {});
      log("dispatcher resume -> " + (data.status || "ok"));
      await refreshAll();
    }

    async function unloadMlx() {
      const data = await post("/api/runtime/dispatcher/mlx/unload", {});
      log("mlx unload -> " + (data.status || "ok"));
      await refreshAll();
    }

    async function checkSpeckle() {
      const data = await request("/api/speckle/status");
      const status = data.status || "unknown";
      el("speckleHint").textContent =
        `Speckle ${status} | http=${data.http_status ?? "-"} | ${data.base_url || ""} | ${data.elapsed_ms ?? "?"} ms`;
      log("speckle status -> " + status + " http=" + (data.http_status ?? "-"));
    }

    async function saveSpeckleSettings() {
      const token = el("speckleToken").value.trim();
      const payload = {
        speckle_enabled: el("speckleEnabled").checked,
        speckle_base_url: validateProviderUrl(el("speckleBaseUrl").value, "Speckle URL"),
        speckle_graphql_url: validateProviderUrl(el("speckleGraphqlUrl").value, "Speckle GraphQL URL"),
        speckle_api_token_clear: el("speckleClear").checked,
        speckle_wake_timeout_sec: Number(el("speckleTimeout").value || 5),
      };
      if (token) payload.speckle_api_token = token;
      const data = await post("/api/settings", payload);
      state.speckleDirty = false;
      el("speckleToken").value = "";
      log("speckle settings -> " + Object.keys(data.updated || {}).join(", "));
      await refreshAll();
    }

    async function importSpeckleGraph() {
      const sourcePath = el("speckleSourcePath").value.trim();
      const payload = { max_objects: 5000 };
      if (sourcePath) payload.source_path = sourcePath;
      const sourceType = el("speckleSourceType").value.trim();
      if (sourceType) payload.source_type = sourceType;
      const data = await post("/api/cad-bim/import", payload);
      log("cad/bim json import -> profile=" + (data.profile || "auto") + " elements=" + (data.elements || 0) + " relations=" + (data.relations || 0) + " properties=" + (data.properties || 0));
      el("speckleHint").textContent =
        `Imported ${data.profile || "auto"} | ${data.elements || 0} elements / ${data.relations || 0} relations / ${data.properties || 0} properties | ${data.projection_path || ""}`;
    }

    async function loadCadBimViewer() {
      const sourcePath = el("speckleSourcePath").value.trim();
      const params = new URLSearchParams({ max_elements: "5000" });
      if (sourcePath) params.set("source_path", sourcePath);
      const data = await request("/api/cad-bim/source?" + params.toString());
      state.cadBimViewerPayload = data.payload || null;
      renderCadBimViewer(data);
      log("cad/bim viewer -> " + (data.source || "latest") + " elements=" + (data.element_count || 0));
    }

    function openCadBimObcViewer() {
      const sourcePath = el("speckleSourcePath").value.trim();
      const params = new URLSearchParams();
      if (sourcePath) params.set("source_path", sourcePath);
      const query = params.toString();
      window.open("/les/cad-bim-viewer/" + (query ? "?" + query : ""), "_blank", "noopener");
    }

    function renderCadBimViewer(data) {
      const payload = data.payload || state.cadBimViewerPayload || {};
      const mode = el("cadBimViewMode").value || "auto";
      const elements = graphElements(payload);
      const relations = graphRelations(payload);
      const drawables = elements.map(drawableFromElement).filter(Boolean);
      const layers = layerCounts(elements);
      const useGraph = mode === "graph" || (mode === "auto" && drawables.length === 0);
      drawCadBimCanvas(useGraph ? [] : drawables, useGraph ? elements : [], relations);
      el("cadBimViewerHint").textContent =
        `${useGraph ? "GRAPH" : "2D"} | source=${data.source || "-"} | elements=${fmt(data.element_count || elements.length)}${data.truncated ? " | truncated" : ""}`;
      setRows("cadBimViewerStats", [
        rowNode("Elements", fmt(elements.length), "JSON", "ok"),
        rowNode("Drawable", fmt(drawables.length), useGraph ? "GRAPH" : "2D", drawables.length ? "ok" : "warn"),
        rowNode("Relations", fmt(relations.length), "LINKS", relations.length ? "ok" : ""),
      ]);
      setRows("cadBimViewerLayers", Object.entries(layers).slice(0, 24).map(([name, count]) => (
        rowNode(name || "-", fmt(count) + " elements", "LAYER", "")
      )), "NO LAYERS");
    }

    function graphElements(payload) {
      if (Array.isArray(payload)) return payload.filter((item) => item && typeof item === "object");
      if (!payload || typeof payload !== "object") return [];
      const root = payload.id ? [payload] : [];
      const elements = Array.isArray(payload.elements) ? payload.elements : [];
      return root.concat(elements).filter((item) => item && typeof item === "object");
    }

    function graphRelations(payload) {
      if (!payload || typeof payload !== "object" || !Array.isArray(payload.relations)) return [];
      return payload.relations.filter((item) => item && typeof item === "object");
    }

    function layerCounts(elements) {
      const out = {};
      for (const element of elements) {
        if (isModelRoot(element)) continue;
        const layer = element.layer || element.category || element.level || element.family || "default";
        out[layer] = (out[layer] || 0) + 1;
      }
      return out;
    }

    function isModelRoot(element) {
      const type = String(element.type || element.object_type || "").toLowerCase();
      return type.endsWith("model") || Boolean(element.source_format && Array.isArray(element.elements));
    }

    function drawableFromElement(element) {
      if (!element || isModelRoot(element)) return null;
      const props = element.properties || {};
      const layer = element.layer || element.category || element.level || "default";
      const name = element.name || element.type || element.id || "";
      const common = { id: element.id || "", layer, name, type: element.type || element.object_type || "" };
      if (point2(props.start) && point2(props.end)) return { ...common, kind: "line", start: point2(props.start), end: point2(props.end) };
      if (Array.isArray(props.points_preview) && props.points_preview.length) {
        return { ...common, kind: "polyline", points: props.points_preview.map(point2).filter(Boolean), closed: Boolean(props.closed) };
      }
      if (point2(props.center) && Number(props.radius) > 0) {
        return { ...common, kind: "circle", center: point2(props.center), radius: Number(props.radius), startAngle: Number(props.start_angle), endAngle: Number(props.end_angle) };
      }
      if (point2(props.insert)) return { ...common, kind: "point", point: point2(props.insert), text: props.text || name };
      if (point2(props.bbox_min) && point2(props.bbox_max)) return { ...common, kind: "bbox", min: point2(props.bbox_min), max: point2(props.bbox_max) };
      return null;
    }

    function point2(value) {
      if (!Array.isArray(value) || value.length < 2) return null;
      const x = Number(value[0]);
      const y = Number(value[1]);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
      return [x, y];
    }

    function drawableBounds(drawables) {
      const xs = [];
      const ys = [];
      const add = (point) => { xs.push(point[0]); ys.push(point[1]); };
      for (const item of drawables) {
        if (item.kind === "line") { add(item.start); add(item.end); }
        else if (item.kind === "polyline") item.points.forEach(add);
        else if (item.kind === "circle") { add([item.center[0] - item.radius, item.center[1] - item.radius]); add([item.center[0] + item.radius, item.center[1] + item.radius]); }
        else if (item.kind === "bbox") { add(item.min); add(item.max); }
        else if (item.kind === "point") add(item.point);
      }
      if (!xs.length) return null;
      return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
    }

    function drawCadBimCanvas(drawables, graphNodes, relations) {
      const canvas = el("cadBimCanvas");
      const ctx = canvas.getContext("2d");
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(320, Math.floor(rect.width * dpr));
      canvas.height = Math.max(240, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#05070a";
      ctx.fillRect(0, 0, width, height);
      drawGrid(ctx, width, height);
      if (drawables.length) drawGeometry(ctx, drawables, width, height);
      else drawGraph(ctx, graphNodes, relations, width, height);
    }

    function drawGrid(ctx, width, height) {
      ctx.strokeStyle = "rgba(38,55,72,.35)";
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 40) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      }
      for (let y = 0; y < height; y += 40) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
      }
    }

    function layerColor(layer) {
      const palette = ["#38bdf8", "#22c55e", "#f59e0b", "#ef4444", "#a78bfa", "#14b8a6", "#f97316", "#e879f9"];
      let hash = 0;
      const text = String(layer || "");
      for (let i = 0; i < text.length; i++) hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
      return palette[Math.abs(hash) % palette.length];
    }

    function drawGeometry(ctx, drawables, width, height) {
      const bounds = drawableBounds(drawables);
      if (!bounds) return;
      const margin = 28;
      const spanX = Math.max(1, bounds.maxX - bounds.minX);
      const spanY = Math.max(1, bounds.maxY - bounds.minY);
      const scale = Math.min((width - margin * 2) / spanX, (height - margin * 2) / spanY);
      const tx = (point) => margin + (point[0] - bounds.minX) * scale;
      const ty = (point) => height - margin - (point[1] - bounds.minY) * scale;
      ctx.font = "11px ui-monospace, monospace";
      for (const item of drawables) {
        ctx.strokeStyle = layerColor(item.layer);
        ctx.fillStyle = layerColor(item.layer);
        ctx.lineWidth = 1.6;
        if (item.kind === "line") {
          ctx.beginPath(); ctx.moveTo(tx(item.start), ty(item.start)); ctx.lineTo(tx(item.end), ty(item.end)); ctx.stroke();
        } else if (item.kind === "polyline") {
          ctx.beginPath();
          item.points.forEach((point, index) => index ? ctx.lineTo(tx(point), ty(point)) : ctx.moveTo(tx(point), ty(point)));
          if (item.closed) ctx.closePath();
          ctx.stroke();
        } else if (item.kind === "circle") {
          ctx.beginPath(); ctx.arc(tx(item.center), ty(item.center), Math.max(2, item.radius * scale), 0, Math.PI * 2); ctx.stroke();
        } else if (item.kind === "bbox") {
          const x = tx(item.min);
          const y = ty(item.max);
          ctx.strokeRect(x, y, Math.max(2, (item.max[0] - item.min[0]) * scale), Math.max(2, (item.max[1] - item.min[1]) * scale));
        } else if (item.kind === "point") {
          const x = tx(item.point);
          const y = ty(item.point);
          ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
          if (item.text) ctx.fillText(String(item.text).slice(0, 42), x + 5, y - 5);
        }
      }
    }

    function drawGraph(ctx, nodes, relations, width, height) {
      const visible = nodes.slice(0, 160);
      if (!visible.length) {
        ctx.fillStyle = "#9fb0c1";
        ctx.font = "12px ui-monospace, monospace";
        ctx.fillText("NO CAD/BIM JSON", 24, 34);
        return;
      }
      const ids = new Map();
      visible.forEach((node, index) => ids.set(String(node.id || index), index));
      const centerX = width / 2;
      const centerY = height / 2;
      const radius = Math.max(60, Math.min(width, height) * .36);
      const pos = visible.map((node, index) => {
        if (index === 0) return [centerX, centerY];
        const angle = ((index - 1) / Math.max(1, visible.length - 1)) * Math.PI * 2;
        return [centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius];
      });
      ctx.strokeStyle = "rgba(159,176,193,.34)";
      ctx.lineWidth = 1;
      for (const rel of relations.slice(0, 400)) {
        const source = ids.get(String(rel.source_id || rel.sourceId || rel.from || ""));
        const target = ids.get(String(rel.target_id || rel.targetId || rel.to || ""));
        if (source == null || target == null) continue;
        ctx.beginPath(); ctx.moveTo(pos[source][0], pos[source][1]); ctx.lineTo(pos[target][0], pos[target][1]); ctx.stroke();
      }
      ctx.font = "10px ui-monospace, monospace";
      visible.forEach((node, index) => {
        const category = node.layer || node.category || node.level || node.family || node.type || "node";
        ctx.fillStyle = layerColor(category);
        ctx.beginPath(); ctx.arc(pos[index][0], pos[index][1], index === 0 ? 7 : 4, 0, Math.PI * 2); ctx.fill();
        if (index < 30) {
          ctx.fillStyle = "#cbd5e1";
          ctx.fillText(String(node.name || node.type || node.id || "").slice(0, 28), pos[index][0] + 6, pos[index][1] - 6);
        }
      });
    }

    async function syncCadBim() {
      const data = await post("/api/rag/sync-smart", {
        source_root: "RAG_Content/CAD_BIM",
        parse: false,
        parse_limit_per_dataset: 1,
      });
      log("cad/bim sync -> files=" + (data.files || 0) + " datasets=" + (data.datasets || []).length);
      await refreshAll();
    }

    function validateProviderUrl(value, label) {
      const url = value.trim();
      if (url && !url.startsWith("http://") && !url.startsWith("https://")) {
        throw new Error(label + " должен начинаться с http:// или https://");
      }
      return url;
    }

    async function saveProviderSettings() {
      const openrouterKey = el("openrouterKey").value.trim();
      const openaiKey = el("openaiKey").value.trim();
      const payload = {
        openrouter_base_url: validateProviderUrl(el("openrouterBaseUrl").value, "OpenRouter URL"),
        openrouter_model: el("openrouterModel").value.trim(),
        openrouter_api_key_clear: el("openrouterClear").checked,
        openai_base_url: validateProviderUrl(el("openaiBaseUrl").value, "OpenAI-compatible URL"),
        openai_model: el("openaiModel").value.trim(),
        openai_api_key_clear: el("openaiClear").checked,
      };
      if (openrouterKey) payload.openrouter_api_key = openrouterKey;
      if (openaiKey) payload.openai_api_key = openaiKey;
      const data = await post("/api/settings", payload);
      state.providerDirty = false;
      el("openrouterKey").value = "";
      el("openaiKey").value = "";
      log("provider settings -> " + Object.keys(data.updated || {}).join(", "));
      await refreshAll();
    }

    function applyYandexMailPreset() {
      el("mailHost").value = "imap.yandex.ru";
      el("mailPort").value = "993";
      el("mailSsl").value = "true";
      if (!el("mailFolders").value.trim()) el("mailFolders").value = "INBOX";
      state.mailDirty = true;
      el("mailHint").textContent = "Yandex preset: imap.yandex.ru:993 SSL. Введите login и пароль приложения.";
    }

    function validateMailSettings() {
      const host = el("mailHost").value.trim();
      const login = el("mailLogin").value.trim();
      const password = el("mailPassword").value.trim();
      if (!host) throw new Error("Укажите IMAP host. Для Яндекса нажмите YANDEX PRESET.");
      if (!login) throw new Error("Укажите IMAP login.");
      if (!password && !state.mailPasswordSet) throw new Error("Укажите пароль приложения.");
    }

    async function saveMailSettings() {
      validateMailSettings();
      const password = el("mailPassword").value.trim();
      const payload = {
        mail_imap_host: el("mailHost").value.trim(),
        mail_imap_port: Number(el("mailPort").value || 993),
        mail_imap_ssl: el("mailSsl").value !== "false",
        mail_imap_login: el("mailLogin").value.trim(),
        mail_imap_folders: el("mailFolders").value.trim() || "INBOX",
        mail_attachment_ocr_enabled: el("mailOcr").checked,
      };
      if (password) payload.mail_imap_password = password;
      const data = await post("/api/settings", payload);
      state.mailDirty = false;
      el("mailPassword").value = "";
      state.mailPasswordSet = true;
      log("mail settings -> " + Object.keys(data.updated || {}).join(", "));
      await refreshAll();
    }

    async function importMail() {
      if (state.mailDirty) await saveMailSettings();
      else validateMailSettings();
      const maxMessages = Math.min(200, Math.max(1, Number(el("mailCount").value || 50)));
      el("mailCount").value = String(maxMessages);
      const parseLimit = 25;
      const parseBatches = Math.min(20, Math.max(1, Math.ceil(maxMessages / parseLimit)));
      const data = await post("/api/mail/import-imap", {
        background: true,
        max_messages: maxMessages,
        parse: true,
        parse_limit: parseLimit,
        parse_batches: parseBatches,
      });
      const parsed = data.parse_result?.files_parsed ?? 0;
      const chunks = data.parse_result?.chunks ?? 0;
      log("mail import -> " + (data.status || "ok") + " job=" + (data.job_id || "-") + " files=" + (data.files || 0) + " parsed=" + parsed + " chunks=" + chunks);
      await refreshAll();
    }

    async function importAppleMail() {
      const data = await post("/api/mail/import-apple-mail", { max_messages: 10, parse: false });
      log("apple mail import -> " + (data.status || "ok") + " files=" + (data.files || 0));
      await refreshAll();
    }

    el("refreshBtn").addEventListener("click", refreshAll);
    el("loginBtn").addEventListener("click", login);
    el("keyInput").addEventListener("keydown", (event) => { if (event.key === "Enter") login(); });
    ["mailHost", "mailPort", "mailSsl", "mailLogin", "mailPassword", "mailFolders", "mailOcr"].forEach((id) => {
      el(id).addEventListener("input", () => { state.mailDirty = true; });
      el(id).addEventListener("change", () => { state.mailDirty = true; });
    });
    ["openrouterBaseUrl", "openrouterModel", "openrouterKey", "openrouterClear", "openaiBaseUrl", "openaiModel", "openaiKey", "openaiClear"].forEach((id) => {
      el(id).addEventListener("input", () => { state.providerDirty = true; });
      el(id).addEventListener("change", () => { state.providerDirty = true; });
    });
    ["speckleBaseUrl", "speckleGraphqlUrl", "speckleToken", "speckleSourcePath", "speckleSourceType", "speckleTimeout", "speckleEnabled", "speckleClear"].forEach((id) => {
      el(id).addEventListener("input", () => { state.speckleDirty = true; });
      el(id).addEventListener("change", () => { state.speckleDirty = true; });
    });
    el("speckleSaveBtn").addEventListener("click", async () => {
      try { await saveSpeckleSettings(); }
      catch (error) { log("speckle settings error: " + error.message); }
    });
    el("speckleCheckBtn").addEventListener("click", async () => {
      try { await checkSpeckle(); }
      catch (error) { log("speckle status error: " + error.message); }
    });
    el("speckleImportBtn").addEventListener("click", async () => {
      try { await importSpeckleGraph(); }
      catch (error) { log("speckle import error: " + error.message); }
    });
    el("cadBimSyncBtn").addEventListener("click", async () => {
      try { await syncCadBim(); }
      catch (error) { log("cad/bim sync error: " + error.message); }
    });
    el("cadBimViewBtn").addEventListener("click", async () => {
      try { await loadCadBimViewer(); }
      catch (error) { log("cad/bim viewer error: " + error.message); }
    });
    el("cadBimObcViewBtn").addEventListener("click", () => {
      try { openCadBimObcViewer(); }
      catch (error) { log("cad/bim obc viewer error: " + error.message); }
    });
    el("cadBimViewMode").addEventListener("change", () => {
      if (state.cadBimViewerPayload) renderCadBimViewer({ payload: state.cadBimViewerPayload });
    });
    el("providerSaveBtn").addEventListener("click", async () => {
      try { await saveProviderSettings(); }
      catch (error) { log("provider settings error: " + error.message); }
    });
    el("mailYandexBtn").addEventListener("click", applyYandexMailPreset);
    el("mailSaveBtn").addEventListener("click", async () => {
      try { await saveMailSettings(); }
      catch (error) { log("mail settings error: " + error.message); }
    });
    el("mailImportBtn").addEventListener("click", async () => {
      try { await importMail(); }
      catch (error) { log("mail import error: " + error.message); }
    });
    el("mailAppleBtn").addEventListener("click", async () => {
      try { await importAppleMail(); }
      catch (error) { log("apple mail import error: " + error.message); }
    });
    el("unloadMlxBtn").addEventListener("click", async () => {
      try { await unloadMlx(); }
      catch (error) { log("mlx unload error: " + error.message); }
    });
    el("startReindexBtn").addEventListener("click", async () => {
      try { await startReindex(); }
      catch (error) { log("dispatcher start error: " + error.message); }
    });
    el("pauseReindexBtn").addEventListener("click", async () => {
      try { await pauseReindex(); }
      catch (error) { log("dispatcher pause error: " + error.message); }
    });
    el("resumeReindexBtn").addEventListener("click", async () => {
      try { await resumeReindex(); }
      catch (error) { log("dispatcher resume error: " + error.message); }
    });
    (async () => {
      await bootstrapTrustedAccess();
      await refreshAll();
      setInterval(refreshAll, 20000);
    })();
  </script>
</body>
</html>"""


def register_lite_admin_routes() -> None:
    from nicegui import app

    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/javascript", ".mjs")
    viewer_dist = _repo_root() / "frontend" / "cad_bim_viewer" / "dist"
    ifc_sample_dir = _repo_root() / "ifc_sample"
    app.mount(
        "/les/cad-bim-viewer/assets",
        StaticFiles(directory=viewer_dist / "assets", check_dir=False),
        name="les_cad_bim_viewer_assets",
    )
    app.mount(
        "/les/cad-bim-viewer/web-ifc",
        StaticFiles(directory=viewer_dist / "web-ifc", check_dir=False),
        name="les_cad_bim_viewer_web_ifc",
    )
    app.mount(
        "/les/cad-bim-viewer/fragments",
        StaticFiles(directory=viewer_dist / "fragments", check_dir=False),
        name="les_cad_bim_viewer_fragments",
    )
    app.mount(
        "/les/cad-bim-viewer/ifc-sample",
        StaticFiles(directory=ifc_sample_dir, check_dir=False),
        name="les_cad_bim_viewer_ifc_sample",
    )

    @app.get("/les")
    @app.get("/les/")
    async def lite_admin_page():
        return HTMLResponse(
            lite_admin_html(),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/les/cad-bim-viewer")
    @app.get("/les/cad-bim-viewer/")
    async def cad_bim_viewer_page():
        index = viewer_dist / "index.html"
        if index.exists():
            return FileResponse(
                index,
                media_type="text/html",
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
        return HTMLResponse(
            """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LES VIZOR</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #07090c; color: #f4f7fb; font: 14px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    main { width: min(680px, calc(100vw - 32px)); border: 1px solid #263748; border-radius: 8px; background: #10161d; padding: 22px; }
    h1 { margin: 0 0 10px; font-size: 18px; }
    p { color: #9fb0c1; line-height: 1.55; }
    code { color: #38bdf8; }
  </style>
</head>
<body>
  <main>
    <h1>LES VIZOR не собран</h1>
    <p>Соберите frontend bundle:</p>
    <p><code>cd frontend/cad_bim_viewer && npm install && npm run build</code></p>
  </main>
</body>
</html>""",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/lite-runtime/status")
    async def lite_runtime_status_page(request: Request):
        return await lite_runtime_status(request)

    @app.get("/lite-runtime/reindex-status")
    async def lite_reindex_status_page(request: Request):
        return await lite_reindex_status(request)

    @app.post("/lite-runtime/action/{action}")
    async def lite_runtime_action_page(action: str, request: Request):
        return await lite_runtime_action(action, request)
