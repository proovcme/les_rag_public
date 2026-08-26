# AGENTS.md — гид для AI-агентов (Л.Е.С. / LES_v2)

Канонический файл для любого агента (Codex, Claude Code, Cursor). Держи коротким; длинные процедуры — в доках и `SKILL.md`.

## Что это
Локальный **строительный evidence-harness** (RAG — один из слоёв, не продукт): проект/датасет → вопрос → правильный workflow → источники → расчёт КОДОМ → blockers/MISSING → проверяемое evidence → ответ. FastAPI (proxy :8050 + MLX-host :8080) + NiceGUI UI «Совушка» (:8051) + Qdrant (:6333), Python 3.12 на **uv**. Сервисы — launchd. Принцип: **модель связывает, код считает**; число без происхождения — не результат.

Основная публичная платформа выпуска — **Windows**: Tauri + FastAPI/NiceGUI. Установщик несёт
собственный офлайн Python/uv runtime; Ollama, FreeToken, Lemonade, OpenAI-compatible API и Qdrant —
внешние пользовательские компоненты. Mac остаётся dev/reference-контуром и не определяет Windows defaults.

Инвариант RAG: любой текущий и будущий dataset индексируется в единую contract-versioned named
collection как `dense + bm25_sparse`; production retrieval всегда выполняет native RRF, затем общий
rerank и parent/context expansion. Typed SQLite/reader tools дают exact rows/cards; они не выбирают
профессиональное решение вместо модели. Unnamed vectors, sparse sidecar, копирование legacy dense,
domain-prose в query и dataset/case-specific boosts запрещены.

## Канон документации (читать В ЭТОМ ПОРЯДКЕ — остальное историческое)
> ⚠️ Доков много и они разных эпох. **Текущая правда — только эта цепочка.** Всё, что ниже в «Историческом», — контекст, НЕ инструкция; не принимай старый слой за актуальный.

1. **AGENTS.md** (этот файл) — канон для агента.
2. **[SKILL.md](SKILL.md)** — рантайм/эксплуатация (порты, деплой = `cp`+`write_deploy_stamp`, доступы, гейты). Источник истины по запуску.
3. **[docs/MODULE_INDEX.md](docs/MODULE_INDEX.md)** — карта МОДУЛЕЙ: что есть, точки входа, **статус док↔код** (✅/🟡/🗄/📋), ссылка на док модуля. Начинай отсюда: модуль → его док/код.
4. **[docs/CODE_MAP.md](docs/CODE_MAP.md)** — карта кода по файлам: поток чата/индексации, «где искать что».
5. **[docs/SOFTWARE_VERSIONS.md](docs/SOFTWARE_VERSIONS.md)** — паспорт версий ЛЕС, Qdrant, Ollama, моделей и сборочного контура.
6. **[ROADMAP_TO_V1.md](ROADMAP_TO_V1.md)** — что считается v1, этапы, блокеры (актуальный план).
7. **[docs/RELEASE_LEDGER.md](docs/RELEASE_LEDGER.md)** — **где мы сейчас**: версия продукта, номер сборки, dev↔рантайм commit, что задеплоено.
8. **[docs/unified_harness_failure_ledger.md](docs/unified_harness_failure_ledger.md)** — журнал реальных провалов и как закрыты.
9. **[docs/TEST_INVENTORY.md](docs/TEST_INVENTORY.md)** — карта тестов (что и где покрыто).

Доп. при правке конкретного ядра: **алгоритм-доки** (0 LLM) — [docs/ALGO-table-query.md](docs/ALGO-table-query.md), [docs/ALGO-spec-to-bor.md](docs/ALGO-spec-to-bor.md) и др. в `docs/ALGO-*`; «что НЕ читать» — [docs/AGENT_NOTES.md](docs/AGENT_NOTES.md). **Как документировать (стандарт):** [docs/DOCUMENTATION_PLAYBOOK.md](docs/DOCUMENTATION_PLAYBOOK.md).

**Любая правка UI/UX «Совушки»:** сначала
[`skills/sovushka-ui/SKILL.md`](skills/sovushka-ui/SKILL.md) и
[`docs/modules/sovushka-uikit.md`](docs/modules/sovushka-uikit.md). Новый
визуальный элемент допустим только после проверки общего component registry.

**Историческое (контекст, НЕ текущая правда):** датированные саммари/хендоффы/репорты и заменённые планы сведены в **[`docs/archive/`](docs/archive/)** (`SESSION_SUMMARY_*`, `ROADMAP_LES_v2.0`, `DOCS_*AUDIT*`, хендоффы — см. `docs/archive/README.md`). На месте, но тоже историческое: `README_v2.0.md`, `LES_MASTER_DOC_v2_1.md`, `INFRASTRUCTURE_v2.0.md`, `RAG_MODERNIZATION_PLAN.md`, `ARTICLE_*.md`. Полезны для «почему так», но версии/решения могут устареть — сверяй с каноном и кодом (`/api/version`).

## Гейт проверки
- **`make architecture-gate`** — структурный fail-closed guard канонической
  0.29-архитектуры: запрещает параллельные `estimate_*` workbook tools,
  regex-forcing, неявную активацию профиля, новые прямые model HTTP callsites
  вне ContextGovernor и фиктивную live acceptance. Это структурное
  доказательство, а не проверка качества модели.
- **`make verify`** — офлайн: `compileall` + `pytest --collect-only` короткого канонического contract/behavior gate, без живых сервисов. Гонять перед готовностью.
- **`make test-architecture`** — совместимый псевдоним короткого канонического gate. Исторический Unified/Construction Harness запускается через `make test-legacy`; прежняя 3204-test suite — только через `make test-legacy-full`.
- **`make test-mail`** — отдельный offline-профиль Е.Ж.И.К.: IMAP/registry/dedup/RAG/API/UI и статический Windows-sidecar contract. **`make test-mail-release`** добавляет Tauri compile-check; установленный classic Outlook подтверждается только живым Legion-гейтом.
- **`make test`** — короткий явно перечисленный contract/behavior gate. Прежний repository-wide прогон перенесён в `make test-legacy-full` и не является release-доказательством.
- **Доменный гейт** (после правок retrieval/router и только при подключённом пользовательском
  корпусе с источниками набора): `uv run python tools/rag_golden_set.py --cases
  golden/domain_fire_hvac_set.json` — ожидается **16/16**. Пустой user-owned `les_rag` означает
  `N/A: corpus absent`, а не повод подмешивать системные СП или ослаблять кейсы
  ([SKILL.md](SKILL.md): качество FIRE/HVAC — доменная приёмка конкретного корпуса).
- **CI нет** — гейт запускается вручную.

## Definition of Done — ЛЮБОЕ изменение
Изменение «готово» не когда код работает, а когда выполнено всё ниже (полный гайд по докам —
[docs/DOCUMENTATION_PLAYBOOK.md](docs/DOCUMENTATION_PLAYBOOK.md); прод-дисциплина — [docs/GUARDRAILS.md](docs/GUARDRAILS.md)):
1. Сузить контекст (MODULE_INDEX/CODE_MAP → узкий поиск, не открывать тяжёлое); **минимальный дифф**.
2. **Тест на изменение** (ловит регрессию); точечно `uv run pytest tests/test_X.py`.
3. **Док — в ТОМ ЖЕ коммите:** обновить док модуля (если менялись поток/границы/точки входа) + строку в
   [MODULE_INDEX](docs/MODULE_INDEX.md) (статус док↔код + новые точки входа). **Док не должен врать о коде.**
4. **Версия + леджер:** двинуть `product_version` по SemVer `X.Y.Z` и монотонный `build_number` в
   [`config/version.json`](config/version.json) + строка в [RELEASE_LEDGER](docs/RELEASE_LEDGER.md).
5. **Гейт ПЕРЕД «готово»:** `make verify` (всегда); `make test` если трогал логику.
6. **В прод — только `make ship`** (verify→test→smoke зелёные) + известный откат (git checkout + redeploy / `tools/restore_runtime.sh`).

## Грабли и осторожность
- **uv-проект:** зависимости/запуск через `uv run`. Не ставить пакеты без одобрения (`uv add` меняет lock).
- **Windows-гейт:** если `make` отсутствует, сначала проверить команду и выполнить точные `uv`-команды цели из `Makefile`; pytest запускать с workspace-local `--basetemp=.test-tmp/<gate>`, потому что системный `%TEMP%\pytest-of-Oleg` на Legion может быть недоступен. Не считать setup `PermissionError` провалом кода и не повторять запуск без `--basetemp`.
- **НЕ дёргать сервисы** (launchd: qdrant/mlx/proxy/sovushka/pauk) без явной нужды — это живой рантайм. Рестарты — `tools/les_runtime_control.py` / `lesctl.py`, осознанно.
- **Деструктивное — запрещено без явной просьбы** (Guardrails в [SKILL.md](SKILL.md)): не удалять `data/qdrant/`, `data/les_meta_qwen.db`, `storage/`, `RAG_Content/`; не запускать полный реиндекс; беречь таблицу `structured_rules`; `VALIDATOR_BACKEND=rules` — текущий стабильный дефолт.
- **MLX/память:** модели TTL-выгружаются, metal-семафор; не ломать `backend/mlx_adapter.py` логику памяти.
- **Сметный модуль (`proxy/smeta_core/document_workflow.py`) — ПРИЗНАН СТАБИЛЬНЫМ v0.3 (v0.27.29):**
  Сметное ядро содержит верифицированные механизмы (Flexible Code Resolver `resolve_extracted_norm_code_flexible`, масштабируемую конвертацию единиц `units_compatible`, допуск открытых карточек `actually_opened` для `unbound`).
  **ЗАПРЕЩЕНО ИЗМЕНЯТЬ БЕЗ ПРЯМОГО УКАЗАНИЯ И ПРОГОНА БЕНЧМАРКА:**
  `uv run python tools/smeta_model_quality_benchmark.py tests/fixtures/sks_4.xlsx --profile qwen=qwen3.5:9b --allow-single-profile --max-turns 10 --candidate-limit 6 --num-ctx 8192 --interrupt-after-rows 5 --out-dir storage/ab_verify`.
  Ожидается 5/5 строк с решениями (covered_by / unbound / bind) и корректная гибридная авто-привязка норм. Детали защищённых участков — в docstring модуля.
- **Текущий контур стабилизации RAG/UI не включает сметный модуль:** не изменять `proxy/smeta_core/**`, сметные алгоритмы, mapping, нормы, расчёты, формы и их product defaults. Сметные тесты разрешено запускать только как регрессионный предохранитель. Изменение сметного поведения требует нового прямого указания владельца и отдельного benchmark-гейта выше.
- **Public release:** публиковать только после явного указания владельца, `public-check`, локальных
  гейтов и живой приёмки точного установщика на Windows. Исключить runtime/data/secrets, сохранить
  rollback и обеспечить совпадение verified commit, публичного `main` и release tag.
- Правка движка CAD/BIM (`frontend/cad_bim_viewer/`) — отдельная Vite-сборка, не править собранный `dist/`.

## Что НЕ читать (токены/секреты)
`.env` и любые креды/`JWT_SECRET`/`ADMIN_PASSWORD` · `local_private_archive/` · `.venv/` · `data/` (БД/логи/индексы) · `logs/` · `dist/` · `exporters/**/artifacts` (тяжёлые .NET) · большие `golden/*.json` · `*.parquet` · собранные бандлы.

## Правила
- Не добавлять зависимости без одобрения. Не ослаблять/скипать тесты ради зелёного. Не глушить ошибки широко. Секреты не читать и не печатать.
- **GUI-first для всего ЛЕС:** каждый активный runtime/env-фактор обязан быть видим в Совушке вместе с effective value, источником и признаком restart. Обычные параметры редактируются из GUI; опасные помечаются `Danger`, требуют явного подтверждения и имеют rollback; секреты показываются только как `задан/не задан` и заменяются masked-вводом; bootstrap paths/ports могут быть read-only, но не скрыты. Незарегистрированный фактор — диагностическая ошибка `UNREGISTERED_RUNTIME_FACTOR`, а не тайный override.
- **Windows / Unicode / PowerShell:** не передавать кириллицу в Python через PowerShell stdin/here-string и не собирать команды строковой конкатенацией. Для повторяемых операций использовать checked-in CLI/API-клиент, аргументы/JSON в UTF-8 и списки аргументов `subprocess`; Python entrypoint обязан включать UTF-8 output. Перед изменением runtime — dry-run с фактическим `%LOCALAPPDATA%\\Programs\\LES\\runtime`. Пути с кириллицей, пробелами и кавычками покрывать тестом.
- **Целостность решения модели в сметах:** в режиме `estimate` код и Codex-аудитор не заменяют,
  не удаляют и не «улучшают» выбранные моделью нормы, аналоги, coverage, ресурсы или коэффициенты.
  Код исполняет инструменты, проверяет структурную ссылочную целостность/единицы/provenance и считает.
  Первичный mapping сохраняется immutable-ревизией; рассчитанные труд, машины, материалы и влияние
  возвращаются той же модели, которая сама подтверждает или изменяет ресурсные решения. Основной XLSX
  строится по последней завершённой модельной ревизии, предыдущие решения не скрываются.
- Застрял/неоднозначно — **остановись и доложи**, не угадывай.

## Формат финального ответа
**Summary · Files changed · Checks run · Result · Risks/TODOs**
