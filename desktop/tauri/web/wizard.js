const invoke = window.__TAURI__?.core?.invoke;
const $ = (id) => document.getElementById(id);
let snapshot = null;
let busy = false;
let refreshing = false;

function setDot(id, tone) {
  const node = $(id);
  node.className = `dot ${tone || ""}`.trim();
}

function answerModels(models) {
  return (models || []).filter((name) => !name.toLowerCase().startsWith("bge-m3"));
}

function render(data) {
  snapshot = data;
  const bootstrap = data.bootstrap || {};
  const failed = bootstrap.state === "failed";
  const preparing = ["running", undefined].includes(bootstrap.state);
  $("overall-state").textContent = failed ? "Нужна помощь" : data.can_start ? "Всё готово" : preparing ? "Подготовка…" : "Нужна настройка";
  $("overall-state").dataset.tone = failed ? "danger" : data.can_start ? "" : "warning";

  $("notice").classList.toggle("visible", failed);
  $("notice").textContent = failed
    ? `${bootstrap.message || "Не удалось завершить подготовку"}${bootstrap.code ? ` · Код: ${bootstrap.code}` : ""}${bootstrap.log_path ? ` · Журнал: ${bootstrap.log_path}` : ""}`
    : "";

  const runtimeReady = !failed && !preparing;
  setDot("runtime-dot", runtimeReady ? "ok" : failed ? "warn" : "");
  $("runtime-status").textContent = failed ? "Подготовка остановилась — смотрите сообщение выше" : runtimeReady ? "Python и uv подготовлены" : bootstrap.message || "Подготавливаю…";

  const ollama = data.ollama || {};
  setDot("ollama-dot", ollama.running ? "ok" : ollama.installed ? "warn" : "");
  $("ollama-status").textContent = ollama.running ? "Ollama установлена и отвечает" : ollama.installed ? "Установлена, но не запущена" : "Не установлена";
  $("install-ollama").disabled = busy || ollama.installed;

  const models = answerModels(data.models);
  const select = $("model-select");
  const previous = select.value;
  select.innerHTML = models.length ? "" : '<option value="">Нет установленных моделей</option>';
  models.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name === data.recommended_model ? `${name} · рекомендуем` : name;
    select.appendChild(option);
  });
  const preferred = models.includes(data.selected_model) ? data.selected_model : models.includes(previous) ? previous : models[0] || "";
  select.value = preferred;
  setDot("model-dot", preferred ? "ok" : "");
  $("model-status").textContent = preferred ? `Выбрана ${preferred}` : "Сначала загрузите модель через Ollama";

  setDot("embedding-dot", data.embedding_present ? "ok" : "");
  $("embedding-status").textContent = data.embedding_present ? "bge-m3 установлена" : "bge-m3 пока не установлена";

  const docker = data.docker || {};
  setDot("docker-dot", docker.running ? "ok" : docker.installed ? "warn" : "");
  $("docker-status").textContent = docker.running
    ? data.qdrant?.running ? "Docker и Qdrant работают" : "Docker работает; Qdrant запустит ЛЕС"
    : docker.installed ? "Docker установлен — запустите Desktop и завершите WSL 2" : "Docker Desktop не установлен";
  $("install-docker").disabled = busy || docker.installed;

  const canStart = Boolean(data.ui_ready || (ollama.running && docker.running && preferred && data.embedding_present && !failed));
  setDot("ready-dot", canStart ? "ok" : "warn");
  $("ready-status").textContent = data.ui_ready ? "ЛЕС уже запущен; можно закрыть справку" : canStart ? "Можно запускать" : "Завершите отмеченные шаги";
  $("start").disabled = busy || !canStart;
  $("start").textContent = data.ui_ready ? "Открыть ЛЕС" : "Запустить ЛЕС";
  $("refresh").textContent = failed ? "Повторить подготовку" : "Проверить снова";
}

async function refresh() {
  if (!invoke || busy || refreshing) return;
  refreshing = true;
  try {
    render(await invoke("setup_snapshot"));
  } catch (error) {
    $("notice").classList.add("visible");
    $("notice").textContent = `Не удалось проверить состояние: ${error}`;
  } finally {
    refreshing = false;
  }
}

async function runBusy(action) {
  busy = true;
  if (snapshot) render(snapshot);
  try { await action(); } catch (error) {
    $("notice").classList.add("visible");
    $("notice").textContent = String(error);
  } finally {
    busy = false;
    await refresh();
  }
}

$("install-ollama").addEventListener("click", () => runBusy(() => invoke("install_setup_component", { component: "ollama" })));
$("install-docker").addEventListener("click", () => runBusy(() => invoke("install_setup_component", { component: "docker" })));
$("refresh").addEventListener("click", () => {
  if (snapshot?.bootstrap?.state === "failed") {
    runBusy(() => invoke("retry_setup"));
  } else {
    refresh();
  }
});
$("start").addEventListener("click", () => runBusy(() => invoke("start_from_setup", { model: $("model-select").value })));
$("model-select").addEventListener("change", () => {
  if (snapshot) render({ ...snapshot, selected_model: $("model-select").value });
});
document.querySelectorAll("[data-link]").forEach((button) => button.addEventListener("click", () => invoke("open_setup_link", { kind: button.dataset.link })));
document.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", async () => {
  await navigator.clipboard.writeText(button.dataset.copy);
  const label = button.textContent;
  button.textContent = "Скопировано";
  window.setTimeout(() => { button.textContent = label; }, 1400);
}));

refresh();
window.setInterval(refresh, 2500);
