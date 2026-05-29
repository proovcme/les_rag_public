"""Static 1280x720 status display for the Wokyis M5 mini screen."""

from __future__ import annotations

from starlette.responses import HTMLResponse


def m5_display_html() -> str:
    return r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>С.О.В.У.Ш.К.А. M5</title>
  <style>
    :root {
      --ink: #101010;
      --paper: #ece8dc;
      --paper-2: #f7f4ea;
      --shade: #c9c2b2;
      --line: #111111;
      --soft-line: #777166;
      --green: #237a4b;
      --amber: #b86b18;
      --red: #a7332f;
      --blue: #225f9f;
      --violet: #5a4b8b;
      --shadow: rgba(0, 0, 0, .42);
      --font: Monaco, "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace;
    }
    * { box-sizing: border-box; }
    html, body {
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: #050505;
      color: var(--ink);
      font-family: var(--font);
      letter-spacing: 0;
    }
    body {
      display: grid;
      place-items: center;
    }
    .stage {
      width: min(100vw, calc(100vh * 16 / 9));
      aspect-ratio: 16 / 9;
      background: #0c0c0c;
      display: grid;
      place-items: center;
      box-shadow: 0 0 0 8px #050505, 0 18px 70px var(--shadow);
    }
    .screen {
      width: 100%;
      height: 100%;
      overflow: hidden;
      background:
        linear-gradient(90deg, rgba(255,255,255,.26) 0 1px, transparent 1px 100%),
        linear-gradient(180deg, rgba(0,0,0,.08) 0 1px, transparent 1px 100%),
        var(--paper);
      background-size: 8px 8px, 8px 8px, auto;
      border: 2px solid #0f0f0f;
      display: grid;
      grid-template-rows: 38px minmax(0, 1fr) 28px;
    }
    .menubar {
      height: 38px;
      display: grid;
      grid-template-columns: 345px minmax(0, 1fr) 310px;
      align-items: center;
      border-bottom: 3px double var(--line);
      background: var(--paper-2);
      padding: 0 10px;
      gap: 10px;
      white-space: nowrap;
    }
    .brand {
      display: flex;
      align-items: center;
      min-width: 0;
      gap: 10px;
      font-weight: 900;
      font-size: 16px;
    }
    .rainbow {
      width: 54px;
      height: 18px;
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      border: 2px solid var(--line);
      background: #fff;
    }
    .rainbow i:nth-child(1) { background: #3d7cc9; }
    .rainbow i:nth-child(2) { background: #6b4aa0; }
    .rainbow i:nth-child(3) { background: #d93f38; }
    .rainbow i:nth-child(4) { background: #f07c24; }
    .rainbow i:nth-child(5) { background: #f2c230; }
    .rainbow i:nth-child(6) { background: #2f8b57; }
    .menu {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 13px;
      font-weight: 800;
      color: #2c2c2c;
    }
    .menu span { margin-right: 20px; }
    .status-strip {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 8px;
      min-width: 0;
      font-size: 12px;
      font-weight: 900;
    }
    .badge {
      min-width: 66px;
      height: 22px;
      display: inline-grid;
      place-items: center;
      border: 2px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 0 8px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .badge.ok { color: var(--green); }
    .badge.warn { color: var(--amber); }
    .badge.err { color: var(--red); }
    .desk {
      min-height: 0;
      display: grid;
      grid-template-columns: 1fr;
      padding: 12px;
      place-items: center;
    }
    .window {
      min-width: 0;
      min-height: 0;
      border: 3px solid var(--line);
      background: var(--paper-2);
      box-shadow: 5px 5px 0 rgba(0,0,0,.24);
      display: grid;
      grid-template-rows: 28px minmax(0, 1fr);
      overflow: hidden;
    }
    .titlebar {
      height: 28px;
      border-bottom: 2px solid var(--line);
      display: grid;
      grid-template-columns: 26px minmax(0, 1fr) 26px;
      align-items: center;
      background:
        repeating-linear-gradient(180deg, #fff 0 2px, #bdb7a8 2px 4px);
      font-size: 12px;
      font-weight: 900;
      text-align: center;
    }
    .box-icon {
      width: 13px;
      height: 13px;
      border: 2px solid var(--line);
      background: var(--paper-2);
      margin-left: 7px;
    }
    .zoom-icon {
      width: 16px;
      height: 16px;
      border: 2px solid var(--line);
      background: var(--paper-2);
      margin-left: 4px;
    }
    .ascii-window {
      width: 100%;
      height: 100%;
    }
    .ascii-pre {
      margin: 0;
      padding: 16px 24px;
      background: var(--paper-2);
      color: var(--ink);
      font-family: var(--font);
      font-size: 14px;
      line-height: 1.4;
      overflow: hidden;
      white-space: pre;
    }
    .ticker {
      height: 28px;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 10px;
      border-top: 3px double var(--line);
      background: var(--paper-2);
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
      overflow: hidden;
    }
    .ticker .square {
      width: 14px;
      height: 14px;
      border: 2px solid var(--line);
      background: var(--blue);
      flex: none;
    }
    .ticker-text {
      overflow: hidden;
      text-overflow: ellipsis;
    }
    @media (min-aspect-ratio: 16 / 9) {
      .stage { height: 100vh; width: calc(100vh * 16 / 9); }
    }
    @media (max-aspect-ratio: 16 / 9) {
      .stage { width: 100vw; height: calc(100vw * 9 / 16); }
    }
  </style>
</head>
<body>
  <div class="stage">
    <div class="screen retro-apple" data-mood="boot">
      <header class="menubar">
        <div class="brand">
          <span class="rainbow" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></span>
          <span>S.O.V.U.S.H.K.A M5</span>
        </div>
        <div class="menu">
          <span>Finder</span><span>RAG</span><span>Memory</span><span>Models</span><span>1280x720</span>
        </div>
        <div class="status-strip">
          <span id="apiBadge" class="badge warn">BOOT</span>
          <span id="profileBadge" class="badge">PROFILE</span>
          <span id="clock" class="badge">--:--</span>
        </div>
      </header>

      <main class="desk">
        <section class="window ascii-window">
          <div class="titlebar">
            <span class="box-icon"></span>
            <span>С.О.В.У.Ш.К.А. M5 // SYSTEM MONITOR</span>
            <span class="zoom-icon"></span>
          </div>
          <pre id="asciiScreen" class="ascii-pre">
[Телеметрия загружается...]
          </pre>
        </section>
      </main>

      <footer class="ticker">
        <span class="square"></span>
        <span id="tickerText" class="ticker-text">S.O.V.U.S.H.K.A M5 DISPLAY // waiting for first telemetry frame</span>
      </footer>
    </div>
  </div>

  <script>
    const isLocalUi = location.port === "8051";
    const API_BASE = isLocalUi ? "/lite-api" : "";
    const KEY_STORAGE = "les_lite_api_key";
    const state = {
      key: localStorage.getItem(KEY_STORAGE) || "",
      frame: 0,
      lastOk: "",
    };
    const el = (id) => document.getElementById(id);

    function apiPath(path) {
      if (!API_BASE) return path;
      return API_BASE + path.replace(/^\/api(?=\/)/, "");
    }

    function headers() {
      const out = { "Accept": "application/json" };
      if (state.key) out["X-API-Key"] = state.key;
      return out;
    }

    async function request(path) {
      const response = await fetch(apiPath(path), { headers: headers() });
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

    function setBadge(id, text, tone = "") {
      const node = el(id);
      if (!node) return;
      node.textContent = text || "";
      node.className = "badge" + (tone ? " " + tone : "");
    }

    function fmt(n) {
      if (n === null || n === undefined || n === "") return "--";
      const num = Number(n);
      if (!Number.isFinite(num)) return String(n);
      return num.toLocaleString("ru-RU");
    }

    function oneDecimal(n) {
      const num = Number(n);
      if (!Number.isFinite(num)) return "--";
      return num.toFixed(1);
    }

    function settled(result) {
      return result && result.status === "fulfilled" ? result.value : null;
    }

    function rejectedStatus(results) {
      const failed = results.find((item) => item.status === "rejected");
      return failed ? failed.reason : null;
    }

    function _n(v) {
      if (!v) return "—";
      return typeof v === "object" ? (v.path || v.name || "—") : String(v);
    }

    function _l(v, def = false) {
      if (!v) return def;
      return typeof v === "object" ? (v.loaded !== false) : def;
    }

    function renderTelemetry(statusData, dispatcher, watcher, mail, apiError) {
      const screen = document.querySelector(".screen");
      const reindex = dispatcher?.reindex || {};
      const completed = Number(reindex.completed || 0);
      const total = Number(reindex.total || (completed + Number(reindex.remaining || 0)) || 0);
      const remaining = Number(reindex.remaining || 0);
      const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((completed / total) * 100))) : 0;
      const reindexLabel = reindex.running ? "RUNNING" : reindex.paused ? "PAUSED" : reindex.complete ? "DONE" : "IDLE";

      const pressure = statusData?.memory_state || dispatcher?.memory?.pressure || {};
      const memory = pressure.memory || dispatcher?.memory?.preflight || {};
      const memoryState = pressure.state || "UNKNOWN";
      const admission = statusData?.chat_admission || {};
      const profile = statusData?.runtime_profile || "UNKNOWN";

      const isOffline = Boolean(apiError) && !dispatcher && !statusData;
      const isBusy = Boolean(reindex.running || statusData?.mode?.mode === "indexing" || admission.active_jobs);
      const mood = isOffline ? "offline" : isBusy ? "busy" : "ready";
      screen.dataset.mood = mood;

      setBadge("apiBadge", isOffline ? "OFFLINE" : "LIVE", isOffline ? "err" : "ok");
      setBadge("profileBadge", profile, admission.allowed === false ? "err" : "ok");

      // Extract systemStatus
      const systemStatus = isOffline ? "OFFLINE ✗" : "ONLINE ✓";

      // Services status from dispatcher
      let servicesList = "—";
      if (dispatcher?.services) {
        servicesList = dispatcher.services.map(s => {
          const run = s.running ? "UP" : "DOWN";
          return `${s.title}=${run}`;
        }).join(" | ");
      }

      // Reindex current file & log
      const file = reindex.current_doc?.file_name || "—";
      const displayFile = file.length > 50 ? "..." + file.slice(-47) : file;
      const logText = reindex.last_log || "—";
      const displayLog = logText.length > 50 ? logText.slice(0, 47) + "..." : logText;

      // Extract models status
      const mlx = statusData?.mlx || {};
      const modelMain = `${_n(mlx.main_model || mlx.model)} [${_l(mlx.main_model || mlx.model, true) ? "LIVE" : "IDLE"}]`;
      const modelVal = mlx.val_model ? `${_n(mlx.val_model)} [${_l(mlx.val_model, false) ? "LIVE" : "IDLE"}]` : "— [IDLE]";
      const modelEmbed = `${_n(mlx.embed_model || mlx.embedding_model || statusData?.embedding?.embedding_model)} [LIVE]`;

      const ramFree = oneDecimal(memory.ram_free_gb);
      const ramTotal = oneDecimal(memory.ram_total_gb);
      const swapPct = oneDecimal(memory.swap_pct);

      function pad(str, len, char = " ") {
        const s = String(str || "");
        if (s.length >= len) return s.slice(0, len);
        return s + char.repeat(len - s.length);
      }

      const midWidth = 72;
      const systemTitle = " [ СИСТЕМА ] " + "═".repeat(midWidth - 13);
      const systemLine1 = `Состояние:       ${systemStatus}`;
      const systemLine2 = `Свободная RAM:   ${ramFree} GB / ${ramTotal} GB (Swap: ${swapPct}%)`;
      const systemLine3 = `Текущий профиль: ${profile} [ ${memoryState} ]`;
      const systemLine4 = `Службы launchd:  ${servicesList}`;

      const indexTitle = " [ ИНДЕКСАЦИЯ RAG ] " + "═".repeat(midWidth - 20);
      const indexLine1 = `Кампания:        ${completed} / ${total} файлов (${percent}%)`;
      const indexLine2 = `Состояние:       ${reindexLabel}`;
      const indexLine3 = `Осталось:        ${remaining} файлов`;
      const indexLine4 = `Текущий файл:    ${displayFile}`;
      const indexLine5 = `Лог-трек:        ${displayLog}`;

      const modelsTitle = " [ АКТИВНЫЕ МОДЕЛИ MLX ] " + "═".repeat(midWidth - 25);
      const modelsLine1 = `MAIN  [Языковая]:  ${modelMain}`;
      const modelsLine2 = `VAL   [Валидатор]: ${modelVal}`;
      const modelsLine3 = `EMBED [Вектор]:    ${modelEmbed}`;

      const lines = [
        `╔═════════╗  ${pad("═════════[ С.О.В.У.Ш.К.А. SYSTEM MONITOR ]═════════", midWidth)}  ╔═════════╗`,
        `║ /\\_ _/\\ ║  ${pad("", midWidth)}  ║ /\\_ _/\\ ║`,
        `║(  o o  )║  ${pad(systemTitle, midWidth)}  ║(  o o  )║`,
        `║(  =V=  )║  ${pad("  " + systemLine1, midWidth)}  ║(  =V=  )║`,
        `║(_______)║  ${pad("  " + systemLine2, midWidth)}  ║(_______)║`,
        `║-"-----"-║  ${pad("  " + systemLine3, midWidth)}  ║-"-----"-║`,
        `║         ║  ${pad("  " + systemLine4, midWidth)}  ║         ║`,
        `║         ║  ${pad("", midWidth)}  ║         ║`,
        `║         ║  ${pad(indexTitle, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + indexLine1, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + indexLine2, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + indexLine3, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + indexLine4, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + indexLine5, midWidth)}  ║         ║`,
        `║         ║  ${pad("", midWidth)}  ║         ║`,
        `║         ║  ${pad(modelsTitle, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + modelsLine1, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + modelsLine2, midWidth)}  ║         ║`,
        `║         ║  ${pad("  " + modelsLine3, midWidth)}  ║         ║`,
        `║-"-----"-║  ${pad("", midWidth)}  ║-"-----"-║`,
        `║(_______)║  ${pad("═".repeat(midWidth), midWidth, "═")}  ║(_______)║`,
        `║(  =V=  )║  ${pad("                      OS VERSION: MAC", midWidth)}  ║(  =V=  )║`,
        `║(  o o  )║  ${pad("                   UPTIME TELEMETRY: OK", midWidth)}  ║(  o o  )║`,
        `║ /\\_ _/\\ ║  ${pad("", midWidth)}  ║ /\\_ _/\\ ║`,
        `╚═════════╝  ${pad("════════════════════════════════════════════════", midWidth, "═")}  ╚═════════╝`
      ];

      const asciiScreen = el("asciiScreen");
      if (asciiScreen) {
        asciiScreen.textContent = lines.join("\n");
      }

      const err = apiError ? ` | ${apiError.message || apiError}` : "";
      state.lastOk = isOffline ? state.lastOk : new Date().toLocaleTimeString("ru-RU");
      setText(
        "tickerText",
        `M5 1280x720 // ${reindexLabel} ${fmt(completed)}/${fmt(total)} // MEM ${memoryState} ${ramFree}GB // updated ${state.lastOk || "--"}${err}`
      );
    }

    async function refresh() {
      state.frame += 1;
      const results = await Promise.allSettled([
        request("/api/status"),
        request("/api/runtime/dispatcher/status"),
        request("/api/rag/watch/status?source_root=RAG_Content&limit=6"),
        request("/api/mail/status"),
      ]);
      renderTelemetry(
        settled(results[0]),
        settled(results[1]),
        settled(results[2]),
        settled(results[3]),
        rejectedStatus(results)
      );
    }

    function tickClock() {
      const node = el("clock");
      if (node) node.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    }

    function setText(id, text) {
      const node = el(id);
      if (node) node.textContent = text == null ? "" : String(text);
    }

    tickClock();
    refresh();
    setInterval(tickClock, 1000);
    setInterval(refresh, 5000);
  </script>
</body>
</html>"""


def register_m5_display_routes() -> None:
    from nicegui import app

    @app.get("/m5")
    @app.get("/m5/")
    @app.get("/display/m5")
    @app.get("/display/m5/")
    async def m5_display_page():
        return HTMLResponse(m5_display_html())
