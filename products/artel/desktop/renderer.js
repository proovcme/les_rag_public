// АРТЕЛЬ морда — общается с локальным бэкендом по HTTP. Без сборки, ванильный JS.

const ARCHETYPES = ["rect_cabinet", "panel", "bar_profile", "cylinder_revolve"];

function backendUrl() {
  return (localStorage.getItem("artel_backend") || "http://127.0.0.1:5057").replace(/\/$/, "");
}

async function api(path, opts) {
  const res = await fetch(backendUrl() + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error((await res.text()) || res.status);
  return res.status === 204 ? null : res.json();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

// ── Здоровье бэкенда ─────────────────────────────────────────────
async function checkHealth() {
  const node = document.getElementById("backend-status");
  try {
    await api("/health");
    node.textContent = "бэкенд: ok";
    node.className = "status ok";
  } catch {
    node.textContent = "бэкенд недоступен";
    node.className = "status off";
  }
}

// ── Вкладки ──────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "specs") loadSpecs();
    if (btn.dataset.tab === "jobs") loadJobs();
    if (btn.dataset.tab === "catalog") loadCatalog();
  });
});

// ── Спецификации ─────────────────────────────────────────────────
async function loadSpecs() {
  const list = document.getElementById("spec-list");
  list.innerHTML = "";
  try {
    const specs = await api("/api/specs");
    if (!specs.length) list.innerHTML = "<li class='muted'>Пусто. Извлеките из техлиста.</li>";
    specs.forEach((s) => {
      const li = el(`<li><b>${s.name || "(без имени)"}</b><span class="badge ${s.status}">${s.status}</span><div class="sub">${s.category || ""}</div></li>`);
      li.addEventListener("click", () => openSpec(s.id));
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class='off'>Ошибка: ${e.message}</li>`;
  }
}

async function openSpec(id) {
  const detail = document.getElementById("spec-detail");
  const rec = await api("/api/specs/" + id);
  const spec = rec.spec || {};
  const types = (spec.types || []).map((t) => `<tr><td>${t.name}</td><td>${Object.entries(t.values || {}).map(([k, v]) => k + "=" + v).join(", ")}</td></tr>`).join("");
  const params = (spec.parameters || []).map((p) => `<li>${p.name} <span class="muted">(${p.source}${p.sharedParameterGuid ? ", GUID" : ""})</span></li>`).join("");
  const arch = rec.geometry ? rec.geometry.archetype : "";
  detail.innerHTML = `
    <h2>${spec.familyName || ""}</h2>
    <div class="muted">${spec.revitCategory || ""} · статус: ${rec.status}</div>
    <h3>Параметры</h3><ul class="params">${params}</ul>
    <h3>Типоразмеры (${(spec.types || []).length})</h3>
    <table class="types"><tr><th>Тип</th><th>Габариты, мм</th></tr>${types}</table>
    <h3>Геометрия (архетип)</h3>
    <select id="arch-select">${ARCHETYPES.map((a) => `<option ${a === arch ? "selected" : ""}>${a}</option>`).join("")}</select>
    <div class="actions">
      <button id="btn-approve" ${rec.status === "approved" ? "disabled" : ""}>Утвердить</button>
      <button id="btn-generate" class="primary">Сгенерировать в Revit</button>
    </div>
    <div id="spec-msg" class="muted"></div>`;

  document.getElementById("btn-approve").onclick = async () => {
    await saveArchetype(id);
    await api("/api/specs/" + id + "/approve", { method: "POST" });
    openSpec(id); loadSpecs();
  };
  document.getElementById("btn-generate").onclick = async () => {
    await saveArchetype(id);
    if (rec.status !== "approved") await api("/api/specs/" + id + "/approve", { method: "POST" });
    try {
      const job = await api("/api/revit/jobs", { method: "POST", body: JSON.stringify({ spec_id: id }) });
      document.getElementById("spec-msg").textContent = `Задание #${job.id} поставлено в очередь. Откройте Revit — плагин заберёт его.`;
    } catch (e) {
      document.getElementById("spec-msg").textContent = "Ошибка: " + e.message;
    }
  };
}

async function saveArchetype(id) {
  const rec = await api("/api/specs/" + id);
  const spec = rec.spec || {};
  const archetype = document.getElementById("arch-select").value;
  // авто-биндинг: первые габаритные параметры → width/depth/height
  const dims = (spec.parameters || []).filter((p) => p.dataType === "Length").map((p) => p.name);
  const bindings = {};
  if (archetype === "cylinder_revolve") { bindings.diameter = dims[0]; bindings.height = dims[1]; }
  else { bindings.width = dims[0]; bindings.depth = dims[1]; bindings.height = dims[2] || dims[1]; }
  await api("/api/specs/" + id, {
    method: "PUT",
    body: JSON.stringify({ geometry: { schema_version: "artel.family_geometry.v1", archetype, bindings } }),
  });
}

document.getElementById("btn-refresh-specs").onclick = loadSpecs;
document.getElementById("btn-extract").onclick = async () => {
  const path = await window.artel.pickPdf();
  if (!path) return;
  const name = prompt("Наименование семейства:", path.split(/[\\/]/).pop().replace(/\.pdf$/i, ""));
  if (!name) return;
  const category = prompt("Категория Revit:", "Mechanical Equipment") || "Specialty Equipment";
  try {
    await api("/api/extract/pdf", { method: "POST", body: JSON.stringify({ path, name, category }) });
    loadSpecs();
  } catch (e) {
    alert("Не удалось извлечь: " + e.message);
  }
};

// ── Задания ──────────────────────────────────────────────────────
async function loadJobs() {
  const list = document.getElementById("job-list");
  list.innerHTML = "";
  const jobs = await api("/api/revit/jobs");
  if (!jobs.length) list.innerHTML = "<li class='muted'>Заданий нет.</li>";
  jobs.forEach((j) => {
    const li = el(`<li>#${j.id} <span class="badge ${j.status}">${j.status}</span></li>`);
    li.addEventListener("click", () => openJob(j.id));
    list.appendChild(li);
  });
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

async function openJob(id) {
  const j = await api("/api/revit/jobs/" + id);
  const detail = document.getElementById("job-detail");
  let report;
  if (!j.report) {
    report = "<p class='muted'>Отчёта пока нет — ждём Revit.</p>";
  } else {
    const r = j.report;
    const rows = (r.results || [])
      .map((o) => `<tr class="${o.status}"><td><span class="badge ${o.status}">${o.status}</span></td>`
        + `<td>${esc(o.op)}${o.target ? " / " + esc(o.target) : ""}</td><td>${esc(o.message)}</td></tr>`)
      .join("");
    report = `<div class="muted">операций: ${r.operation_count ?? "?"} · ok: ${r.executed_count ?? "?"} · фейлов: ${r.failed_count ?? 0}</div>`
      + (rows ? `<table class="results"><tr><th></th><th>Операция</th><th>Сообщение</th></tr>${rows}</table>`
              : `<pre>${esc(JSON.stringify(r, null, 2))}</pre>`);
  }
  const canAccept = j.status === "done";
  detail.innerHTML =
    `<h2>Задание #${j.id}</h2><div class="muted">статус: ${j.status}</div>`
    + (canAccept ? `<div class="actions"><button id="btn-accept" class="primary">Принять в каталог</button></div>` : "")
    + `<h3>Отчёт</h3>${report}<div id="job-msg" class="muted"></div>`;

  if (canAccept) {
    document.getElementById("btn-accept").onclick = async () => {
      try {
        const c = await api("/api/revit/jobs/" + id + "/accept", { method: "POST" });
        document.getElementById("job-msg").textContent = `Принято в каталог: ${c.name} (#${c.id}).`;
      } catch (e) {
        document.getElementById("job-msg").textContent = "Ошибка: " + e.message;
      }
    };
  }
}

// ── Каталог ──────────────────────────────────────────────────────
async function loadCatalog() {
  const list = document.getElementById("catalog-list");
  const query = (document.getElementById("catalog-search").value || "").trim();
  list.innerHTML = "";
  try {
    const items = await api("/api/catalog" + (query ? "?query=" + encodeURIComponent(query) : ""));
    if (!items.length) { list.innerHTML = "<li class='muted'>Каталог пуст. Принимайте успешные задания.</li>"; return; }
    items.forEach((c) => {
      list.appendChild(el(
        `<li><b>${esc(c.name) || "(без имени)"}</b><span class="badge">${esc(c.archetype)}</span>`
        + `<div class="sub">${esc(c.category)}${c.rfa_path ? " · " + esc(c.rfa_path) : ""}</div></li>`));
    });
  } catch (e) {
    list.innerHTML = `<li class='off'>Ошибка: ${esc(e.message)}</li>`;
  }
}

document.getElementById("btn-refresh-jobs").onclick = loadJobs;
document.getElementById("btn-refresh-catalog").onclick = loadCatalog;
document.getElementById("catalog-search").addEventListener("input", () => {
  clearTimeout(window._catTimer);
  window._catTimer = setTimeout(loadCatalog, 250);
});

// ── Настройки ────────────────────────────────────────────────────
const urlInput = document.getElementById("backend-url");
urlInput.value = backendUrl();
urlInput.addEventListener("change", () => {
  localStorage.setItem("artel_backend", urlInput.value);
  checkHealth();
});

// ── Старт ────────────────────────────────────────────────────────
checkHealth();
loadSpecs();
setInterval(checkHealth, 5000);
