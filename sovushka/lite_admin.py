"""Lightweight static admin shell for Sovushka.

The default admin route should be cheap to open while memory is under pressure.
The richer NiceGUI console remains available at /les/classic.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Callable

from fastapi import Request
from starlette.responses import HTMLResponse, JSONResponse

from sovushka.lite_chat import _client_is_loopback


LOCAL_RUNTIME_ACTIONS = {
    "start_indexer",
    "stop_indexer",
    "restart_proxy",
    "restart_mlx",
    "restart_qdrant",
    "restart_ui",
}


def local_runtime_action_allowed(*, is_loopback: bool) -> bool:
    return is_loopback


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


async def lite_runtime_status(request: Request) -> JSONResponse:
    if not local_runtime_action_allowed(is_loopback=_client_is_loopback(request)):
        return JSONResponse({"detail": "Local runtime status requires loopback access"}, status_code=403)

    from tools import les_runtime_control

    statuses = await asyncio.to_thread(
        les_runtime_control.all_statuses,
        ["qdrant", "mlx", "proxy", "indexer", "ui"],
    )
    return JSONResponse({"services": _runtime_result_payload(statuses)})


async def lite_runtime_action(action: str, request: Request) -> JSONResponse:
    if action not in LOCAL_RUNTIME_ACTIONS:
        return JSONResponse({"detail": f"Unknown action: {action}"}, status_code=404)
    if not local_runtime_action_allowed(is_loopback=_client_is_loopback(request)):
        return JSONResponse({"detail": "Local runtime actions require loopback access"}, status_code=403)

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
    button, input { font: inherit; }
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
    input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: rgba(7, 9, 12, .72);
      color: var(--text);
      padding: 8px 10px;
      outline: none;
      font-size: .76rem;
    }
    @media (max-width: 1020px) {
      .layout { grid-template-columns: 1fr; }
      .side { position: static; }
      .grid { grid-template-columns: 1fr; }
      .panel-wide { grid-column: span 1; }
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
      <div class="panel">
        <div class="title">Файлы</div>
        <div id="filesValue" class="value">...</div>
        <div id="filesHint" class="hint"></div>
      </div>
      <div class="panel">
        <div class="title">Chunks</div>
        <div id="chunksValue" class="value">...</div>
        <div id="qdrantHint" class="hint"></div>
      </div>
      <div class="panel">
        <div class="title">Память</div>
        <div id="memoryValue" class="value">...</div>
        <div id="memoryHint" class="hint"></div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Pending / Errors</div>
        <div id="pendingList" class="hint">Загрузка...</div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Datasets</div>
        <div id="datasetList" class="hint">Загрузка...</div>
      </div>

      <div class="panel panel-wide">
        <div class="title">Jobs</div>
        <div id="jobsList" class="hint">Загрузка...</div>
      </div>
    </section>

    <aside class="side">
      <div class="panel">
        <div class="title">Runtime</div>
        <div id="runtimeList" class="hint">Локальный статус доступен только с localhost.</div>
        <div class="actions">
          <button id="refreshBtn" type="button">ОБНОВИТЬ</button>
          <a class="linkbtn" href="/">ЧАТ</a>
          <a class="linkbtn" href="/classic">CLASSIC CHAT</a>
          <a class="linkbtn" href="/les/classic">CLASSIC ADMIN</a>
        </div>
      </div>

      <div class="panel">
        <div class="title">Memory Actions</div>
        <div class="actions">
          <button id="chatModeBtn" type="button" class="safe">CHAT MODE</button>
          <button id="indexModeBtn" type="button">INDEX LIGHT</button>
          <button id="parseOneBtn" type="button">PARSE 1</button>
        </div>
        <div class="hint">`PARSE 1` запускает один guarded batch. Heavy PDF всё равно должен идти через ручной профиль.</div>
      </div>

      <div class="panel">
        <div class="title">Local Launchd</div>
        <div class="actions">
          <button data-runtime="stop_indexer" type="button" class="danger">STOP INDEXER</button>
          <button data-runtime="start_indexer" type="button">START INDEXER</button>
          <button data-runtime="restart_proxy" type="button">RESTART PROXY</button>
          <button data-runtime="restart_mlx" type="button">RESTART MLX</button>
          <button data-runtime="restart_qdrant" type="button">RESTART QDRANT</button>
        </div>
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
      <div class="hint">Введите admin key. На localhost trusted-доступ может открыться без ключа.</div>
      <div style="height:12px"></div>
      <input id="keyInput" type="password" placeholder="les_xxxxxxxxxxxxxxxx">
      <div style="height:10px"></div>
      <button id="loginBtn" type="button">ВОЙТИ</button>
      <div id="authError" class="hint" style="color:var(--err);min-height:18px;margin-top:8px"></div>
    </div>
  </div>

  <script>
    const isLocalUi = ["localhost", "127.0.0.1", "::1"].includes(location.hostname) && location.port === "8051";
    const API_BASE = isLocalUi ? "/lite-api" : "";
    const KEY_STORAGE = "les_lite_api_key";
    const ROLE_STORAGE = "les_lite_role";
    const HOLDER_STORAGE = "les_lite_holder";
    const state = {
      key: localStorage.getItem(KEY_STORAGE) || "",
      role: localStorage.getItem(ROLE_STORAGE) || "",
      holder: localStorage.getItem(HOLDER_STORAGE) || "",
      busy: false,
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

    function row(name, meta, badge, cls = "") {
      return `<div class="row"><div class="row-main"><div class="row-name">${escapeHtml(name)}</div><div class="row-meta">${escapeHtml(meta || "")}</div></div><span class="chip ${cls}">${escapeHtml(badge || "")}</span></div>`;
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
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
        const [status, mode, jobs, pending, datasets] = await Promise.all([
          request("/api/health"),
          request("/api/indexing-mode"),
          request("/api/jobs/summary"),
          request("/api/rag/documents?status=PENDING&limit=10"),
          request("/api/rag/datasets"),
        ]);
        showAuth(false);
        renderStatus(status, mode);
        renderJobs(jobs);
        renderPending(pending);
        renderDatasets(datasets);
        await refreshLocalRuntime();
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

    function renderStatus(status, mode) {
      const rag = status.rag || {};
      const totals = rag.totals || {};
      const qdrant = rag.qdrant || {};
      const memory = mode.memory_state || {};
      const mem = memory.memory || {};
      const admission = mode.chat_admission || {};
      const profile = mode.runtime_profile || "?";
      const memState = memory.state || "?";
      chip("authChip", state.key ? (state.role || "KEY") : "TRUSTED", "ok");
      chip("profileChip", profile, admission.allowed === false ? "err" : "ok");
      chip("memoryChip", memState, memState === "GREEN" ? "ok" : memState === "YELLOW" ? "warn" : "err");
      chip("jobsChip", (admission.active_jobs || 0) + " JOBS", admission.active_jobs ? "warn" : "ok");
      el("filesValue").textContent = fmt(totals.indexed_files) + " / " + fmt(totals.files);
      el("filesHint").textContent = `pending=${fmt(totals.pending_files)} errors=${fmt(totals.error_files)} status=${rag.status || status.status || "?"}`;
      el("chunksValue").textContent = fmt(totals.chunks);
      el("qdrantHint").textContent = `qdrant=${fmt(qdrant.points)} match=${qdrant.points_match_sqlite_chunks !== false}`;
      el("memoryValue").textContent = `${mem.ram_free_gb ?? "?"} GB`;
      el("memoryHint").textContent = memory.reason || `swap=${mem.swap_pct ?? "?"}%`;
    }

    function renderPending(data) {
      const docs = data.documents || [];
      if (!docs.length) {
        el("pendingList").innerHTML = '<span class="chip ok">NO PENDING</span>';
        return;
      }
      el("pendingList").innerHTML = docs.map((doc) => row(
        doc.file_name,
        `${doc.dataset_name} | ${doc.doc_type || ""} | ${doc.complexity || ""} | ${(doc.file_size / 1024 / 1024).toFixed(1)} MB`,
        doc.status,
        doc.complexity === "heavy" ? "warn" : ""
      )).join("");
    }

    function renderDatasets(items) {
      const rows = (items || []).slice().sort((a, b) => (b.chunk_count || 0) - (a.chunk_count || 0));
      el("datasetList").innerHTML = rows.map((ds) => row(
        ds.name,
        `${fmt(ds.doc_count)} files | ${fmt(ds.chunk_count)} chunks`,
        ds.status,
        ds.status === "COMPLETED" ? "ok" : ds.status === "IDLE" ? "warn" : "err"
      )).join("");
    }

    function renderJobs(data) {
      const jobs = (data.jobs || []).slice(0, 8);
      if (!jobs.length) {
        el("jobsList").innerHTML = '<span class="chip ok">NO JOBS</span>';
        return;
      }
      el("jobsList").innerHTML = jobs.map((job) => row(
        `${job.type || "job"} ${job.id || ""}`,
        job.message || "",
        job.status || "",
        job.status === "completed" ? "ok" : job.status === "failed" ? "err" : "warn"
      )).join("");
    }

    async function refreshLocalRuntime() {
      try {
        const response = await fetch("/lite-runtime/status");
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "runtime unavailable");
        el("runtimeList").innerHTML = (data.services || []).map((svc) => row(
          svc.title || svc.key,
          `${svc.label || ""} | pid ${svc.pid || svc.port_pid || "-"} | :${svc.port || "-"}`,
          svc.health || (svc.running ? "UP" : "DOWN"),
          svc.running && svc.health === "ok" ? "ok" : svc.running ? "warn" : "err"
        )).join("");
      } catch (error) {
        el("runtimeList").textContent = error.message;
      }
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
      await refreshLocalRuntime();
    }

    el("refreshBtn").addEventListener("click", refreshAll);
    el("loginBtn").addEventListener("click", login);
    el("keyInput").addEventListener("keydown", (event) => { if (event.key === "Enter") login(); });
    el("chatModeBtn").addEventListener("click", async () => {
      await post("/api/indexing-mode", { enabled: false, reason: "lite admin", unload_models: true });
      await refreshAll();
    });
    el("indexModeBtn").addEventListener("click", async () => {
      await post("/api/indexing-mode", { enabled: true, reason: "lite admin", unload_models: true });
      await refreshAll();
    });
    el("parseOneBtn").addEventListener("click", async () => {
      await post("/api/rag/parse-scheduler", {
        batch_limit: 1,
        max_batches: 1,
        cooldown_sec: 0,
        unload_before_start: true,
        unload_between_batches: true,
        unload_after_finish: true,
        warm_embedder: false,
        stop_on_error: true,
        background: true
      });
      await refreshAll();
    });
    for (const button of document.querySelectorAll("[data-runtime]")) {
      button.addEventListener("click", async () => {
        try { await runtimeAction(button.dataset.runtime); }
        catch (error) { log(button.dataset.runtime + " error: " + error.message); }
      });
    }

    refreshAll();
    setInterval(refreshAll, 20000);
  </script>
</body>
</html>"""


def register_lite_admin_routes() -> None:
    from nicegui import app

    @app.get("/les")
    @app.get("/les/")
    async def lite_admin_page():
        return HTMLResponse(lite_admin_html())

    @app.get("/lite-runtime/status")
    async def lite_runtime_status_page(request: Request):
        return await lite_runtime_status(request)

    @app.post("/lite-runtime/action/{action}")
    async def lite_runtime_action_page(action: str, request: Request):
        return await lite_runtime_action(action, request)
