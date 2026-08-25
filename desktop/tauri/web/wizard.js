const invoke = window.__TAURI__?.core?.invoke;
const $ = (id) => document.getElementById(id);
let snapshot = null;
let busy = false;
let refreshing = false;

function setDot(id, tone) {
  const node = $(id);
  if (node) node.className = `dot ${tone || ""}`.trim();
}

function providerById(data, id) {
  return (data.providers || []).find((provider) => provider.id === id) || {};
}

function renderProvider(data, id) {
  const provider = providerById(data, id);
  const tone = provider.available ? "ok" : provider.configured || provider.installed ? "warn" : "";
  setDot(`provider-${id}-dot`, tone);
  $(`provider-${id}-status`).textContent = provider.available
    ? provider.configured ? "выбран · отвечает" : "обнаружен"
    : provider.configured ? "выбран · не отвечает" : "не обнаружен";
}

function render(data) {
  snapshot = data;
  const bootstrap = data.bootstrap || {};
  const failed = bootstrap.state === "failed";
  const preparing = ["running", undefined].includes(bootstrap.state);
  const canStart = Boolean(data.ui_ready || (data.core_ready && !failed && !preparing));
  $("overall-state").textContent = failed ? "Ошибка ЛЕС" : data.ui_ready ? "ЛЕС работает" : preparing ? "Подготовка…" : canStart ? "ЛЕС готов" : "Нужна проверка";
  $("overall-state").dataset.tone = failed ? "danger" : preparing || !canStart ? "warning" : "";
  $("notice").classList.toggle("visible", failed);
  $("notice").textContent = failed
    ? `${bootstrap.message || "Не удалось подготовить ЛЕС"}${bootstrap.code ? ` · Код: ${bootstrap.code}` : ""}${bootstrap.log_path ? ` · Журнал: ${bootstrap.log_path}` : ""}`
    : "";
  setDot("runtime-dot", canStart ? "ok" : failed ? "warn" : "");
  $("runtime-status").textContent = failed
    ? "Встроенная среда повреждена или не подготовилась"
    : data.ui_ready ? "Службы ЛЕС запущены" : preparing ? bootstrap.message || "Подготавливаю встроенную среду…" : "Встроенная среда готова";
  ["ollama", "freetoken", "lemonade", "openai-compatible"].forEach((id) => renderProvider(data, id));
  const embeddings = data.embeddings || [];
  const embeddingReady = embeddings.some((item) => item.available);
  const embeddingConfigured = embeddings.some((item) => item.configured);
  setDot("embedding-dot", embeddingReady ? "ok" : embeddingConfigured ? "warn" : "");
  $("embedding-status").textContent = embeddingReady
    ? `Готов: ${embeddings.filter((item) => item.available).map((item) => item.label).join(", ")}`
    : embeddingConfigured ? "Настроен, но не отвечает" : "Не настроен";
  const qdrantReady = Boolean(data.qdrant?.running);
  const dockerReady = Boolean(data.docker?.running);
  setDot("qdrant-dot", qdrantReady ? "ok" : dockerReady ? "warn" : "");
  $("qdrant-status").textContent = qdrantReady
    ? "Qdrant отвечает"
    : dockerReady ? "Docker работает; Qdrant пока не отвечает" : data.docker?.installed ? "Docker установлен, но не запущен" : "Qdrant и Docker не обнаружены";
  $("start").disabled = busy || !canStart;
  $("start").textContent = data.ui_ready ? "Открыть ЛЕС" : preparing ? "Подготовка…" : "Запустить ЛЕС";
  $("refresh").textContent = failed ? "Повторить подготовку" : "Проверить снова";
  $("footer-copy").textContent = failed
    ? "Проверьте код ошибки и журнал; внешние движки не могут повредить встроенную среду ЛЕС."
    : "Внешние компоненты не блокируют запуск ЛЕС; недоступные функции будут отмечены внутри приложения.";
}

async function refresh() {
  if (!invoke || busy || refreshing) return;
  refreshing = true;
  try { render(await invoke("setup_snapshot")); }
  catch (error) {
    $("notice").classList.add("visible");
    $("notice").textContent = `Не удалось проверить состояние: ${error}`;
  } finally { refreshing = false; }
}

async function runBusy(action) {
  busy = true;
  if (snapshot) render(snapshot);
  try { await action(); }
  catch (error) {
    $("notice").classList.add("visible");
    $("notice").textContent = String(error);
  } finally {
    busy = false;
    await refresh();
  }
}

$("refresh").addEventListener("click", () => {
  if (snapshot?.bootstrap?.state === "failed") runBusy(() => invoke("retry_setup"));
  else refresh();
});
$("start").addEventListener("click", () => runBusy(() => invoke("start_from_setup")));
document.querySelectorAll("[data-link]").forEach((button) => button.addEventListener("click", () => invoke("open_setup_link", { kind: button.dataset.link })));

refresh();
window.setInterval(refresh, 10000);
