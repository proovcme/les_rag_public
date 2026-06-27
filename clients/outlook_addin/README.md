# Outlook Add-in «В ЛЕС»

Кнопка в Outlook, которая шлёт **текущее письмо** (тема, отправитель, дата, тело,
вложения) в локальный ЛЕС: `POST <URL ЛЕС>/api/mail/push`. Ответ ЛЕС (`routed[]` —
что куда уехало, и `kac` — КАЦ-итог) показывается в таскпейне.

Это самодостаточный пакет. Питон/ядро ЛЕС он не трогает. Тестировать без Outlook
нельзя — здесь корректный скаффолд и честная инструкция сайдлоада на **личном**
ноуте (без корп-ограничений).

---

## Дерево файлов

```
clients/outlook_addin/
├── manifest.xml          # манифест Outlook Add-in (MessageReadCommandSurface: кнопка + таскпейн)
├── package.json          # только npx-скрипты dev-сервера/сертификатов (зависимости не ставятся)
├── README.md             # этот файл
├── assets/               # плейсхолдер-иконки (зелёные, валидные PNG)
│   ├── icon-16.png  icon-32.png  icon-64.png  icon-80.png  icon-128.png
└── src/
    ├── taskpane.html     # UI: тема/отправитель/вложения, поле «URL ЛЕС», кнопка, вывод ответа
    ├── taskpane.js       # чтение письма + сбор JSON по контракту + fetch POST
    ├── commands.html     # невидимый host для FunctionFile (точка расширения)
    └── commands.js       # заготовка безпейновых команд (сейчас не активна)
```

---

## Что делает add-in (контракт)

Запрос `POST <URL>/api/mail/push`, `Content-Type: application/json`:

```json
{
  "subject": "string",
  "from": "Имя <addr@host>",
  "date": "2026-06-23T10:00:00.000Z",
  "body": "plain text письма",
  "attachments": [
    { "name": "smeta.xlsx", "content_type": "application/vnd...", "content_b64": "<base64 байтов файла>" }
  ]
}
```

Ответ (рендерится в таскпейне):

```json
{
  "ok": true,
  "message_id": "…",
  "routed": [ { "name": "smeta.xlsx", "kind": "smeta", "destination": "…" } ],
  "kac": { } 
}
```

`routed` показывается таблицей, `kac` (если не `null`) — блоком «КАЦ-итог».

---

## Как читаются вложения (Base64)

1. Список вложений берётся из `Office.context.mailbox.item.attachments`
   (имя, размер, `contentType`, `isInline`). Встроенные (`isInline`) пропускаются —
   это картинки из тела, не файлы.
2. Содержимое каждого вложения запрашивается через
   `item.getAttachmentContentAsync(att.id, cb)` — **последовательно**, чтобы не
   упереться в лимит Office на параллельные async-вызовы.
3. Outlook возвращает `content.format`. Когда формат =
   `Office.MailboxEnums.AttachmentContentFormat.Base64`, поле `content.content` —
   уже готовая base64-строка байтов файла, её и кладём в `content_b64`.
   Прочие форматы (`url`, `eml`, `iCalendar`) не являются байтами файла — такие
   вложения помечаются «пропущено» и в payload не попадают (в статусе видно,
   сколько и какие пропущены).
4. Тело письма берётся как **plain text**: `item.body.getAsync(Office.CoercionType.Text, cb)`.
5. Дата — `item.dateTimeCreated` → `.toISOString()` (ISO8601).

> Доступ к содержимому вложений требует разрешения `ReadWriteMailbox`
> (объявлено в `manifest.xml`). Для одной только темы/тела хватило бы `ReadItem`,
> но контракт требует вложения.

---

## Mixed content — почему ломается и как починить (рабочий рецепт)

Проблема: Office требует, чтобы ассеты таскпейна грузились по **HTTPS**
(`https://localhost:3000`). Но локальный ЛЕС слушает **HTTP**
(`http://localhost:8050`). Браузерный движок таскпейна блокирует
`fetch()` с https-страницы на http-адрес как **mixed content** — запрос
не уходит, в таскпейне видно ошибку «Сеть/CORS».

Ниже три рабочих варианта. **Рекомендация для личного ноута — Вариант A**
(Outlook desktop + таскпейн по http): самый короткий путь без сертификатов на ЛЕС.

### Вариант A (рекомендуется на Mac/Win desktop): таскпейн по HTTP

Outlook **desktop** (в отличие от Outlook on the web) разрешает грузить ассеты
add-in по `http://localhost`. Тогда и таскпейн, и ЛЕС — оба http, mixed content
исчезает.

1. В `manifest.xml` замени **все** `https://localhost:3000` на
   `http://localhost:3000` (это URL ассетов, не ЛЕС). Шесть мест: `IconUrl`,
   `HighResolutionIconUrl`, `SourceLocation`, `Icon.16/32/80`, `Commands.Url`,
   `Taskpane.Url`.
2. Подними http-сервер ассетов из папки add-in:
   ```bash
   cd clients/outlook_addin
   npm run serve-http        # http-server . -p 3000 --cors
   ```
3. Запусти ЛЕС как обычно (http://localhost:8050).
4. Сайдлоад манифеста (см. раздел «Сайдлоад» ниже).
5. В таскпейне поле «URL ЛЕС» = `http://localhost:8050`. Оба http → `fetch` проходит.

> Минус: работает только в Outlook **desktop**. В Outlook on the web http-ассеты
> запрещены — там нужен Вариант B.

### Вариант B: всё по HTTPS (таскпейн https + ЛЕС за https)

Подходит и для Outlook on the web. ЛЕС нужно открыть по https — проще всего
локальным реверс-прокси с самоподписанным сертификатом (сам ЛЕС не трогаем).

1. Поставь dev-сертификаты (доверенный локальный CA):
   ```bash
   cd clients/outlook_addin
   npm run certs            # office-addin-dev-certs install
   ```
   Кладёт `localhost.crt`/`localhost.key` в `~/.office-addin-dev-certs/` и
   добавляет CA в системное доверие (на macOS — в Keychain, спросит пароль).
2. https-сервер ассетов таскпейна (порт 3000) с этими сертификатами:
   ```bash
   npm run serve            # http-server -S -C …localhost.crt -K …localhost.key -p 3000 --cors
   ```
3. Подними https-реверс к ЛЕС на отдельном порту (например 8443 → 8050).
   Вариант на `local-ssl-proxy` (через npx, без установки в проект):
   ```bash
   npx --yes local-ssl-proxy \
     --source 8443 --target 8050 \
     --cert ~/.office-addin-dev-certs/localhost.crt \
     --key  ~/.office-addin-dev-certs/localhost.key
   ```
4. В таскпейне «URL ЛЕС» = `https://localhost:8443`. Теперь https→https,
   mixed content нет. Сертификат localhost доверенный (шаг 1), браузер не ругается.

> На стороне ЛЕС нужно разрешить CORS для origin таскпейна
> (`https://localhost:3000`) — это делает команда, строящая `/api/mail/push`,
> не данный add-in.

### Вариант C: localhost-исключение (быстрый хак для проверки)

Хром-движки считают `http://localhost` «потенциально доверенным», но **запрос
с https-страницы на http всё равно блокируется** как mixed content — само по себе
исключение localhost его не снимает. Поэтому «исключение» здесь — это временно
отключить блокировку mixed content в движке таскпейна:

- Если таскпейн на desktop рендерится в WebView2 (Win) / WKWebView (Mac), флаг
  глобально не выставить — используй Вариант A.
- Если отлаживаешь add-in в обычном Chrome (Outlook on the web), можно временно:
  иконка замка слева в адресной строке → «Настройки сайта» → «Небезопасный
  контент» → **Разрешить**. Это снимет блок http-fetch для данного origin.
  Годится только для разовой проверки, не для постоянной работы — для постоянной
  бери Вариант B.

**Итог:** desktop → Вариант A (быстро), Outlook on the web / «по-взрослому» →
Вариант B (https с обеих сторон).

---

## Сайдлоад: как увидеть кнопку в Outlook (руками)

### 0. Сгенерируй свой GUID (один раз)

В `manifest.xml` `<Id>` — заглушка. Замени на свой:
```bash
uuidgen      # macOS/Linux; вставь результат в <Id>…</Id>
```

### 1. Проверь манифест
```bash
cd clients/outlook_addin
npm run validate         # office-addin-manifest validate manifest.xml
```

### 2. Подними сервер ассетов
- Вариант A: `npm run serve-http` (и заранее поправь https→http в manifest.xml).
- Вариант B: `npm run certs` затем `npm run serve`.

Проверь в браузере: `http(s)://localhost:3000/src/taskpane.html` должен открыться.

### 3a. Автосайдлоад (проще всего)
```bash
npm run start            # office-addin-debugging start manifest.xml desktop
```
Инструмент сам зарегистрирует add-in и откроет Outlook desktop. Для Outlook on the
web: `npm run start-web`. Снять: `npm run stop`.

### 3b. Ручной сайдлоад (если автоматический не сработал)

**Outlook on the web / new Outlook:**
1. Открой Outlook в браузере → шестерёнка (Настройки) → внизу «Управление
   надстройками» / «Get Add-ins».
2. «Мои надстройки» → «Пользовательские надстройки» → «Добавить из файла…».
3. Укажи `manifest.xml`. Подтверди предупреждение про непроверенную надстройку.

**Outlook desktop (Mac):**
1. Лента → «…» (Дополнительно) или «Get Add-ins» → «My add-ins» →
   «Custom Add-in» → «Add from File…» → выбери `manifest.xml`.

**Outlook desktop (Windows):**
1. Лента «Главная» → «Get Add-ins» → «My add-ins» → внизу «Custom Add-ins» →
   «Add from File…» → `manifest.xml`.

### 4. Используй
1. Открой любое письмо (режим **чтения**).
2. На ленте появится группа **ЛЕС** с кнопкой **В ЛЕС**. Нажми — откроется таскпейн.
3. В таскпейне видно тему/отправителя/вложения. Поле «URL ЛЕС» = адрес ЛЕС
   (по умолчанию `http://localhost:8050`, сохраняется).
4. «Отправить в ЛЕС» → внизу появится статус и таблица `routed` + блок КАЦ.

> Кнопки не видно? Проверь: (1) сервер ассетов на :3000 жив и отдаёт
> `taskpane.html`; (2) манифест прошёл `validate`; (3) для нового Outlook иногда
> нужно переоткрыть приложение после сайдлоада; (4) `<Id>` уникален (старый
> сайдлоад с тем же Id мог зависнуть — сними его в «Управление надстройками»).

---

## Замечания

- Add-in **только клиент**. Эндпоинт `/api/mail/push` строится на стороне ЛЕС
  параллельно — контракт выше зафиксирован, его и держимся.
- CORS: ЛЕС должен пускать origin таскпейна (`http(s)://localhost:3000`).
- Зависимости в проект не ставятся: все инструменты вызываются через `npx --yes`
  (office-addin-dev-certs, office-addin-debugging, office-addin-manifest,
  http-server, local-ssl-proxy) и кешируются npx локально.
