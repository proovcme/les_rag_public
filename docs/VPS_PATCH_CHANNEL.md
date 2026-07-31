# Windows installation and application updater ЛЕС

## Назначение

Есть два независимых пользовательских действия поверх одного lifecycle:

- **жёсткая установка выпуска** — проверенный `LES-Setup.exe` является только payload;
  Python engine целиком заменяет дерево программы и сохраняет `%LOCALAPPDATA%\LES`;
- **мягкое обновление** — небольшой content-addressed ZIP меняет только разрешённые
  файлы приложения.

Оператор запускает нужный режим вручную в настройках. Фоновых проверок и
самопроизвольной установки нет. Apply никогда не запускает pytest, сборку
Tauri, baseline или dependency sync.

## Общий lifecycle

`tools/windows_update_engine.py` — единственный владелец stop/start/smoke и
полной hard-транзакции. До остановки он проверяет SHA installer и готовность
persistent venv. `tools/windows_runtime.py` напрямую запускает proxy/UI через
`pythonw.exe`, без PowerShell/cmd, хранит exact PID и до чтения отклоняет
`.env` больше 1 МБ с кодом `LES_ENV_OVERSIZED`. Повреждённый env чинится
`tools/windows_env_doctor.py`: значения не выводятся, исходный файл атомарно
уходит в persistent recovery. Текущее дерево `%LOCALAPPDATA%\Programs\LES` атомарно
переименовывается в sibling recovery point; silent NSIS создаёт новое дерево,
`state.ps1` восстанавливает junctions на `%LOCALAPPDATA%\LES`. Успех требует
exact commit/version/build, API/UI, доступного Qdrant, совместимого index contract и прямого
Python process contract. Проверка сначала подтверждает дешёвые identity/API/UI и
живые exact PID, затем запрашивает глубокий RAG/Qdrant health; успех требует двух
последовательных стабильных проб. При провале новое дерево удаляется, старое возвращается
одним rename и перезапускается.

Любая системная проверка, доступная из UI или периодического runtime status,
запускает дочерние процессы Windows только с `CREATE_NO_WINDOW` и без stdin.
Контракт распространяется не только на updater: `tasklist`, фоновые dispatcher
jobs и нативный выбор папки не имеют права создавать console window.

PowerShell допустим только как bounded single-purpose launcher для state,
start/stop и интерактивной Scheduled Task. Он не хранит вывод дочернего процесса
в памяти, не строит приложение, не опрашивает WMI/CIM и не управляет откатом.
Исторические `windows_*production*.ps1` оставлены тонкими алиасами; standalone
PowerShell rollback закрыт.

## Что разрешено

- Python под `backend/`, `proxy/`, `sovushka/`;
- prompts/skills и безопасные JSON/YAML/Markdown/UI assets;
- корневые `proxy_server.py` и `sovushka_ng.py`;
- собственные helpers `tools/{vps_patch_apply,windows_update_engine}.py` и паспорт
  `config/version.json`.
- общий console-free operational launcher `tools/les_runtime_control.py`;
- пять exact lifecycle-скриптов:
  `installers/windows/{start-light,stop-light,runtime-process,state}.ps1` и
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
файлы. Новый deploy stamp записывается перед стартом. Status публикуется через
same-directory temporary file и bounded retry атомарного replace: Windows-reader,
который в этот момент читает предыдущий JSON, не является ошибкой приложения и
не запускает rollback.

Успех требует точного commit/product version/build, HTTP proxy/UI, доступного Qdrant,
совместимого index contract, чтения persistent сметного baseline через рабочий
`/api/lsr/gesn/{code}/expand`, прямых `python.exe/pythonw.exe` PID и
`direct_python_no_console_v2`.
При любой ошибке возвращаются все существовавшие файлы, удаляются добавленные, восстанавливается
deploy stamp и стартует предыдущая версия. User state, `data/`, `storage/`, RAG, секреты и индексы
не входят в transaction.
Статус лежит в persistent state и доступен через `GET /api/update/patch/status` после рестарта.

Python engine ждёт exact child PID с timeout, пишет stdout/stderr сразу в файлы
и не удерживает многогигабайтный вывод в памяти. Apply не делает сетевой
`uv sync`: готовый persistent venv проверяется локальным bounded import-spec
probe до остановки. Изменение зависимостей требует отдельного полного
release-build с offline dependency payload; текущий update не маскирует
отсутствующую зависимость сетевой установкой.

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

Обе prepare-команды запускают только `make test-updater`. Этот target делегирует
единому переносимому entrypoint `uv run python tools/platform_release_gate.py updater`,
поэтому тот же профиль работает на Legion без GNU Make. Entry point сам создаёт
доступный pytest `--basetemp` внутри workspace; оператор не воспроизводит список
тестов вручную.

Clean-install smoke также использует content-addressed
`.codex_tmp/windows-release-smoke/<commit>` внутри checkout. Он не переиспользует
общий `%LOCALAPPDATA%\LES-release-smoke`, где файлы прежнего installer могут
иметь несовместимый ACL и блокировать следующий автоматический prepare.
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

# прямой эквивалент для Windows без GNU Make
uv run python tools/platform_release_gate.py updater

# переносимые эквиваленты обязательных verify/test текущего LES
uv run python tools/platform_release_gate.py current-verify
uv run python tools/platform_release_gate.py current-test

powershell -NoProfile -File tools/windows_updater_smoke.ps1 \
  -ExpectedVersion 0.25.22 -ExpectedBuild 495 -ExpectedCommit <sha>
```

Offline-профиль поведенчески применяет и откатывает runtime + desktop на временных деревьях,
проверяет отказ до остановки и сохранность user state. Windows smoke использует
bounded поэтапные пробы (не более трёх минут при реальном отказе) и
проверяет только установленное обновление, identity, API/UI/index contract, configured reranker
на двух коротких фрагментах и process hygiene. Он не строит приложение, не создаёт baseline,
не вызывает генеративную модель/полный RAG и не запускает общую suite. Если пакет меняет
`vps_patch_apply.py`, `windows_update_engine.py` или `windows_runtime.py`, detached launcher
берётся из checksum-declared target payload; иначе используется уже установленное ядро обновления.

Первый запуск нового контура на Legion выполняется hard-job из проверенного
локального installer без публикации. После его приёмки обычные изменения
доставляются мягким package; hard install остаётся живым пользовательским путём
для полного выпуска или восстановления повреждённого дерева приложения.

Prepared hard-update принимает имя ветки явно и переносит его в job/deploy stamp;
тестовая `codex/*` ветка не может быть записана как `codex/sovushka-ui-kit` по
жёстко заданному значению. `start-light.ps1` перед `Start-Process` нормализует
унаследованные `Path`/`PATH` в один process key, иначе Windows PowerShell 5.1
может упасть ещё до старта Python при сборке регистронезависимого словаря.
