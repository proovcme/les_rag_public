/*
 * taskpane.js — «В ЛЕС»
 *
 * Что делает:
 *   1. Читает текущее письмо (тема, отправитель, дата, тело plain-text, вложения).
 *   2. По кнопке собирает JSON по контракту ЛЕС и шлёт POST <URL>/api/mail/push.
 *   3. Показывает ответ: routed[] (что куда уехало) и kac (если был).
 *
 * Контракт запроса (строго):
 *   {
 *     "subject": str,
 *     "from": str,
 *     "date": str,                 // ISO8601
 *     "body": str,                 // plain text
 *     "attachments": [ {"name": str, "content_type": str, "content_b64": str} ]
 *   }
 * Контракт ответа:
 *   { "ok": true, "message_id": str,
 *     "routed": [{"name":..,"kind":..,"destination":..}], "kac": {..|null} }
 */

const DEFAULT_LES_URL = "http://localhost:8050";
const SETTINGS_KEY = "les_url";

let CURRENT_ITEM = null;

// ---------- утилиты ----------

function $(id) { return document.getElementById(id); }

function setStatus(text, kind) {
  const el = $("status");
  el.className = "status" + (kind ? " " + kind : "");
  el.innerHTML = text;
}

function humanSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " Б";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " КБ";
  return (bytes / (1024 * 1024)).toFixed(1) + " МБ";
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Нормализуем базовый URL: убрать хвостовой слэш.
function normalizeBase(url) {
  return (url || "").trim().replace(/\/+$/, "");
}

// ---------- настройки (URL ЛЕС) ----------
// roamingSettings доступен в полном Office-окружении; localStorage — фолбэк
// (например, при открытии HTML вне Outlook). Пишем в оба.

function loadLesUrl() {
  let url = null;
  try {
    if (Office.context && Office.context.roamingSettings) {
      url = Office.context.roamingSettings.get(SETTINGS_KEY);
    }
  } catch (e) { /* нет окружения Office */ }
  if (!url) {
    try { url = localStorage.getItem(SETTINGS_KEY); } catch (e) {}
  }
  return url || DEFAULT_LES_URL;
}

function saveLesUrl(url) {
  try { localStorage.setItem(SETTINGS_KEY, url); } catch (e) {}
  try {
    if (Office.context && Office.context.roamingSettings) {
      Office.context.roamingSettings.set(SETTINGS_KEY, url);
      Office.context.roamingSettings.saveAsync(); // best-effort, без блокировки UI
    }
  } catch (e) {}
}

// ---------- чтение письма ----------

function fromToString(from) {
  // item.from: { displayName, emailAddress }
  if (!from) return "";
  const name = from.displayName || "";
  const addr = from.emailAddress || "";
  if (name && addr) return `${name} <${addr}>`;
  return addr || name;
}

function renderHeader(item) {
  $("subject").textContent = item.subject || "(без темы)";
  $("from").textContent = fromToString(item.from) || "—";

  // дата получения письма
  let dateStr = "—";
  if (item.dateTimeCreated) {
    try { dateStr = new Date(item.dateTimeCreated).toLocaleString("ru-RU"); }
    catch (e) { dateStr = String(item.dateTimeCreated); }
  }
  $("date").textContent = dateStr;

  // вложения
  const ul = $("attachments");
  const atts = item.attachments || [];
  ul.innerHTML = "";
  if (!atts.length) {
    ul.innerHTML = '<li class="att-size">нет вложений</li>';
    return;
  }
  for (const a of atts) {
    const li = document.createElement("li");
    const inline = a.isInline ? " (встроенное)" : "";
    li.innerHTML =
      escapeHtml(a.name) +
      ' <span class="att-size">' + escapeHtml(humanSize(a.size)) + inline + "</span>";
    ul.appendChild(li);
  }
}

// тело письма как plain text
function getBodyText(item) {
  return new Promise((resolve, reject) => {
    item.body.getAsync(Office.CoercionType.Text, (res) => {
      if (res.status === Office.AsyncResultStatus.Succeeded) {
        resolve(res.value || "");
      } else {
        reject(res.error);
      }
    });
  });
}

// ISO8601-дата письма
function getIsoDate(item) {
  const d = item.dateTimeCreated ? new Date(item.dateTimeCreated) : new Date();
  return d.toISOString();
}

// ---------- вложения в Base64 ----------
// item.getAttachmentContentAsync возвращает content + формат.
// Outlook отдаёт формат Base64 для большинства файлов, но также может вернуть
// Url (например, ссылки) или Eml/ICalendar. Мы обрабатываем именно Base64-байты;
// прочие форматы помечаем и пропускаем, чтобы не слать мусор.

function getOneAttachmentB64(item, att) {
  return new Promise((resolve) => {
    item.getAttachmentContentAsync(att.id, (res) => {
      if (res.status !== Office.AsyncResultStatus.Succeeded) {
        resolve({ skipped: true, name: att.name, reason: (res.error && res.error.message) || "ошибка чтения" });
        return;
      }
      const content = res.value;
      // content.format: "base64" | "url" | "eml" | "iCalendar"
      if (content.format === Office.MailboxEnums.AttachmentContentFormat.Base64) {
        resolve({
          name: att.name,
          content_type: att.contentType || "application/octet-stream",
          content_b64: content.content, // уже base64-строка
        });
      } else {
        resolve({ skipped: true, name: att.name, reason: "формат " + content.format + " не поддержан" });
      }
    });
  });
}

async function collectAttachments(item) {
  const atts = (item.attachments || []).filter((a) => !a.isInline);
  const out = [];
  const skipped = [];
  for (const a of atts) {
    // последовательно, чтобы не упереться в лимиты Office на параллельные async-вызовы
    const r = await getOneAttachmentB64(item, a);
    if (r.skipped) skipped.push(r);
    else out.push(r);
  }
  return { attachments: out, skipped };
}

// ---------- сборка payload и отправка ----------

async function buildPayload(item) {
  const [body, attRes] = await Promise.all([
    getBodyText(item),
    collectAttachments(item),
  ]);
  const payload = {
    subject: item.subject || "",
    from: fromToString(item.from),
    date: getIsoDate(item),
    body: body,
    attachments: attRes.attachments,
  };
  return { payload, skipped: attRes.skipped };
}

function renderResult(data) {
  const box = $("result");
  let html = "";

  if (data.message_id) {
    html += '<div class="row"><span class="label">message_id</span> ' +
            escapeHtml(data.message_id) + "</div>";
  }

  const routed = data.routed || [];
  if (routed.length) {
    html += '<table><thead><tr><th>Файл/часть</th><th>Тип</th><th>Куда</th></tr></thead><tbody>';
    for (const r of routed) {
      html += "<tr><td>" + escapeHtml(r.name) + "</td><td>" +
              escapeHtml(r.kind) + "</td><td>" + escapeHtml(r.destination) + "</td></tr>";
    }
    html += "</tbody></table>";
  } else {
    html += '<div class="hint">ЛЕС не вернул маршрутизацию (routed пуст).</div>';
  }

  if (data.kac) {
    html += '<div class="kac"><h3>КАЦ-итог</h3><pre>' +
            escapeHtml(JSON.stringify(data.kac, null, 2)) + "</pre></div>";
  }

  box.innerHTML = html;
}

async function onSend() {
  const btn = $("sendBtn");
  const base = normalizeBase($("lesUrl").value);
  if (!base) {
    setStatus("Укажи URL ЛЕС.", "err");
    return;
  }
  saveLesUrl(base);

  btn.disabled = true;
  $("result").innerHTML = "";
  setStatus('<span class="spinner"></span>Читаю письмо и вложения…');

  let payload, skipped;
  try {
    const built = await buildPayload(CURRENT_ITEM);
    payload = built.payload;
    skipped = built.skipped;
  } catch (e) {
    setStatus("Не удалось прочитать письмо: " + escapeHtml((e && e.message) || e), "err");
    btn.disabled = false;
    return;
  }

  const url = base + "/api/mail/push";
  setStatus('<span class="spinner"></span>Отправляю в ЛЕС…');

  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      setStatus("ЛЕС ответил " + resp.status + " " + escapeHtml(resp.statusText) +
                (txt ? ": " + escapeHtml(txt.slice(0, 300)) : ""), "err");
      btn.disabled = false;
      return;
    }

    const data = await resp.json();
    let okMsg = "Готово.";
    if (skipped && skipped.length) {
      okMsg += " Пропущено вложений: " + skipped.length +
               " (" + escapeHtml(skipped.map((s) => s.name).join(", ")) + ").";
    }
    setStatus(okMsg, "ok");
    renderResult(data);
  } catch (e) {
    // Самый частый кейс на личном ноуте — mixed content / CORS / нет соединения.
    setStatus(
      "Сеть/CORS: не удалось достучаться до ЛЕС по " + escapeHtml(url) + ". " +
      "Если таскпейн открыт по https, а ЛЕС по http — браузер блокирует запрос " +
      "(mixed content). Рецепты в README → раздел «mixed content».",
      "err"
    );
  } finally {
    btn.disabled = false;
  }
}

// ---------- инициализация ----------

Office.onReady((info) => {
  // info.host === Office.HostType.Outlook
  $("lesUrl").value = loadLesUrl();
  $("lesUrl").addEventListener("change", () => saveLesUrl(normalizeBase($("lesUrl").value)));
  $("sendBtn").addEventListener("click", onSend);

  try {
    CURRENT_ITEM = Office.context.mailbox.item;
    if (CURRENT_ITEM) {
      renderHeader(CURRENT_ITEM);
      setStatus("");
    } else {
      setStatus("Нет открытого письма. Открой письмо и нажми кнопку снова.", "err");
    }
  } catch (e) {
    // открыто вне Outlook (например, просто в браузере для вёрстки)
    $("attachments").innerHTML = '<li class="att-size">вне Outlook — письмо недоступно</li>';
    setStatus("Запущено вне Outlook: доступна только вёрстка.", "");
  }
});
