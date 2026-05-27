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
    button, input, textarea { font: inherit; }
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
      grid-template-columns: 330px minmax(0, 1fr) 292px;
      gap: 10px;
      padding: 10px;
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
    .owl-window {
      padding: 12px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 10px;
      min-height: 0;
    }
    .owl-bezel {
      width: 100%;
      aspect-ratio: 1 / 1;
      border: 4px solid var(--line);
      background:
        radial-gradient(circle at 50% 38%, rgba(255,255,255,.8), transparent 0 62%, rgba(0,0,0,.08) 63%),
        #ddd7c9;
      display: grid;
      place-items: center;
      image-rendering: pixelated;
    }
    #owlCanvas {
      width: 232px;
      height: 232px;
      image-rendering: pixelated;
    }
    .owl-meta {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      border-top: 2px solid var(--line);
      padding-top: 8px;
      font-size: 13px;
      font-weight: 900;
      min-height: 42px;
    }
    .mood {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .blink {
      width: 16px;
      height: 16px;
      border: 2px solid var(--line);
      background: var(--green);
      box-shadow: inset 0 0 0 3px #fff;
    }
    .screen[data-mood="busy"] .blink { background: var(--amber); }
    .screen[data-mood="offline"] .blink { background: var(--red); }
    .core {
      min-height: 0;
      display: grid;
      grid-template-rows: 210px 1fr 150px;
      gap: 10px;
    }
    .big-panel {
      padding: 14px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 8px;
    }
    .label {
      font-size: 12px;
      line-height: 1;
      font-weight: 900;
      text-transform: uppercase;
      color: #3d3a35;
      display: flex;
      justify-content: space-between;
      gap: 10px;
    }
    .value {
      align-self: center;
      font-size: 52px;
      line-height: 1;
      font-weight: 900;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .hint {
      min-height: 18px;
      font-size: 12px;
      line-height: 1.25;
      color: #3f3b35;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .progress {
      height: 18px;
      border: 2px solid var(--line);
      background:
        repeating-linear-gradient(90deg, #fff 0 8px, #d2cab9 8px 16px);
      overflow: hidden;
    }
    .fill {
      height: 100%;
      width: 0%;
      background: var(--green);
      border-right: 2px solid var(--line);
      transition: width .35s ease;
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      min-height: 0;
    }
    .tile {
      padding: 12px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      gap: 8px;
    }
    .tile .num {
      align-self: center;
      font-size: 31px;
      line-height: 1;
      font-weight: 900;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .list-panel {
      padding: 10px;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 8px;
    }
    .rows {
      min-height: 0;
      overflow: hidden;
      display: grid;
      align-content: start;
      gap: 6px;
    }
    .row {
      min-height: 42px;
      border: 2px solid var(--line);
      background: #fffdf4;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 6px 8px;
    }
    .row-title {
      font-size: 12px;
      line-height: 1.1;
      font-weight: 900;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .row-detail {
      margin-top: 3px;
      font-size: 10px;
      line-height: 1.1;
      color: #47433d;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mini-badge {
      height: 23px;
      min-width: 48px;
      display: grid;
      place-items: center;
      border: 2px solid var(--line);
      padding: 0 6px;
      font-size: 10px;
      line-height: 1;
      font-weight: 900;
      background: #e9e4d7;
    }
    .mini-badge.ok { color: var(--green); }
    .mini-badge.warn { color: var(--amber); }
    .mini-badge.err { color: var(--red); }
    .rail {
      min-height: 0;
      display: grid;
      grid-template-rows: 1fr 1fr;
      gap: 10px;
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
          <span>Finder</span><span>RAG</span><span>Memory</span><span>Mail</span><span>1280x720</span>
        </div>
        <div class="status-strip">
          <span id="apiBadge" class="badge warn">BOOT</span>
          <span id="profileBadge" class="badge">PROFILE</span>
          <span id="clock" class="badge">--:--</span>
        </div>
      </header>

      <main class="desk">
        <section class="window">
          <div class="titlebar">
            <span class="box-icon"></span>
            <span>СОВУШКА.SYSTEM</span>
            <span class="zoom-icon"></span>
          </div>
          <div class="owl-window">
            <div class="label"><span>RETRO OWL</span><span id="owlCode">INIT</span></div>
            <div class="owl-bezel">
              <canvas id="owlCanvas" width="96" height="96" aria-label="pixel owl"></canvas>
            </div>
            <div class="owl-meta">
              <div id="owlMood" class="mood">загрузка датчиков...</div>
              <div class="blink" aria-hidden="true"></div>
            </div>
          </div>
        </section>

        <section class="core">
          <section class="window big-panel">
            <div class="label"><span>GUARDED REINDEX</span><span id="reindexState">WAIT</span></div>
            <div id="reindexValue" class="value">-- / --</div>
            <div>
              <div class="progress"><div id="reindexFill" class="fill"></div></div>
              <div id="reindexHint" class="hint">ожидание runtime dispatcher</div>
            </div>
          </section>

          <section class="tiles">
            <div class="window tile">
              <div class="label"><span>MEMORY</span><span id="memoryState">?</span></div>
              <div id="memoryValue" class="num">-- GB</div>
              <div id="memoryHint" class="hint">swap --%</div>
            </div>
            <div class="window tile">
              <div class="label"><span>WATCHER</span><span id="watcherState">RAG</span></div>
              <div id="watcherValue" class="num">--</div>
              <div id="watcherHint" class="hint">RAG_Content</div>
            </div>
            <div class="window tile">
              <div class="label"><span>MAIL</span><span id="mailState">ЕЖИК</span></div>
              <div id="mailValue" class="num">--</div>
              <div id="mailHint" class="hint">IMAP / Apple Mail</div>
            </div>
          </section>

          <section class="window list-panel">
            <div class="label"><span>RAG QUEUE</span><span id="queueState">SCAN</span></div>
            <div id="queueRows" class="rows"></div>
          </section>
        </section>

        <aside class="rail">
          <section class="window list-panel">
            <div class="label"><span>SERVICES</span><span id="serviceState">LOCAL</span></div>
            <div id="serviceRows" class="rows"></div>
          </section>
          <section class="window list-panel">
            <div class="label"><span>MAIL LAYER</span><span id="mailLayerState">PROFILE</span></div>
            <div id="mailRows" class="rows"></div>
          </section>
        </aside>
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

    function setText(id, text) {
      const node = el(id);
      if (node) node.textContent = text == null ? "" : String(text);
    }

    function setBadge(id, text, tone = "") {
      const node = el(id);
      if (!node) return;
      node.textContent = text || "";
      node.className = "badge" + (tone ? " " + tone : "");
    }

    function setMiniBadge(node, text, tone = "") {
      node.textContent = text || "";
      node.className = "mini-badge" + (tone ? " " + tone : "");
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

    function rowNode(titleText, detailText, badgeText, tone = "") {
      const row = document.createElement("div");
      row.className = "row";
      const text = document.createElement("div");
      const title = document.createElement("div");
      const detail = document.createElement("div");
      const badge = document.createElement("div");
      title.className = "row-title";
      detail.className = "row-detail";
      title.textContent = titleText || "";
      detail.textContent = detailText || "";
      setMiniBadge(badge, badgeText || "", tone);
      text.append(title, detail);
      row.append(text, badge);
      return row;
    }

    function setRows(id, rows, emptyTitle = "NO DATA", emptyDetail = "") {
      const node = el(id);
      if (!node) return;
      if (!rows.length) {
        node.replaceChildren(rowNode(emptyTitle, emptyDetail, "OK", "ok"));
        return;
      }
      node.replaceChildren(...rows);
    }

    function toneForState(value) {
      const stateName = String(value || "").toUpperCase();
      if (["GREEN", "OK", "READY", "DONE", "UP"].includes(stateName)) return "ok";
      if (["YELLOW", "WARN", "WAIT", "RUNNING", "PAUSED", "BUSY"].includes(stateName)) return "warn";
      if (["RED", "CRITICAL", "ERROR", "DOWN", "OFFLINE"].includes(stateName)) return "err";
      return "";
    }

    function settled(result) {
      return result && result.status === "fulfilled" ? result.value : null;
    }

    function rejectedStatus(results) {
      const failed = results.find((item) => item.status === "rejected");
      return failed ? failed.reason : null;
    }

    function drawPixelOwl(mood) {
      const canvas = el("owlCanvas");
      const ctx = canvas.getContext("2d");
      ctx.imageSmoothingEnabled = false;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const palette = {
        ".": "#ece8dc",
        "B": "#111111",
        "G": "#6e685e",
        "W": "#fffdf4",
        "Y": "#f2c230",
        "O": "#f07c24",
        "R": "#d93f38",
        "E": mood === "offline" ? "#a7332f" : mood === "busy" ? "#b86b18" : "#237a4b",
      };
      const art = [
        "........................",
        ".........BBBBBB.........",
        ".......BBGGGGGGBB.......",
        "......BGGGGGGGGGGB......",
        ".....BGGBBGBBGBBGGB.....",
        "....BGGWWBGGGGBWWGGB....",
        "...BGGGWEBGGGGBEWGGGB...",
        "...BGGGWWGGYGGGWWGGGB...",
        "..BGGGGGGGYOYGGGGGGGB...",
        "..BGGGBGGGYYYGGGBGGGB...",
        "..BGGGBBGGGYGGGBBGGGB...",
        "...BGGGGBGGGGGBGGGGB....",
        "...BGGGGGBBBBBGGGGGB....",
        "....BGGGGGGGGGGGGGB.....",
        ".....BGGGBBBBBGGGB......",
        "......BBGGRRRRGGBB......",
        ".......BGRRRRRRGB.......",
        "........BBGGGGBB........",
        ".........BGGGGB.........",
        "........BGB..BGB........",
        ".......BB....BB.........",
        "........................",
        "........................",
        "........................",
      ];
      const cell = 4;
      for (let y = 0; y < art.length; y++) {
        for (let x = 0; x < art[y].length; x++) {
          ctx.fillStyle = palette[art[y][x]] || palette["."];
          ctx.fillRect(x * cell, y * cell, cell, cell);
        }
      }
      if (mood === "busy" && state.frame % 2 === 0) {
        ctx.fillStyle = "#f07c24";
        ctx.fillRect(43, 21, 10, 6);
        ctx.fillRect(67, 21, 10, 6);
      }
    }

    function renderTelemetry(mode, dispatcher, watcher, mail, apiError) {
      const screen = document.querySelector(".screen");
      const reindex = dispatcher?.reindex || {};
      const completed = Number(reindex.completed || 0);
      const total = Number(reindex.total || (completed + Number(reindex.remaining || 0)) || 0);
      const remaining = Number(reindex.remaining || 0);
      const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((completed / total) * 100))) : 0;
      const reindexLabel = reindex.running ? "RUNNING" : reindex.paused ? "PAUSED" : reindex.complete ? "DONE" : "IDLE";

      const pressure = dispatcher?.memory?.pressure || mode?.memory_state || {};
      const memory = pressure.memory || dispatcher?.memory?.preflight || {};
      const memoryState = pressure.state || "UNKNOWN";
      const admission = mode?.chat_admission || {};
      const profile = dispatcher?.runtime_profile || mode?.runtime_profile || "UNKNOWN";
      const watcherCounts = watcher?.counts || {};
      const mailDataset = mail?.dataset || {};
      const mailStatus = mail?.status || "unknown";
      const imap = mail?.imap || {};
      const appleMail = mail?.apple_mail || {};

      const isOffline = Boolean(apiError) && !dispatcher && !mode;
      const isBusy = Boolean(reindex.running || mode?.active || admission.active_jobs);
      const mood = isOffline ? "offline" : isBusy ? "busy" : "ready";
      screen.dataset.mood = mood;
      drawPixelOwl(mood);

      setBadge("apiBadge", isOffline ? "OFFLINE" : "LIVE", isOffline ? "err" : "ok");
      setBadge("profileBadge", profile, admission.allowed === false ? "err" : "ok");
      setText("owlCode", mood.toUpperCase());
      setText("owlMood", isOffline ? "нет связи с LES runtime" : isBusy ? "индексирую и берегу память" : "дежурю на маленьком экране");

      setText("reindexState", reindexLabel);
      setText("reindexValue", `${fmt(completed)} / ${fmt(total)}`);
      el("reindexFill").style.width = percent + "%";
      setText(
        "reindexHint",
        `remaining=${fmt(remaining)} | pid=${reindex.pid || "--"} | ${reindex.current_doc?.event || reindex.last_event?.event || reindex.last_log || "idle"}`
      );

      setText("memoryState", memoryState);
      setText("memoryValue", `${oneDecimal(memory.ram_free_gb)} GB`);
      setText("memoryHint", `swap=${oneDecimal(memory.swap_pct)}% | ${pressure.reason || "memory guard"}`);

      const pending = Number(watcher?.pending_changes ?? 0);
      const changed = Number(watcherCounts.changed || 0);
      const routeChanged = Number(watcherCounts.route_changed || 0);
      setText("watcherState", pending ? "DIRTY" : "CLEAN");
      setText("watcherValue", `${fmt(pending)} pending`);
      setText("watcherHint", `new=${fmt(watcherCounts.new || 0)} | changed=${fmt(changed)} | route=${fmt(routeChanged)}`);

      setText("mailState", mailStatus === "ready" ? "READY" : "WAIT");
      setText("mailValue", mailDataset.doc_count != null ? `${fmt(mailDataset.doc_count)} docs` : mailStatus.toUpperCase());
      setText(
        "mailHint",
        `imap=${imap.enabled ? "on" : "off"} | apple=${appleMail.status || "--"} | ${imap.host || "no host"}`
      );

      const samples = (watcher?.samples || []).slice(0, 3).map((item) => rowNode(
        item.relative_path || "RAG_Content",
        `${item.state || "changed"} | ${item.current?.dataset_name || "new"} -> ${item.dataset_name || "--"}`,
        item.state || "FILE",
        item.state === "route_changed" ? "warn" : "ok"
      ));
      setRows("queueRows", samples, "QUEUE CLEAN", "RAG watcher has no pending samples");

      const services = (dispatcher?.services || []).slice(0, 4).map((svc) => rowNode(
        svc.title || svc.key || "service",
        `${svc.label || ""} | pid ${svc.pid || svc.port_pid || "--"} | :${svc.port || "--"}`,
        svc.running ? (svc.health || "UP") : "DOWN",
        svc.running && svc.health === "ok" ? "ok" : svc.running ? "warn" : "err"
      ));
      setRows("serviceRows", services, "NO SERVICES", "runtime dispatcher did not return services");

      const mailRows = [
        rowNode("IMAP", `${imap.host || "not configured"} | folders ${(imap.folders || []).join(", ") || "INBOX"}`, imap.enabled ? "ON" : "OFF", imap.enabled ? "ok" : "warn"),
        rowNode("Apple Mail", `${appleMail.root || "~/Library/Mail"}`, appleMail.status || "WAIT", toneForState(appleMail.status === "ready" ? "READY" : appleMail.status)),
        rowNode("Attachments", "OCR/VLM layer feeds mail-vector profile", "OCR", "ok"),
      ];
      setRows("mailRows", mailRows);

      const serviceState = services.some((node) => node.textContent.includes("DOWN")) ? "CHECK" : "LOCAL";
      setText("serviceState", serviceState);
      setText("queueState", pending ? "WORK" : "SCAN");
      setText("mailLayerState", mailStatus === "ready" ? "PROFILE" : "SETUP");

      const err = apiError ? ` | ${apiError.message || apiError}` : "";
      state.lastOk = isOffline ? state.lastOk : new Date().toLocaleTimeString("ru-RU");
      setText(
        "tickerText",
        `M5 1280x720 // ${reindexLabel} ${fmt(completed)}/${fmt(total)} // MEM ${memoryState} ${oneDecimal(memory.ram_free_gb)}GB // MAIL ${mailStatus.toUpperCase()} // updated ${state.lastOk || "--"}${err}`
      );
    }

    async function refresh() {
      state.frame += 1;
      const results = await Promise.allSettled([
        request("/api/indexing-mode"),
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
      setText("clock", new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }));
    }

    drawPixelOwl("boot");
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
