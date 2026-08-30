# ALGO — установка, запуск и обновление LES на Windows / Legion

Статус: канон. Этот документ определяет один lifecycle для clean install, обычного запуска,
soft update и hard recovery. Реализация не имеет права вводить второй ручной путь.

## 0. Пользовательский контур (как AnythingLLM)

Обычный оператор не запускает Python/CLI. Единственный продуктовый вход:

| Действие | Как |
|---|---|
| Чистая установка | `LES-Setup.exe` |
| Обычное удаление | Параметры Windows → Приложения → ЛЕС → Удалить (данные сохранить) |
| Полное удаление | тот же Uninstall + «Да» на удаление `%LOCALAPPDATA%\LES` |
| Обновление поверх | новый `LES-Setup.exe` поверх текущей установки |

Программа: `%LOCALAPPDATA%\Programs\LES`. Данные: `%LOCALAPPDATA%\LES`.
Setup/Uninstall перед заменой останавливают LES best-effort и не требуют UAC.
Stop/deps/docker не имеют права ронять Setup с «ошибка 1»: недостающее пишется
по-русски (`setup-deps-missing.txt`), WebView2 ставится bootstrapper/winget.
Человеческая инструкция: [WINDOWS_DESKTOP.md](WINDOWS_DESKTOP.md).

Ниже — машинный контракт тех же переходов (для кода, smoke и приёмки).

## 1. Неподвижные правила

- Всё работает от обычного пользователя. UAC, `RunLevel Highest`, `runas`, `takeown`, `icacls`,
  изменение DACL и скрытые elevated tasks запрещены.
- Канонические пути только два:
  - программа: `%LOCALAPPDATA%\Programs\LES`;
  - изменяемое состояние: `%LOCALAPPDATA%\LES`.
- Git checkout, SSH, публикация, сборка и тесты не выполняются на этапе применения обновления.
- Инсталлятор или пакет полностью проверяется до остановки LES: schema, SHA-256, версия, commit,
  allowlist, baseline manifest и наличие rollback point.
- Пользовательские файлы вне `%LOCALAPPDATA%\LES` не изменяются. Clean reset состояния возможен
  только по явной команде пользователя.
- Число без provenance не считается результатом; updater acceptance обязательно проверяет точный
  ГЭСН expand и hybrid smeta RAG, а не только HTTP 200.

## 2. Единственный dependency-контур

До запуска proxy/UI supervisor обязан подготовить **core**, а внешние capabilities проверить
независимо:

1. Persistent Python `%LOCALAPPDATA%\LES\.venv` сверяется с contract marker: SHA `uv.lock`,
   bundled Python/uv/cache, selected extra и platform. Exact marker + import probe означает
   `environment_action=skipped`; mismatch выполняет один locked/offline sync, нездоровая среда —
   один controlled rebuild. Все последующие `uv run` используют `--no-sync`.
   Вложенные служебные каталоги создаются по разрешённому target persistent-state junction:
   Python под `%LOCALAPPDATA%\Programs` не выполняет `mkdir` через mount point.
2. Immutable ФСНБ baseline проверяется; его недоступность отражается degraded status, но не
   превращает отсутствие внешнего компонента в повреждение Python.
3. Docker/Qdrant и answer/embedding providers определяются как optional capabilities.
   `docker_engine_unavailable` и `qdrant_unavailable` остаются warnings; core proxy/UI запускается.
4. Direct `pythonw.exe` proxy/UI стартуют и API health подтверждает готовность core.

Полный RAG/smeta acceptance по-прежнему требует доступных Qdrant, корпуса и providers, но это
отдельный capability gate, а не условие запуска базового LES.

## 3. Clean install

Вход: checksum-verified installer текущего commit и явный режим `clean`.

1. Проверить installer SHA/version/build/commit и bundled baseline до любых изменений.
2. Остановить только подтверждённый LES по exact runtime identity и PID владельцев 8050/8051.
3. Остановить `les-light-qdrant`.
4. Для полного reset атомарно вывести старые app/state roots из канонических путей на уровне их
   родительских каталогов. Не обходить содержимое с повреждённым DACL и не чинить ACL.
5. Создать пустые канонические per-user roots с обычным наследованием прав.
6. Установить app tree, persistent Python и bundled baseline во временные sibling-каталоги.
7. Проверить baseline механически; затем атомарно активировать его в canonical state.
8. Создать новый Qdrant container/volume и построить/подключить требуемые RAG generations.
9. Выполнить общий dependency startup из раздела 2.
10. Запустить proxy/UI и выполнить acceptance из раздела 7.
11. Только после зелёной acceptance пометить install `ready`; старый выведенный root больше никогда
    не используется как источник данных или rollback.

## 4. Обычный запуск

Пока bootstrap публикует `state=running`, desktop-кнопка запуска заблокирована и показывает текущую
фазу подготовки. Runtime startup не обращается к Hugging Face: tokenizer читается только из локального
кэша, а отсутствие кэша немедленно переключает chunking на контрактный символьный fallback.

Одна команда supervisor:

1. Прочитать installed identity и lifecycle state.
2. Если 8050/8051 свободны — выполнить dependency startup и запустить proxy/UI.
3. Если порты заняты — принять процессы только когда `/api/version.runtime_path` совпадает с
   installed runtime, `/healthz` подтверждает Совушку, а PID принадлежат Python. Тогда вернуть
   `already_ready` либо перезапустить их по явной операции.
4. Чужой владелец порта никогда не завершается: вернуть `foreign_port_owner` с PID/port.
5. Дождаться полной acceptance; таймаут возвращает точный failed stage.

Допустимы три явных runtime mode одного и того же lifecycle:

| Mode | Запускается | Владеет | Обязательное значение |
|---|---|---|---|
| `full` | proxy + Совушка | 8050 + 8051 | нет; default Tauri |
| `backend` | только proxy | 8050 | нет |
| `ui` | только Совушка | 8051 | HTTP(S) `BackendUrl` |

`ui` не запускает Qdrant, model adapter или proxy. Его нельзя принять по одному
`/healthz`: stop завершает только exact UI PID из `windows-light-state.json`.
`backend` проверяет identity через `/api/version` и не касается UI-порта.
Чужой listener во всех режимах остаётся `foreign_port_owner`.

## 5. Soft update

Полный Windows installer обязан содержать `.les_deploy_stamp.json` с exact 40-character commit.
Установка без точной identity не считается допустимой базой для soft update.

Одна команда `update-local` выполняет полный pipeline:

1. Прочитать exact installed commit из deploy stamp.
2. Проверить чистый pushed target commit и построить bounded runtime diff автоматически.
3. Исключить docs/tests/build-only файлы; неизвестный runtime path блокирует пакет, а не игнорируется.
4. Построить пакет с base/accepted/target SHA каждого файла и проверить его повторно.
5. Поднять полный dependency-контур. Если live baseline проходит mechanical base + RRF + exact
   ГЭСН expand, не изменять данные. Если не проходит — soft update прекращается; provisioning
   выполняется hard recovery/clean install, но не скрытой файловой починкой.
6. Идентифицировать и остановить LES-процессы; дождаться освобождения портов.
7. Если подтверждённый PID невозможно остановить из-за integrity level, записать терминальное
   `reboot_required` и подготовить одноразовое продолжение после входа. Не повторять попытки и не
   запрашивать UAC.
8. Создать checksum-verified rollback copy изменяемых файлов и deploy stamp.
9. Выполнить atomic replace bounded allowlist.
10. Запустить общий dependency-контур и proxy/UI.
11. Выполнить acceptance. При провале атомарно вернуть файлы/stamp и снова выполнить startup.
12. `ready` публикуется только после полной acceptance; CLI ждёт терминальный status.

## 6. Hard recovery update

Используется, когда меняются native shell, зависимости, baseline или повреждён app tree.

1. Проверить полный installer и recovery space.
2. Остановить подтверждённый LES.
3. Атомарно переименовать app tree в sibling recovery point.
4. Установить новый app tree в canonical per-user path.
5. Состояние сохранять только в обычном hard update. При явном clean reset применить раздел 3.
6. Выполнить dependency startup и полную acceptance.
7. При провале удалить новый app tree, вернуть старый одним rename и запустить его.

## 7. Обязательная acceptance

Успех установки/запуска/обновления доказывает один JSON trace:

- installed version/build/commit совпадают с target;
- API `:8050` и UI `:8051` отвечают;
- Qdrant `:6333` отвечает, aliases существуют;
- general RAG: complete dense+sparse/fingerprint counts и native RRF;
- RAG index contract совместим; внешний Qdrant отмечен `available` или `N/A`;
- mechanical smeta SQLite trusted for navigation/calculation;
- `GET /api/lsr/gesn/10-01-001-01/expand?qty=1` возвращает непустые ресурсы;
- configured reranker выполняет реальный двухкандидатный probe;
- runtime PID принадлежат direct Python, нет LES-owned `cmd.exe`/PowerShell wrappers;
- две последовательные стабильные пробы проходят после окна прогрева.

## 8. Ошибки и автоматическое решение

| Код | Причина | Автоматическое действие |
|---|---|---|
| `qdrant_unavailable` | внешний Qdrant не настроен или недоступен | `N/A`; core API/UI и soft update продолжают работу, updater не управляет Qdrant |
| `python_environment_invalid` | offline sync/rebuild не дал здоровую lock-bound среду | terminal fail с точной диагностикой; не маскировать как Docker/Qdrant |
| `model_missing` | внешняя generation/embedding model недоступна | capability warning; updater не устанавливает и не выбирает модель |
| `baseline_unreadable` | база отсутствует/повреждена/DACL чужой | soft update fail; clean reset создаёт новый canonical state без ACL mutation |
| `baseline_outdated` | bundled baseline новее | hard recovery; soft update не смешивает поколения файлов |
| `foreign_port_owner` | порт занят не LES | не завершать процесс; точный PID/port в status |
| `lost_process_state` | LES endpoint завис или state требует сверки | принять только по endpoint identity либо полному exact state root/mode/process contract/Python/port→PID; иначе `foreign_port_owner` |
| `reboot_required` | подтверждённый старый PID имеет высокий integrity | одноразовое continuation после reboot; UAC запрещён |
| `base_checksum_mismatch` | runtime drift | отказ до stop; hard recovery, не расширение accepted hashes наугад |
| `startup_timeout` | процесс жив, endpoint не ready | stderr tail + failed component; rollback update |
| `acceptance_failed` | версия/RAG/ГЭСН/reranker не прошли | rollback; не выдавать установку за успешную |
| `rollback_failed` | старый контур не поднялся | сохранить recovery point и терминальный diagnostic; не продолжать циклически |

## 9. Проверка самой автоматики

До применения обязательны hermetic tests всех переходов, затем два живых Legion-сценария:

1. clean install на пустом app/state: первый bootstrap намеренно проходит без Docker и доказывает
   core API/UI + warning codes; после stop второй bootstrap того же state обязан вернуть
   `environment_action=skipped`, не выполнять package network/sync и затем пройти полный RRF smoke;
2. мелкий soft update этой установки с изменением одного безопасного runtime-файла.

Для обоих сохраняются job, status timeline, process snapshot и acceptance JSON. Только после двух
зелёных сценариев запускается model-quality benchmark.
