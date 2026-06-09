# AGENTS.md — гид для AI-агентов (Л.Е.С. / LES_v2)

Канонический файл для любого агента (Codex, Claude Code, Cursor). Держи коротким; длинные процедуры — в доках и `SKILL.md`.

## Что это
Локальная экспертная RAG-система: FastAPI (proxy :8050 + MLX-host :8080) + NiceGUI UI «Совушка» (:8051) + Qdrant (:6333), Python 3.12 на **uv**. Запускается набором сервисов (launchd/docker).

## Старт (читать ПЕРВЫМ — экономит токены)
- **[docs/CODE_MAP.md](docs/CODE_MAP.md)** — карта кода: топология, поток чата/индексации, пакеты, «где искать что». Сначала карта → точечный поиск → исходники.
- **[SKILL.md](SKILL.md)** — рантайм-знание оператора (порты, доступы, доверенные сети, P.A.U.K./V.O.L.K., внешний `les.ovc.me`). НЕ дублировать сюда.
- Архитектура: [INFRASTRUCTURE_v2.0.md](INFRASTRUCTURE_v2.0.md) · [PROXY_ARCHITECTURE.md](PROXY_ARCHITECTURE.md) · [LES_MASTER_DOC_v2_1.md](LES_MASTER_DOC_v2_1.md) · [RAG_MODERNIZATION_PLAN.md](RAG_MODERNIZATION_PLAN.md) · [MLX_GUIDE.md](MLX_GUIDE.md) · термины [DICTIONARY_LES_v2.0.md](DICTIONARY_LES_v2.0.md) · «не читать» [docs/AGENT_NOTES.md](docs/AGENT_NOTES.md).

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
