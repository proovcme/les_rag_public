# Windows application updater ЛЕС

## Назначение

Application updater v2 заменяет повседневную передачу полного `LES-Setup.exe`: установленный
Windows-ЛЕС вручную получает небольшой content-addressed пакет с
`https://les.ovc.me/updates/`. Legion будет только полигоном приёмки после завершения Mac-работ;
сейчас updater на Legion не запускается.

Оператор нажимает `Проверить обновление` → `Установить`. Фоновых проверок и самопроизвольной
установки нет. Apply никогда не запускает pytest, сборку Tauri, baseline, dependency sync или
installer.

## Что разрешено

- Python под `backend/`, `proxy/`, `sovushka/`;
- prompts/skills и безопасные JSON/YAML/Markdown/UI assets;
- корневые `proxy_server.py` и `sovushka_ng.py`;
- собственный helper `tools/vps_patch_apply.py` и паспорт `config/version.json`.
- четыре exact lifecycle-скрипта:
  `installers/windows/{start-light,stop-light,state}.ps1` и
  `installers/windows/app/bootstrap.ps1`;
- опционально один уже собранный `les-desktop.exe` как отдельный `scope=app`.

Зависимости, lock-файлы, схемы/миграции, baseline ФСНБ, произвольные installers, исходники
Rust/Tauri/NSIS и любые другие нативные компоненты запрещены allowlist одновременно у builder,
клиента и detached helper. Если менялась оболочка, `windows_update_shell.py` один раз собирает на
Windows только Cargo shell и создаёт attestation с exact commit/version/build и SHA старого/нового
EXE. Builder не принимает произвольный бинарник: в update ZIP попадает только EXE из совпавшего
attestation, а не toolchain или installer.

## Контракт безопасности

`latest.json` содержит точные `product_version`, `build_number`, `base_commit`, `target_commit`,
scope и список файлов, допустимые и новый SHA-256 каждого
файла, SHA-256 и размер архива. Для app-shell оператор обязан передать точный SHA предыдущего
установленного `les-desktop.exe`. Клиент принимает только HTTPS `les.ovc.me/updates/*`, проверяет
собственные base-хэши до загрузки и повторно перед заменой, сверяет архив с внешним и внутренним
manifest и отвергает лишние файлы/path traversal.

Каждый новый `latest.json` собирается кумулятивно от commit базового полного релиза, а не от
предыдущего патча. Для каждого файла builder вычисляет точные SHA-256 полного base, текущего target
и каждого commit-состояния файла на ancestry `base..target` в LF/Windows-CRLF представлении.
Поэтому машина может пропустить патчи или уже иметь любой опубликованный промежуточный патч и затем
сразу перейти в последнее состояние; чужая локальная правка остаётся fail-closed и требует полного
выпуска.

Базовый SHA текстового файла считается по фактическому Windows runtime с CRLF, потому что полный
инсталлятор собирается из Windows checkout. Payload хранится как канонический текст; уже обновлённый
файл сопоставляется с target SHA. Это различие обязательно проверяется на установленном runtime.

Helper запускается через `pythonw.exe` независимой интерактивной Scheduled Task вне process tree
заменяемого runtime. PowerShell и `taskkill` запускаются с `CREATE_NO_WINDOW`. Helper до остановки
повторно валидирует archive SHA, exact manifest, отсутствие лишних ZIP entries, allowlist, base SHA,
размер и target SHA всех staged payload. Затем создаёт backup, останавливает LES, закрывает один
desktop, атомарно заменяет runtime и/или `les-desktop.exe`; компилируются только изменённые `.py`
файлы. Новый deploy stamp записывается перед стартом.

Успех требует точного commit/product version/build, HTTP proxy/UI, совместимого index contract,
прямых `python.exe/pythonw.exe` PID, `direct_python_no_console_v1` и нуля LES-owned `cmd.exe`.
При любой ошибке возвращаются все существовавшие файлы, удаляются добавленные, восстанавливается
deploy stamp и стартует предыдущая версия. User state, `data/`, `storage/`, RAG, секреты и индексы
не входят в transaction.
Статус лежит в persistent state и доступен через `GET /api/update/patch/status` после рестарта.

## Публикация

```bash
make build-windows-update-shell \
  WINDOWS_SHELL_ARGS='--base-exe "<installed-app>/les-desktop.exe"'

make prepare-windows-update \
  WINDOWS_UPDATE_ARGS='--base <compatible-base-commit> --target HEAD \
    --file proxy/services/example.py \
    --file installers/windows/start-light.ps1 \
    --desktop-manifest dist/windows-update-shell/les-desktop.update.json \
    --output dist/vps-patch'

uv run python tools/vps_patch.py publish --output dist/vps-patch
```

Обе prepare-команды запускают только `make test-updater` (обычно около секунды).
Нативная сборка shell выполняется отдельно и только если менялся Tauri; apply её не
повторяет. Builder принимает только явно перечисленные файлы. Публикация сначала загружает `.part`, затем
атомарно переименовывает архив и в последнюю очередь `latest.json`, поэтому клиент не увидит
manifest раньше полного архива.

## Web-контур

`les.ovc.me` больше не проксирует живой API/Совушку. `/` — статический лендинг проекта,
`/updates/*` — origin обновлений; старые `/api`, `/lite-api`, `/les`, `/classic` отвечают `404`.
Рабочие машины доступны только локально/через ZeroTier.

## Короткие проверки

```bash
make test-updater

powershell -NoProfile -File tools/windows_updater_smoke.ps1 \
  -ExpectedVersion 0.25.18 -ExpectedBuild 491 -ExpectedCommit <sha>
```

Offline-профиль поведенчески применяет и откатывает runtime + desktop на временных деревьях,
проверяет отказ до остановки и сохранность user state. Windows smoke длится не более 90 секунд и
проверяет только установленное обновление, identity, API/UI/index contract и process hygiene.
Он не строит приложение, не создаёт baseline, не вызывает модель/RAG и не запускает общую suite.

Переход с установленного v1-helper на v2 требует один последний полный installer, потому что старый
helper не знает `scope=app`. После этого обычные изменения доставляются application updater; полный
installer нужен только при изменении зависимостей, layout persistent state или самого формата
обновления.
