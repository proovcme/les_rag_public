const invoke = window.__TAURI__?.core?.invoke;
const $ = (id) => document.getElementById(id);
let snapshot = null;
let busy = false;
let refreshing = false;
let preparingStartedAt = 0;
let pollTimer = null;

function setDot(id, tone) {
  const node = $(id);
  if (node) node.className = `dot ${tone || ""}`.trim();
}

function providerById(data, id) {
  return (data.providers || []).find((provider) => provider.id === id) || {};
}

function setPoll(ms) {
  window.clearInterval(pollTimer);
  pollTimer = window.setInterval(refresh, ms);
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
  const preparing = bootstrap.state === "running" && !data.ui_ready;
  if (preparing) {
    if (!preparingStartedAt) preparingStartedAt = Date.now();
  } else {
    preparingStartedAt = 0;
  }
  const stale = preparing && preparingStartedAt && (Date.now() - preparingStartedAt > 120000);
  const canStart = Boolean(data.ui_ready || stale || (data.core_ready && !failed && !preparing));
  $("overall-state").textContent = failed ? "Ошибка ЛЕС" : data.ui_ready ? "ЛЕС работает" : preparing && !stale ? "Подготовка…" : canStart ? "ЛЕС готов" : "Нужна проверка";
  $("overall-state").dataset.tone = failed ? "danger" : preparing || !canStart ? "warning" : "";
  const staleNotice = "Подготовка идёт дольше обычного. Можно открыть журнал и повторить запуск; внешние движки это не блокируют.";
  $("notice").classList.toggle("visible", failed || stale);
  $("notice").textContent = failed
    ? `${bootstrap.message || "Не удалось подготовить ЛЕС"}${bootstrap.code ? ` · Код: ${bootstrap.code}` : ""}${bootstrap.log_path ? ` · Журнал: ${bootstrap.log_path}` : ""}`
    : stale ? staleNotice : "";
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
  $("start").textContent = data.ui_ready ? "Открыть ЛЕС" : preparing && !stale ? "Подготовка…" : "Запустить ЛЕС";
  $("refresh").textContent = failed || stale ? "Повторить подготовку" : "Проверить снова";
  $("footer-copy").textContent = failed
    ? "Проверьте код ошибки и журнал; внешние движки не могут повредить встроенную среду ЛЕС."
    : "Внешние компоненты не блокируют запуск ЛЕС; недоступные функции будут отмечены внутри приложения.";
  setPoll(preparing && !stale ? 2000 : 10000);
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
  const failed = snapshot?.bootstrap?.state === "failed";
  const preparingNow = snapshot?.bootstrap?.state === "running" && !snapshot?.ui_ready;
  const staleNow = preparingNow && preparingStartedAt && (Date.now() - preparingStartedAt > 120000);
  if (failed || staleNow) runBusy(() => invoke("retry_setup"));
  else refresh();
});
$("start").addEventListener("click", () => runBusy(() => invoke("start_from_setup")));
document.querySelectorAll("[data-link]").forEach((button) => button.addEventListener("click", () => invoke("open_setup_link", { kind: button.dataset.link })));

refresh();
pollTimer = window.setInterval(refresh, 10000);
