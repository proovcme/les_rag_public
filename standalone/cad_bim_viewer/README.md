# LES CAD/BIM Вьюер Standalone

Минимальная standalone-сборка WebGL CAD/BIM viewer. Она работает без LES backend и без `npm install`:

- JSON/Revit/DWG/IFC-derived `cad_bim_graph.json` добавляется кнопкой `Добавить`;
- IFC добавляется кнопкой `Добавить` и грузится через локальный `web-ifc.wasm`;
- несколько моделей можно держать в одной сцене, скрывать, изолировать, вписывать и выгружать;
- для прямой загрузки JSON можно указать URL или путь вроде `models/demo.cad_bim_graph.json`.

## Запуск

### macOS / Linux

```bash
cd standalone/cad_bim_viewer
./serve.sh 8095
```

### Windows PowerShell

```powershell
cd standalone\cad_bim_viewer
powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095
```

Открыть:

```text
http://127.0.0.1:8095/
```

Для доступа с рабочих мест в локальной сети запускайте на сервере от имени администратора и открывайте:

```text
http://SERVER:8095/
```

В Лоции укажите этот адрес в переменной `TIM_VIEWER_2_URL`, например `http://SERVER:8095`. Не используйте `localhost` для пользователей в сети: в их браузере это будет их собственный компьютер.

### Установка рядом с Лоцией

Для production-сервера Лоции проще запустить установщик из этой папки от имени администратора:

```bat
INSTALL_FOR_LOCIA.cmd
```

Он копирует viewer в `C:\LociaTimViewer2`, создаёт задачу автозапуска `LociaERP\TimViewer2` от `SYSTEM`, открывает входящий TCP-порт `8095`, прописывает `TIM_VIEWER_2_URL` в `C:\Locia\.env` и перезапускает `LociaApache`. Viewer остаётся отдельным standalone-сервисом; в Лоции хранится только ссылка.

Если нужно указать конкретное имя или IP сервера:

```bat
INSTALL_FOR_LOCIA.cmd -PublicHost 192.168.1.10 -Port 8095
```

Просто двойной клик по `index.html` не рекомендуется: браузер может заблокировать WASM/worker и локальные файлы. Встроенный `serve.ps1` отдает `.wasm` как `application/wasm`, поэтому подходит для почти голой Windows-машины с PowerShell и браузером.

## Быстрая проверка без сети

1. Запусти локальный server.
2. В поле источника введи `models/demo.cad_bim_graph.json`.
3. Нажми `Загрузить`.
4. Проверь вкладки `Модели`, `Структура`, `Слои`, `Инструменты`.

## Состав

```text
index.html
assets/index.js
assets/index.css
fragments/worker.mjs
web-ifc/web-ifc.wasm
models/
models/demo.cad_bim_graph.json
serve.sh
serve.ps1
```

Runtime-зависимости минимальные: современный браузер и один локальный static server. Для Windows server уже включен в папку как PowerShell-скрипт; для macOS/Linux используется системный `python3 -m http.server`. `npm install` для запуска этой папки не нужен.

## Обновление сборки из LES repo

Из корня репозитория:

```bash
tools/build_cad_bim_standalone.sh
```

Перед этим нужно пересобрать основной viewer `frontend/cad_bim_viewer/dist`.
