# Алгоритм: приёмка почты (Outlook → /api/mail/push → классификация вложений)

Письмо из Outlook одним нажатием уходит в **локальный** ЛЕС, который детерминированно
раскладывает вложения по назначению: КП → КАЦ, смета/ВОР → RAG, скан → приёмка ИД, прочее →
RAG-документ. Канал недоверенный: плагин шлёт в **локальный** ЛЕС (не в облако) —
[[cloudflare-blocked-use-openai-direct]], локаль-первый. 0 LLM в маршрутизации (regex/тип файла).

## Конвейер

```
Outlook (Mac/Win) + Add-in → POST /api/mail/push (тело + вложения base64) →
  save_attachments (раскодировать в storage/mail_push/<msg_id>/) →
  route_push (классификация каждого вложения) →
    КП        → КАЦ (kac_pdf_service.extract_and_analyze, best-effort)
    смета/ВОР → RAG · смета/ВОР (upload в датасет)
    скан      → приёмка ИД (очередь, status=pending)
    прочее    → RAG · документ
  тело письма → текстовый файл → RAG (mail-датасет)
```

## Классификация вложения (`route_push`, детерминированно)

| Класс | Сигнал | Назначение |
|---|---|---|
| **КП** | PDF + подсказки (кп, коммерч, предложен, прайс, счёт, offer, price) | КАЦ (≥3 КП → выбор) |
| **смета/ВОР** | подсказки (смет, вор, лср, кс2, кс3, локальн) ИЛИ `.xlsx/.xls` | RAG · смета/ВОР |
| **скан** | `.jpg/.png/.tif/.bmp/.heic` + подсказки (скан, акт, исполнит, обмер) | приёмка ИД (pending) |
| **документ** | всё прочее (дефолт) | RAG · документ |

КП и сканы **не идут** в основной RAG (КП → КАЦ-анализ, скан → журнал объёмов через приёмку ИД).
КАЦ по КП выполняется best-effort (не блокирует ответ). Ответ `/api/mail/push`:
`{ok, message_id, dataset_id, routed:[{name,kind,destination}], kac:{…}, uploaded:[{doc_id,name}]}`.

## Эндпоинт

- `POST /api/mail/push` (auth) — принимает `{subject, from, date, body, attachments:[{name,
  content_type, content_b64}]}`. Сервис — `proxy/services/mail_push_service.py`, роутер —
  `proxy/routers/mail.py`. Хранилище вложений — `storage/mail_push/<msg_id>/`.

## Плагин Outlook — `clients/outlook_addin/`

JS-надстройка (Outlook desktop + web): кнопка в ленте → таскпейн читает текущее письмо
(`Office.context.mailbox.item`: тема/отправитель/тело/вложения) → собирает JSON →
`POST /api/mail/push` в локальный ЛЕС → показывает таблицу `routed[]` + блок КАЦ. Файлы:
`manifest.xml` (метаданные/кнопка), `src/taskpane.{html,js}` (UI + отправка).

**Mixed content (Office требует HTTPS для таскпейна, ЛЕС по HTTP):** варианты — оба по HTTP
(desktop, `serve-http`), оба по HTTPS (dev-сертификаты + https-прокси :8443→:8050), или dev-флаг
Chrome. Подробности — в README плагина.

## Legion (Outlook на Windows) + SSH-туннель

Outlook+плагин крутятся на Легионе (Windows), ЛЕС — на Маке. Обратный SSH-туннель
`tools/legion_mail_tunnel.sh` пробрасывает `localhost:8050` Легиона → `127.0.0.1:8050` Мака
(`-R`, bind на localhost): плагин шлёт на `http://localhost:8050/api/mail/push` → приходит в
локальный ЛЕС через SSH. Env: `LES_LEGION_SSH` (alias из `~/.ssh/config`, дефолт `legion`),
`LES_PORT` (дефолт 8050). Авто-переподключение каждые 5с, keepalive 30с.

## Где в коде

- Сервис: `proxy/services/mail_push_service.py` (`save_attachments`/`route_push`),
  `proxy/services/kac_pdf_service.py` (КП → КАЦ).
- Роутер: `proxy/routers/mail.py` (`POST /api/mail/push`; рядом — `import-imap`/`import-archive`).
- Клиент: `clients/outlook_addin/`. Туннель: `tools/legion_mail_tunnel.sh`.

## Граница (что осталось)

- `.pst` (Windows-архив) требует `libpff`; `.msg` индексируется как файл.
- Предложено дальше: почта → задачи → график (письмо-поручение → задачник → план работ).
