# AGENTS.md — гид для AI-агентов (Л.Е.С. / LES_v2)

Канонический файл для любого агента (Codex, Claude Code, Cursor). Держи коротким; длинные процедуры — в доках и `SKILL.md`.

## Что это
Локальный **строительный evidence-harness** (RAG — один из слоёв, не продукт): проект/датасет → вопрос → правильный workflow → источники → расчёт КОДОМ → blockers/MISSING → проверяемое evidence → ответ. FastAPI (proxy :8050 + MLX-host :8080) + NiceGUI UI «Совушка» (:8051) + Qdrant (:6333), Python 3.12 на **uv**. Сервисы — launchd. Принцип: **модель связывает, код считает**; число без происхождения — не результат.

## Канон документации (читать В ЭТОМ ПОРЯДКЕ — остальное историческое)
> ⚠️ Доков много и они разных эпох. **Текущая правда — только эта цепочка.** Всё, что ниже в «Историческом», — контекст, НЕ инструкция; не принимай старый слой за актуальный.

1. **AGENTS.md** (этот файл) — канон для агента.
2. **[SKILL.md](SKILL.md)** — рантайм/эксплуатация (порты, деплой = `cp`+`write_deploy_stamp`, доступы, гейты). Источник истины по запуску.
3. **[docs/CODE_MAP.md](docs/CODE_MAP.md)** — карта кода: где что лежит, поток чата/индексации, «где искать что». Сначала карта → точечный поиск → исходники.
4. **[ROADMAP_TO_V1.md](ROADMAP_TO_V1.md)** — что считается v1, этапы, блокеры (актуальный план).
5. **[docs/unified_harness_failure_ledger.md](docs/unified_harness_failure_ledger.md)** — журнал реальных провалов и как закрыты (читать, чтобы не наступить снова).
6. **[docs/TEST_INVENTORY.md](docs/TEST_INVENTORY.md)** — тесты v0.16–v0.22 (что и где покрыто).

Доп. при правке конкретного ядра: **алгоритм-доки** (0 LLM) — [docs/ALGO-table-query.md](docs/ALGO-table-query.md), [docs/ALGO-spec-to-bor.md](docs/ALGO-spec-to-bor.md) и др. в `docs/ALGO-*`; «что НЕ читать» — [docs/AGENT_NOTES.md](docs/AGENT_NOTES.md).

**Историческое (контекст, НЕ текущая правда):** датированные саммари/хендоффы/репорты и заменённые планы сведены в **[`docs/archive/`](docs/archive/)** (`SESSION_SUMMARY_*`, `ROADMAP_LES_v2.0`, `DOCS_*AUDIT*`, хендоффы — см. `docs/archive/README.md`). На месте, но тоже историческое: `README_v2.0.md`, `LES_MASTER_DOC_v2_1.md`, `INFRASTRUCTURE_v2.0.md`, `RAG_MODERNIZATION_PLAN.md`, `ARTICLE_*.md`. Полезны для «почему так», но версии/решения могут устареть — сверяй с каноном и кодом (`/api/version`).

## Гейт проверки
- **`make verify`** — офлайн: `compileall` (синтаксис) + `pytest --collect-only` (импорт-смоук всех тестов, без живых сервисов). Гонять перед готовностью.
- **`make test`** — полная сюита (≡ `uv run pytest -q` из [SKILL.md](SKILL.md)); **часть тестов требует живых Qdrant/MLX** — это нормально, что без них они падают/скипаются.
- **Доменный гейт** (после правок retrieval/router): `uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json` — база **16/16** ([SKILL.md](SKILL.md): качество FIRE/HVAC — это доменная приёмка, не точечные фиксы).
- **CI нет** — гейт запускается вручную.

## Рабочий цикл изменения
1. Сузить контекст (CODE_MAP → узкий поиск, не открывать тяжёлое).
2. Минимальный дифф.
3. Точечная проверка (один тест: `uv run pytest tests/test_X.py`).
4. **`make verify`** до объявления готовности.

## Грабли и осторожность
- **uv-проект:** зависимости/запуск через `uv run`. Не ставить пакеты без одобрения (`uv add` меняет lock).
- **НЕ дёргать сервисы** (launchd: qdrant/mlx/proxy/sovushka/pauk) без явной нужды — это живой рантайм. Рестарты — `tools/les_runtime_control.py` / `lesctl.py`, осознанно.
- **Деструктивное — запрещено без явной просьбы** (Guardrails в [SKILL.md](SKILL.md)): не удалять `data/qdrant/`, `data/les_meta_qwen.db`, `storage/`, `RAG_Content/`; не запускать полный реиндекс; беречь таблицу `structured_rules`; `VALIDATOR_BACKEND=rules` — текущий стабильный дефолт.
- **MLX/память:** модели TTL-выгружаются, metal-семафор; не ломать `backend/mlx_adapter.py` логику памяти.
- Правка движка CAD/BIM (`frontend/cad_bim_viewer/`) — отдельная Vite-сборка, не править собранный `dist/`.

## Что НЕ читать (токены/секреты)
`.env` и любые креды/`JWT_SECRET`/`ADMIN_PASSWORD` · `local_private_archive/` · `.venv/` · `data/` (БД/логи/индексы) · `logs/` · `dist/` · `exporters/**/artifacts` (тяжёлые .NET) · большие `golden/*.json` · `*.parquet` · собранные бандлы.

## Правила
- Не добавлять зависимости без одобрения. Не ослаблять/скипать тесты ради зелёного. Не глушить ошибки широко. Секреты не читать и не печатать.
- Застрял/неоднозначно — **остановись и доложи**, не угадывай.

## Формат финального ответа
**Summary · Files changed · Checks run · Result · Risks/TODOs**
