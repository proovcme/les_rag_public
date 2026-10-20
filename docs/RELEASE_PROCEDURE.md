# Выпуск ЛЕС

## 974 — кандидат: ограниченный повтор Windows rename при rollback

Измеренный release-blocker973: основной pytest завершён, но `test-updater`
дважды остановился на WinError5 в `rollback_accepted_hard_update` при замене
каталога приложения. Предусмотренная правка974 ограничивает повтор rename
пятью секундами/интервалом50мс только для WinError5/32/33; повтор разрешён,
только если исходный каталог существует, а целевой отсутствует, с проверкой
до и после паузы. Если первый перенос выполнен, а второй
не выполнен, прежний candidate восстанавливается на месте; исходная ошибка и
ошибка восстановления сохраняются отдельно. Та же граница нужна для recovery
после smoke-отказа; native/PID/identity guards не ослабляются.
ROOT TDD:9failed/4passed →13passed; первоначальный updater325passed/20,41s.
Два дополнительных случая drift во время паузы воспроизвели2failed; после
post-sleep проверки final related99passed/2,48s. Полный974 gate/install/live
не подтверждены; это по-прежнему кандидат.
Регрессии добавляются в прежний `test_windows_native_boot_960.py`; это не
разрешение считать принятым rollback по одному успешному rename.

## 960 — продуктовый старт принадлежит native bootstrap

Hard/soft apply, resume после недоступного API, rollback и recovery сохраняют
прежние dependency/PID/stop guards, затем запускают native entry. Generic
headless start перед ним больше не занимает продуктовые порты с другим env.
Здоровый resume не останавливает уже работающий backend; явный headless CLI
сохраняет прежнее поведение. User-owned FreeToken/Ollama не завершаются.

После восстановления проверяется прежний deploy commit/version/build, а не
только HTTP health. `rollback_ready` не объявляется до этой проверки; исходная
ошибка не скрывается ошибкой recovery. Установленная приёмка обязана сверить
effective factors и bindings сразу после canonical apply, до любого ручного
start-light, иначе ручной перезапуск может замаскировать дефект обновления.
Packaged native SHA берётся из точного NSIS artifact, отдельно от loose Cargo EXE.
Регрессия: `test_windows_native_boot_960.py` (9 маршрутов и foreign PID guards).

## 959 — восстановление после отказа до замены Windows-приложения

Hard update сохраняет прежние version/deploy identity и SHA native EXE до
остановки. Если обе остановки завершены, но замены application tree ещё не было,
технический отказ восстанавливает прежний native запуск только при неизменной
identity на месте. Проверяется прежний commit/version/build. Исходный отказ
остаётся итоговой ошибкой; ошибка восстановления записывается отдельно.
Проверка внешних CWD-locks не ослабляется и чужие процессы не завершаются.
После move действует прежний recovery-rollback. Marker сохранения состояния
не является резервной копией пользовательской БД. Регрессия:
`test_windows_hard_rejection_recovery_959.py`; exact installer live gate обязателен.

Это единственная актуальная публичная процедура. Старые `patch-release`,
`github-patch-release` и `release-multiplatform` остаются внутренними адаптерами;
оператор не запускает через них публикацию.

## Полный проход

Windows prebundle smoke использует отдельные runtime/state roots и свободные
порты. `LES_RELEASE_SMOKE=1` запрещает start-light останавливать уже работающий
proxy/UI/adapter ради освобождения порта. Обычный запуск сохраняет прежнее
поведение. `tauri_build_environment` добавляет существующий Rust toolchain
через Windows `;`, сводит case-insensitive Path/PATH к одному ключу и сохраняет
остальные PATH entries; установка toolchain не выполняется. Оба исправления
закрывают измеренные отказы prepare 861, но не доказывают качество ЛСР.

Из чистой ветки, отправленной в `origin`, принять кандидата на текущем Legion и
опубликовать тот же immutable artifact одной командой:

```text
make release RELEASE_ARGS='run --host local --publish'
```

Команда последовательно и с сохранением state выполняет:

1. Сверяет `HEAD`, upstream, версию и generated maps; один раз запускает `make verify`,
   `make test`, `make test-updater` и `make public-check`.
   Базу накопительного patch берёт только из проверенного
   `dist/release-work/full-base/latest.json`; из feature worktree сначала
   проверяет её локальный release-work, затем канонический `repo_root`.
   Исторический `dist/latest.json` не участвует в классификации. `--full-feed`
   нужен только для явной замены этого attested full-base.
   Успех сохраняется как `les.release-gate-receipt.v1`, привязанный к exact
   commit/tree/version и политике gates. Такой receipt можно явно передать в
   `prepare --gate-receipt`, повторный прогон suite не выполняется.
2. Автоматически выбирает soft patch или полный NSIS-выпуск. Сразу после
   готовности ZIP/EXE, до установленного smoke, фиксирует его SHA/размер и
   provenance в immutable `les.release-artifact.v1`. Для full release туда же
   входит SHA canonical `hard-update-job.json`; перед мутацией повторно
   проверяются его installer, install/state/status roots и version identity.
   Для текстового Windows runtime manifest дополнительно фиксирует exact SHA
   фактически установленного файла, только если его LF-нормализованное
   содержимое совпадает с доверенным состоянием Git ancestry. Новый клиент и
   helper также принимают доверенный текст независимо от смешения LF/CRLF;
   любое другое содержимое по-прежнему отклоняется checksum guard.
   Текстовые support-файлы, явно входящие в Windows runtime manifest
   (`env.example`, registry динамических entrypoint и перечисленные Python
   maintenance tools), допустимы в soft patch только когда один и тот же exact
   path разрешён classifier, builder и installed updater. Рассинхрон этих трёх
   списков является ошибкой release tooling, а не причиной для NSIS.
   `README.md` остаётся обязательной package metadata полного runtime, но
   изменение только его публичного текста не меняет приложение и не входит в
   cumulative patch: базовый installer уже содержит этот файл, а soft-update
   не пересобирает Python environment.
3. На текущем Legion (`--host local`) ставит точные candidate bytes штатным
   путём, проверяет identity,
   живые proxy/UI отдельно от внешних capabilities и, если Qdrant был доступен, временный native
   `dense + qdrant_sparse → RRF` dataset. Контрольный текст гарантированно длиннее
   фильтра коротких чанков; recovery-free cleanup разрешён только exact-набору
   `LES acceptance <uuid>` с единственным `release-acceptance.txt`, поэтому smoke
   не делает полный snapshot пользовательской коллекции.
4. Выполняет controlled rollback, проверяет восстановленную версию и повторно
   ставит те же candidate bytes.
5. Только после stage `accepted` проверяет, что публичный `main` является
   предком принятого commit, и выполняет обычный non-force fast-forward до
   exact target. Divergence останавливает выпуск до создания draft; force push
   запрещён. До проверки ancestry публичный репозиторий не изменяется.
6. Создаёт GitHub draft с явным target commit, добавляет
   `release-receipt.json`, скачивает все assets обратно и сверяет SHA.
7. Публикует draft и независимо сверяет public main, tag, feed, receipt и assets.

Если checksum guard доказал, что установленный runtime не принадлежит
доверенной ancestry cumulative patch, guard не ослабляют. Оператор повторяет
выпуск с `--force-full --smeta-baseline-archive <verified.zip>`: `local`
готовит NSIS напрямую через `windows_prepare_update.ps1`, а acceptance ставит
exact installer, делает rollback и повторную установку через общий hard-update
engine.

### Локальный полный установщик без публикации

Когда нет подтверждённого full-base или отправленной в `origin` ветки, явный
`--local-only-full` готовит полный установщик из чистого exact checkout, включая
detached HEAD. Он сохраняет все обычные version/runtime-map/verify/test/updater/
public-check gates, verified baseline, immutable installer/job SHA и стандартную
приёмку. Пропуск gates, remote host, `--base`, `--full-feed` и `--publish` запрещены.
Источник фиксируется честно: `upstream_commit: null` в gate receipt,
`base_commits: []` в artifact receipt; оба имеют `local_only_full: true` и
`publishable: false`. Режим не
создаёт искусственный full-base feed и не разрешает последующую публикацию.
Обычный выпуск без флага по-прежнему требует pushed branch и attested base.

Из отдельного чистого checkout после commit всех изменений:
для `uv` в этом build-process задаётся `UV_PROJECT_ENVIRONMENT` внутри уже
игнорируемого `<clean-checkout>/.test-tmp/release-env`, чтобы не создать
untracked `.venv`. Пользовательские untracked files исходного checkout сохраняются.

```text
uv run python -m tools.release_orchestrator prepare --root <clean-checkout> --work-root <release-work> --host local --local-only-full --target <exact-commit> --smeta-baseline-archive <verified-baseline.zip>
uv run python -m tools.release_orchestrator accept --root <clean-checkout> --work-root <release-work> --host local --artifact <artifact-receipt.json>
uv run python -m tools.release_orchestrator status --artifact <artifact-receipt.json>
```

`prepare` только собирает пакет; `accept` выполняется после завершения живых
прогонов, поскольку ставит exact installer, проверяет smoke, делает rollback,
проверяет восстановленную версию и повторно ставит те же bytes. Нестандартные
install/runtime/state roots передаются одинаково обоим командам. Кэш подготовленного
installer принимается только при совпадении SHA текущего baseline; другой архив
того же commit требует новой сборки. Отсутствующий baseline не допускает cache hit.
SHA baseline закрепляется до сборки и проверяется перед изменением кэша;
изменение архива во время сборки отклоняется, прежний кэш сохраняется.
Freeze проверяет реальные SHA скопированных файлов. Временные Windows locks
atomic rename допускают только три попытки для WinError 5/32/33; постоянный
отказ остаётся ошибкой, несовпадающие immutable bytes не перезаписываются.

### Явные дополнительные книги цен

Официальный baseline creator поддерживает старый семифайловый архив v1 и
расширенный v2. Дополнительные книги перечисляются явно; папки пользовательского
RAG, мета-БД, документы и секреты не обходятся и не копируются:

```text
uv run python -m tools.smeta_release_baseline create --source-root <verified-source-root> --archive <baseline.zip> --pricebook data/price_base/sankt-peterburg_3kv2026.parquet --pricebook data/price_base/moskva_3kv2026.parquet
uv run python -m tools.smeta_release_baseline verify --archive <baseline.zip>
```

Разрешены только явно названные `data/price_base/*.parquet`, с любым фактическим
регионом и периодом. Creator/verifier используют официальный `PriceBook`, проверяют
typed metadata, SHA/размеры, числовые значения и точный file whitelist. В manifest
v2 сохранены количество исходных строк, строки с ценовыми значениями, пробелы цен
и единиц, повторные коды. Такие исходные пробелы сохраняются без исправления или
удаления строк; они не доказывают готовность денежного расчёта, который проверяет
единицу и происхождение каждой выбранной позиции отдельно.

Bootstrap `repair` и `provision` добавляют только отсутствующие дополнительные
книги. Проверенные существующие книги оператора сохраняются побайтно; повреждённая
существующая дополнительная книга вызывает явный отказ без молчаливой замены.
Manifest известных производителей проецируется в публичные hashes/counts и
относительные payload paths; абсолютные machine paths и неизвестные private keys
не попадают в новый архив. Это не проверка прав распространения исходных нормативных
данных: источник для поставки должен быть отдельно разрешён владельцем.

Полный Windows runtime manifest обязан включать не только импортируемый код, но
и package metadata, которую читает build backend. В частности, если
`pyproject.toml` объявляет корневой `README.md`, оба файла входят в staged
runtime до `uv sync --locked`. При отказе локального prepare оркестратор
возвращает ограниченный хвост stdout/stderr, чтобы ошибка сборки не сводилась к
одному exit code.
Динамические Python entrypoints (`python -m ...`), включая фоновый FGIS
supervisor, перечисляются в manifest явно: статический import-аудит их не видит,
а installed smoke обязан доказать реальный старт процесса.

Installed clean-smoke запускает Windows bootstrap только с системным
`WindowsPowerShell\v1.0\Modules` в `PSModulePath` и без унаследованных
`VIRTUAL_ENV`, `UV_PROJECT_ENVIRONMENT`, `UV_CACHE_DIR`. Операторский PowerShell
7/Codex environment не должен лишать дочерний Windows PowerShell стандартных
cmdlet вроде `Get-FileHash` или направлять installed bootstrap в dev-venv.
Smoke-root остаётся checkout-owned, но его имя ограничено
`.codex_tmp/wrs/<sha12>-<id8>`: `uv` и Hatchling создают под ним глубокое дерево,
поэтому полный commit и GUID в пути запрещены как источник Windows
`STATUS_NAME_TOO_LONG`.

Построитель cumulative patch читает Git history пакетно и печатает
ограниченный прогресс по ancestry и manifest-файлам. Результат автоматического
public-main sync (`before`, `after`, `fast_forwarded`) записывается в persisted
publication state. Если последующий шаг упал, повторный `publish --artifact`
продолжает тот же draft; уже выполненный exact sync становится безопасным no-op.
Release CLI до первого вывода принудительно устанавливает UTF-8 для stdout и
stderr, поэтому русский progress и итоговый JSON не зависят от Windows codepage.

Если GNU Make отсутствует на Windows, `uv run python tools/release_orchestrator.py`
выполняет те же обязательные gate-рецепты из текущего `Makefile` напрямую через
`uv`: сохраняются полный `CURRENT_TESTS`, локальный `--basetemp`, updater и
`public-check`. Эффективные команды записываются в gate receipt. Неизвестная
Make/shell-конструкция прекращает подготовку; сокращённая platform-suite не
подменяет канонические тесты. Раздельный `prepare` принимает `--runtime`, `--state`
и `--install` с теми же defaults, что `accept` и `run`; нестандартные корни нужно
передать одинаково при подготовке и приёмке immutable installer.
Полностью заключённый в кавычки literal `@echo` является сообщением статуса:
пунктуация внутри него не блокирует запуск реального gate. Команды за закрывающей
кавычкой, переменные и подстановки shell по-прежнему отклоняются.

Ручной fast-forward нужен только как диагностическое восстановление после
осознанного устранения divergence. Обычная процедура не требует отдельного
`git push public` между приёмкой и публикацией.

## Раздельное выполнение и продолжение

```text
make release RELEASE_ARGS='gate --branch <branch>'
make release RELEASE_ARGS='prepare --host local --gate-receipt <gate-receipt.json>'
make release RELEASE_ARGS='accept --artifact <artifact-receipt.json> --host local'
make release RELEASE_ARGS='status --artifact <artifact-receipt.json>'
make release RELEASE_ARGS='publish --artifact <artifact-receipt.json>'
```

Последний artifact записан в `dist/release-work/latest.json`. Если acceptance
упала после build, повторить те же exact bytes без gates/Tauri/NSIS:

```text
make release RELEASE_ARGS='retry --artifact <artifact-receipt.json> --host local'
```

Каждая попытка хранится отдельно как `les.release-acceptance.v2`; неудача не
меняет artifact receipt и candidate bytes. `publish --artifact` — единственный
поддержанный ручной fallback: он требует успешную попытку, повторно сверяет SHA
и не содержит build. Старый `les.release-attempt.v1` доступен через
`status --attempt` только для исторической диагностики.
Если runner оборвался до доказанного восстановления host, обычный `retry`
fail-closed остановится. После ручной сверки installed identity и завершения
rollback оператор повторяет его с `--recovery-proved`; этот факт и ID прежней
попытки записываются в новую acceptance-квитанцию. Host при retry менять нельзя.

`local` — явный псевдоним машины, на которой запущен оркестратор. Имя или SSH
alias (например, `legion`) указывается только при действительно удалённой
приёмке; оно никогда не подменяется неявно.

## Стоп-условия

- Любое расхождение commit или одного байта прекращает выпуск.
- Исчезновение ранее доступной capability прекращает приёмку.
- Недоступный до обновления внешний Qdrant получает честный `N/A`; ЛЕС его не
  устанавливает и не запускает.
- На Windows способ запуска внешнего Qdrant остаётся ответственностью оператора;
  release-процедура проверяет доступность и continuity, но не создаёт и не
  переписывает Scheduled Task.
- `%LOCALAPPDATA%\LES` не входит в application transaction.
- `--skip-gates` создаёт только непубликуемый legacy dev-attempt; публичный v2
  artifact требует точный gate receipt.
- Ошибка после публикации — критический immutable-release incident; stage
  `postflight_verified` не выставляется.

Receipt и текущую стадию смотреть командой `status`. Публичная публикация до
успешных install, smoke, rollback и reinstall на Legion технически запрещена.
