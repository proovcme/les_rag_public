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

async function openJob(id) {
  const j = await api("/api/revit/jobs/" + id);
  const report = j.report
    ? `<pre>${JSON.stringify(j.report, null, 2)}</pre>`
    : "<p class='muted'>Отчёта пока нет — ждём Revit.</p>";
  document.getElementById("job-detail").innerHTML =
    `<h2>Задание #${j.id}</h2><div class="muted">статус: ${j.status}</div><h3>Отчёт</h3>${report}`;
}

document.getElementById("btn-refresh-jobs").onclick = loadJobs;

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
