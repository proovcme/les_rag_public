"""Lightweight static chat shell for Sovushka.

The root chat should not mount a NiceGUI component tree. NiceGUI stays available
for the admin console and the legacy rich chat at /classic.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable

import httpx
from fastapi import Request, Response
from starlette.responses import HTMLResponse, JSONResponse

from sovushka.config import PROXY_URL
from sovushka.trust import trusted_role_for_request


BRIDGE_PUBLIC_PATHS = {"/api/auth/verify"}


def _client_is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else "127.0.0.1"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def bridge_request_allowed(
    path: str,
    *,
    has_key: bool,
    is_loopback: bool,
    is_trusted_network: bool = False,
) -> bool:
    target_path = f"/api/{path.strip('/')}"
    return has_key or is_loopback or is_trusted_network or target_path in BRIDGE_PUBLIC_PATHS


def _forward_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": request.headers.get("accept", "application/json")}
    content_type = request.headers.get("content-type")
    api_key = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization")
    if content_type:
        headers["Content-Type"] = content_type
    if api_key:
        headers["X-API-Key"] = api_key
    if authorization:
        headers["Authorization"] = authorization
    return headers


async def bridge_proxy_request(path: str, request: Request) -> Response:
    has_key = bool(request.headers.get("x-api-key") or request.headers.get("authorization"))
    is_loopback = _client_is_loopback(request)
    is_trusted_network = bool(trusted_role_for_request(request))
    if not bridge_request_allowed(
        path,
        has_key=has_key,
        is_loopback=is_loopback,
        is_trusted_network=is_trusted_network,
    ):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    target_path = f"/api/{path.strip('/')}"
    query = f"?{request.url.query}" if request.url.query else ""
    target_url = f"{PROXY_URL.rstrip('/')}{target_path}{query}"
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            proxied = await client.request(
                request.method,
                target_url,
                content=body or None,
                headers=_forward_headers(request),
            )
    except httpx.RequestError as error:
        return JSONResponse({"detail": f"Proxy unavailable: {error}"}, status_code=502)

    content_type = proxied.headers.get("content-type", "application/json")
    return Response(content=proxied.content, status_code=proxied.status_code, media_type=content_type)


def lite_chat_html() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Л.Е.С. Lite Chat</title>
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
    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      overflow: hidden;
    }
    button, input, textarea {
      font: inherit;
    }
    .shell {
      height: 100vh;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      background: linear-gradient(180deg, #0b1016, #07090c 38%);
    }
    .topbar {
      min-height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(16, 22, 29, .96);
    }
    .brand {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
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
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      flex-wrap: wrap;
    }
    .chip {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 4px 8px;
      color: var(--dim);
      background: rgba(7, 9, 12, .35);
      font-size: .58rem;
      font-weight: 800;
      white-space: nowrap;
    }
    .chip-ok { color: var(--ok); border-color: rgba(34, 197, 94, .45); }
    .chip-warn { color: var(--warn); border-color: rgba(245, 158, 11, .45); }
    .chip-err { color: var(--err); border-color: rgba(239, 68, 68, .45); }
    .main {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 300px;
      gap: 12px;
      padding: 12px;
    }
    .messages {
      min-height: 0;
      overflow-y: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(16, 22, 29, .72);
      padding: 14px;
    }
    .side {
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(16, 22, 29, .72);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      overflow: auto;
    }
    .msg {
      max-width: min(920px, 92%);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      margin: 0 0 10px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.48;
      font-size: .86rem;
    }
    .msg-user {
      margin-left: auto;
      background: rgba(56, 189, 248, .08);
      border-right: 3px solid var(--accent);
    }
    .msg-ai {
      margin-right: auto;
      background: rgba(7, 9, 12, .4);
      border-left: 3px solid var(--ok);
    }
    .msg-sys {
      margin: 0 auto 10px;
      color: var(--dim);
      border-style: dashed;
      background: transparent;
      text-align: center;
      font-size: .72rem;
    }
    .sources {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 8px;
    }
    .source {
      border: 1px solid rgba(56, 189, 248, .35);
      color: var(--accent);
      border-radius: 5px;
      padding: 2px 6px;
      font-size: .58rem;
    }
    .feedback {
      display: flex;
      align-items: center;
      gap: 5px;
      margin-top: 8px;
      flex-wrap: wrap;
    }
    .feedback button {
      width: 30px;
      min-height: 28px;
      padding: 0;
      border-radius: 6px;
      font-size: .62rem;
      line-height: 1;
    }
    .feedback button:disabled { cursor: default; opacity: .75; }
    .feedback button.bad-answer {
      width: auto;
      min-width: 116px;
      padding: 0 10px;
      color: var(--err);
      border-color: rgba(239, 68, 68, .55);
      background: rgba(239, 68, 68, .1);
      font-weight: 700;
    }
    .feedback-status {
      color: var(--muted);
      font-size: .58rem;
      min-width: 80px;
    }
    .composer {
      border-top: 1px solid var(--line);
      background: rgba(16, 22, 29, .96);
      padding: 10px 12px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }
    textarea {
      width: 100%;
      min-height: 58px;
      max-height: 180px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(7, 9, 12, .72);
      color: var(--text);
      padding: 10px 12px;
      outline: none;
    }
    textarea:focus, input:focus {
      border-color: var(--accent);
    }
    button {
      min-height: 38px;
      border: 1px solid rgba(56, 189, 248, .45);
      border-radius: 7px;
      color: var(--accent);
      background: rgba(56, 189, 248, .08);
      padding: 8px 12px;
      cursor: pointer;
      font-weight: 900;
      font-size: .72rem;
    }
    button:hover { background: rgba(56, 189, 248, .16); }
    button:disabled { opacity: .5; cursor: wait; }
    .section {
      border-bottom: 1px solid rgba(38, 55, 72, .65);
      padding-bottom: 10px;
    }
    .section:last-child { border-bottom: 0; }
    .section-title {
      color: var(--dim);
      text-transform: uppercase;
      font-size: .58rem;
      font-weight: 900;
      margin-bottom: 8px;
    }
    label {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--dim);
      font-size: .72rem;
      margin: 7px 0;
    }
    input[type="text"], input[type="password"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: rgba(7, 9, 12, .72);
      color: var(--text);
      padding: 8px 10px;
      outline: none;
      font-size: .76rem;
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
    .auth-title {
      color: var(--accent);
      font-weight: 900;
      letter-spacing: .08em;
      margin-bottom: 6px;
    }
    .hint {
      color: var(--muted);
      font-size: .66rem;
      line-height: 1.45;
    }
    .error { color: var(--err); min-height: 18px; margin-top: 8px; font-size: .68rem; }
    .links {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .links a {
      color: var(--accent);
      text-decoration: none;
      border: 1px solid rgba(56, 189, 248, .35);
      border-radius: 6px;
      padding: 5px 8px;
      font-size: .62rem;
    }
    @media (max-width: 860px) {
      body { overflow: auto; }
      .shell { min-height: 100vh; height: auto; }
      .main { grid-template-columns: 1fr; }
      .side { order: -1; max-height: none; }
      .composer { grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; flex-direction: column; }
      .chips { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-title">Л.Е.С. LITE</div>
        <div class="brand-sub">локальный RAG чат без NiceGUI client state</div>
      </div>
      <div class="chips">
        <span id="authChip" class="chip">AUTH ...</span>
        <span id="profileChip" class="chip">PROFILE ...</span>
        <span id="memoryChip" class="chip">MEM ...</span>
        <span id="jobsChip" class="chip">JOBS ...</span>
      </div>
    </header>

    <main class="main">
      <section id="messages" class="messages" aria-live="polite"></section>
      <aside class="side">
        <div class="section">
          <div class="section-title">Контур</div>
          <div id="runtimeText" class="hint">Проверяю runtime...</div>
        </div>
        <div class="section">
          <div class="section-title">Параметры запроса</div>
          <label><input id="validation" type="checkbox" checked> Т.О.С.К.А. validation</label>
          <label><input id="reranker" type="checkbox"> Реранкер</label>
          <input id="dataset" type="text" placeholder="dataset filter, optional">
        </div>
        <div class="section">
          <div class="section-title">Е.Ж.И.К. Почта</div>
          <input id="mailQuery" type="text" placeholder="поиск: тема, участник, фраза">
          <div style="height:8px"></div>
          <button id="mailThreadsBtn" type="button">ЦЕПОЧКИ</button>
          <div id="mailText" class="hint">Кто кому что писал и цепочки писем.</div>
        </div>
        <div class="section">
          <div class="section-title">Сессия</div>
          <div id="sessionText" class="hint"></div>
          <button id="newSessionBtn" type="button">НОВАЯ СЕССИЯ</button>
        </div>
        <div class="section">
          <div class="section-title">Переходы</div>
          <div class="links">
            <a href="/les">АДМИНКА</a>
            <a href="/classic">CLASSIC UI</a>
          </div>
        </div>
      </aside>
    </main>

    <footer class="composer">
      <textarea id="question" placeholder="Спросите по локальной базе знаний..."></textarea>
      <button id="sendBtn" type="button">ОТПРАВИТЬ</button>
    </footer>
  </div>

  <div id="authPanel" class="auth">
    <div class="auth-card">
      <div class="auth-title">В.О.Л.К.</div>
      <div class="hint">Введите ключ доступа. На localhost trusted-доступ может открыться без ключа.</div>
      <div style="height:12px"></div>
      <input id="keyInput" type="password" placeholder="les_xxxxxxxxxxxxxxxx">
      <div style="height:10px"></div>
      <button id="loginBtn" type="button">ВОЙТИ</button>
      <div id="authError" class="error"></div>
    </div>
  </div>

  <script>
    const isLocalUi = location.port === "8051";
    const API_BASE = isLocalUi ? "/lite-api" : "";
    const KEY_STORAGE = "les_lite_api_key";
    const HOLDER_STORAGE = "les_lite_holder";
    const ROLE_STORAGE = "les_lite_role";
    const SESSION_STORAGE = "les_lite_session_id";

    const el = (id) => document.getElementById(id);
    const state = {
      key: localStorage.getItem(KEY_STORAGE) || "",
      holder: localStorage.getItem(HOLDER_STORAGE) || "",
      role: localStorage.getItem(ROLE_STORAGE) || "",
      pending: false,
      sessionId: localStorage.getItem(SESSION_STORAGE) || crypto.randomUUID(),
    };
    localStorage.setItem(SESSION_STORAGE, state.sessionId);

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
      let payload = null;
      const text = await response.text();
      try { payload = text ? JSON.parse(text) : {}; } catch (_) { payload = { detail: text }; }
      if (!response.ok) {
        const message = payload.detail || payload.error || ("HTTP " + response.status);
        const error = new Error(typeof message === "string" ? message : JSON.stringify(message));
        error.status = response.status;
        error.payload = payload;
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

    function setChip(id, text, cls) {
      const node = el(id);
      node.textContent = text;
      node.className = "chip" + (cls ? " " + cls : "");
    }

    function showAuth(show, message = "") {
      el("authPanel").style.display = show ? "flex" : "none";
      el("authError").textContent = message;
    }

    async function saveFeedback(historyId, feedback, button, statusNode) {
      if (!historyId || !button) return;
      const previous = button.textContent;
      button.disabled = true;
      button.textContent = "...";
      if (statusNode) statusNode.textContent = "";
      try {
        await request("/api/chat/history/" + encodeURIComponent(historyId) + "/feedback", {
          method: "POST",
          body: JSON.stringify({ feedback }),
        });
        button.textContent = "OK";
        if (statusNode) statusNode.textContent = "сохранено";
      } catch (error) {
        button.disabled = false;
        button.textContent = previous;
        if (statusNode) statusNode.textContent = error.message;
        if (error.status === 401 || error.status === 403) showAuth(true, error.message);
      }
    }

    function addMessage(text, type, meta = {}) {
      const wrap = document.createElement("div");
      wrap.className = "msg " + type;
      const body = document.createElement("div");
      body.textContent = text;
      wrap.appendChild(body);
      if (meta.crag || (meta.sources && meta.sources.length)) {
        const line = document.createElement("div");
        line.className = "sources";
        if (meta.crag) {
          const crag = document.createElement("span");
          crag.className = "source";
          crag.textContent = meta.crag;
          line.appendChild(crag);
        }
        for (const source of meta.sources || []) {
          const item = document.createElement("span");
          item.className = "source";
          item.textContent = source;
          line.appendChild(item);
        }
        wrap.appendChild(line);
      }
      if (meta.history_id) {
        const feedback = document.createElement("div");
        feedback.className = "feedback";
        const status = document.createElement("span");
        status.className = "feedback-status";
        const makeButton = (label, title, value, className = "") => {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.title = title;
          button.setAttribute("aria-label", title);
          if (className) button.className = className;
          button.addEventListener("click", () => saveFeedback(meta.history_id, value, button, status));
          return button;
        };
        feedback.appendChild(makeButton("✓", "Ответ корректен", "correct"));
        feedback.appendChild(makeButton("Плохой ответ", "Плохой ответ: сохранить для разбора", "bad_answer", "bad-answer"));
        feedback.appendChild(makeButton("DS", "Источник не из того датасета", "wrong_dataset"));
        feedback.appendChild(status);
        wrap.appendChild(feedback);
      }
      el("messages").appendChild(wrap);
      el("messages").scrollTop = el("messages").scrollHeight;
      return wrap;
    }

    function updateSessionText() {
      el("sessionText").textContent = state.sessionId;
    }

    async function refreshRuntime() {
      try {
        const data = await request("/api/indexing-mode", { method: "GET" });
        showAuth(false);
        const profile = data.runtime_profile || data.mode?.runtime_profile || "?";
        const memory = data.memory_state || {};
        const memState = memory.state || "?";
        const allowed = data.chat_generation_allowed !== false;
        setChip("authChip", state.key ? (state.role || "KEY") : "TRUSTED", "chip-ok");
        setChip("profileChip", profile, allowed ? "chip-ok" : "chip-err");
        setChip("memoryChip", memState, memState === "GREEN" ? "chip-ok" : (memState === "YELLOW" ? "chip-warn" : "chip-err"));
        setChip("jobsChip", (data.chat_admission?.active_jobs || 0) + " JOBS", data.chat_admission?.active_jobs ? "chip-warn" : "chip-ok");
        el("runtimeText").textContent = (data.chat_generation_reason || "chat allowed") + " | " + (memory.reason || "");
      } catch (error) {
        if (error.status === 401 && !state.key) {
          setChip("authChip", "KEY REQUIRED", "chip-warn");
          showAuth(true);
          el("runtimeText").textContent = "Нужен ключ доступа.";
          return;
        }
        if (error.status === 401 || error.status === 403) {
          localStorage.removeItem(KEY_STORAGE);
          state.key = "";
          setChip("authChip", "AUTH FAIL", "chip-err");
          showAuth(true, error.message);
          return;
        }
        setChip("profileChip", "OFFLINE", "chip-err");
        el("runtimeText").textContent = error.message;
      }
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
          headers: { "Content-Type": "application/json" },
        });
        state.key = key;
        state.role = result.role || "user";
        state.holder = result.holder || "";
        localStorage.setItem(KEY_STORAGE, state.key);
        localStorage.setItem(ROLE_STORAGE, state.role);
        localStorage.setItem(HOLDER_STORAGE, state.holder);
        showAuth(false);
        addMessage("Вход выполнен: " + (state.holder || state.role), "msg-sys");
        await refreshRuntime();
      } catch (error) {
        showAuth(true, error.message);
      } finally {
        el("loginBtn").disabled = false;
      }
    }

    async function send() {
      const question = el("question").value.trim();
      if (!question || state.pending) return;
      state.pending = true;
      el("sendBtn").disabled = true;
      el("question").value = "";
      addMessage(question, "msg-user");
      const placeholder = addMessage("Генерирую...", "msg-ai");
      const started = Date.now();
      const timer = setInterval(() => {
        placeholder.firstChild.textContent = "Генерирую... " + Math.floor((Date.now() - started) / 1000) + "с";
      }, 1000);
      try {
        const payload = {
          question,
          validation_enabled: el("validation").checked,
          reranker_enabled: el("reranker").checked,
          session_id: state.sessionId,
        };
        const dataset = el("dataset").value.trim();
        if (dataset) payload.dataset_filter = dataset;
        const data = await request("/api/chat", { method: "POST", body: JSON.stringify(payload) });
        placeholder.remove();
        addMessage(data.answer || data.response || "Нет ответа", "msg-ai", {
          crag: data.crag_status || "",
          sources: data.sources || [],
          history_id: data.history_id || null,
        });
      } catch (error) {
        placeholder.remove();
        const prefix = error.status === 409 ? "Индексирование активно: " : "Ошибка: ";
        addMessage(prefix + error.message, "msg-sys");
        if (error.status === 401 || error.status === 403) showAuth(true, error.message);
      } finally {
        clearInterval(timer);
        state.pending = false;
        el("sendBtn").disabled = false;
        await refreshRuntime();
      }
    }

    function formatMailThreads(data) {
      const lines = [
        "Е.Ж.И.К.: " + (data.total_threads || 0) + " цепочек / " + (data.total_messages || 0) + " писем"
      ];
      const threads = (data.threads || []).slice(0, 8);
      if (!threads.length) {
        lines.push("Ничего не найдено.");
        return lines.join("\n");
      }
      threads.forEach((thread, idx) => {
        const who = thread.who_to_whom || {};
        const what = thread.what || {};
        const to = (who.to || []).join(", ") || "?";
        lines.push("");
        lines.push((idx + 1) + ". " + (thread.subject || "(без темы)") + " [" + (thread.message_count || 0) + "]");
        lines.push((thread.last_date || "") + " | " + (who.from || "?") + " -> " + to);
        if (what.snippet) lines.push(what.snippet);
        lines.push("thread=" + thread.thread_key);
      });
      return lines.join("\n");
    }

    async function showMailThreads() {
      const q = el("mailQuery").value.trim();
      el("mailThreadsBtn").disabled = true;
      try {
        const query = q ? "&q=" + encodeURIComponent(q) : "";
        const data = await request("/api/mail/threads?limit=8" + query, { method: "GET" });
        addMessage(formatMailThreads(data), "msg-ai", { crag: "MAIL" });
        el("mailText").textContent = "Найдено: " + (data.total_threads || 0) + " цепочек.";
      } catch (error) {
        addMessage("Почта: " + error.message, "msg-sys");
        if (error.status === 401 || error.status === 403) showAuth(true, error.message);
      } finally {
        el("mailThreadsBtn").disabled = false;
      }
    }

    el("sendBtn").addEventListener("click", send);
    el("mailThreadsBtn").addEventListener("click", showMailThreads);
    el("loginBtn").addEventListener("click", login);
    el("keyInput").addEventListener("keydown", (event) => { if (event.key === "Enter") login(); });
    el("question").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) send();
    });
    el("newSessionBtn").addEventListener("click", () => {
      state.sessionId = crypto.randomUUID();
      localStorage.setItem(SESSION_STORAGE, state.sessionId);
      updateSessionText();
      addMessage("Новая сессия создана.", "msg-sys");
    });

    updateSessionText();
    addMessage("Lite chat готов. Ctrl/⌘+Enter отправляет вопрос.", "msg-sys");
    refreshRuntime();
    setInterval(refreshRuntime, 15000);
  </script>
</body>
</html>"""


def register_lite_chat_routes() -> None:
    from nicegui import app

    @app.get("/")
    async def lite_chat_page():
        return HTMLResponse(lite_chat_html())

    @app.api_route("/lite-api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def lite_api_bridge(path: str, request: Request):
        return await bridge_proxy_request(path, request)
