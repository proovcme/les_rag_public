# АРТЕЛЬ Hand Test Runbook

Цель: запустить АРТЕЛЬ как локальный ручной стенд и проверить основной MVP-контур без Revit.

## Что должно работать

- открыть UI из backend root `/`;
- увидеть live Backend API status;
- увидеть live LES status;
- увидеть seed data из backend;
- запросить LES RAG context по заданию `task_0241` через `ARTEL_Index`;
- проверить catalog/task endpoints через `curl`.

## LES seed перед тестом

Если LES установлен с нуля и индекс пустой, посадить public-safe учебный кейс:

```bash
cd ../..
uv run python tools/seed_artel_learning_cases.py --verify-search
```

Команда пишет markdown-проекцию в `RAG_Content/ARTEL/family_learning_cases/`,
запускает только `/api/rag/sync/ARTEL` и проверяет, что `/api/search` с
`dataset_filter="ARTEL"` вернул хотя бы один chunk.

## Запуск

Требуется .NET SDK 8+.

```bash
cd products/artel
LES_BASE_URL=http://127.0.0.1:8050 \
LES_TIMEOUT_SECONDS=20 \
dotnet run --project backend/Agnostis.Api --urls http://127.0.0.1:5057
```

Открыть:

```text
http://127.0.0.1:5057/
```

Если LES после переустановки пустой, это не блокер для ручного UI-теста. Но для продуктового теста `LES context` должен идти по `dataset_filter="ARTEL"` и возвращать не пустой result после seed-команды выше.

## Seed Revit Family Methodology

Для продуктового теста семейств загрузите Autodesk guide и ARTEL quality basis:

```bash
python3 tools/seed_artel_family_guides.py \
  --guide-pdf /path/to/revit_family_creation_guide_autodesk_2017.pdf \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Ожидаемый результат: `ARTEL_Index` содержит `FAMILY_GUIDE`, `FOP_PROFILE` и
`LEARNING_CASE`. После этого АРТЕЛЬ может просить LES дать требования к
созданию/качеству Revit-семейств и точные ФОП/ADSK параметры.

## Seed Revit API Reference

Для ручного теста Revit add-in/extractor посадите API-базу:

```bash
python3 tools/seed_artel_revit_api_reference.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

Ожидаемый результат: `ARTEL_Index` содержит `REVIT_API_REFERENCE`. После этого
АРТЕЛЬ может просить LES дать API-контекст по `FamilyManager`,
`FilteredElementCollector`, транзакциям, shared parameters, connector extraction
и batch JSON extraction для `.rfa`/`.rft`.

## Seed Family Factory Sources

Для подготовки фабрики семейств посадите модель Revit и API symbol map:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --seed-defaults \
  --verify-search
```

Ожидаемый результат: `ARTEL_Index` содержит:

- `REVIT_MODEL_GUIDE` для понятий Element/Parameter/Category/Family/Type;
- `REVIT_API_SYMBOL_MAP` для поиска точных API классов, методов, свойств,
  namespace и документационных GUID/link ids.

Для полной SDK-базы на Windows/Revit host используйте локальный `RevitAPI.chm`
или извлеченный HTML:

```bash
python3 tools/seed_artel_revit_factory_sources.py \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --chm /path/to/RevitAPI.chm \
  --verify-search
```

Autodesk SDK/CHM хранить как runtime/private RAG data, не как public repo
content.

Если backend запущен на другой машине и ходит в LES по ZeroTier/LAN, `GET /api/integrations/les/status` может быть `ok`, а `POST /api/tasks/task_0241/rag-context` может вернуть `status: "upstream_error"` с `httpStatus: 401`, если для LES `/api/search` нужен API key. Это проверяет, что цепочка АРТЕЛЬ -> LES работает до auth boundary. Для содержательного retrieval используйте локальный `LES_BASE_URL=http://127.0.0.1:8050`, trusted network или задайте `LES_API_KEY`.

## Быстрый smoke

Из корня LES:

```bash
python3 tools/smoke_artel_hand_test.py --base-url http://127.0.0.1:5057
```

Проверяется:

- `/`;
- `/health`;
- `/api/integrations/les/status`;
- `/api/tasks`;
- `/api/tasks/task_0241/rag-context`;
- `/api/catalog`.

Для Windows/Revit host `legion` есть отдельный результат smoke:
[docs/legion-revit-smoke.md](docs/legion-revit-smoke.md).

Для загрузки найденного ФОП/shared parameters в LES используйте:

```bash
python3 tools/seed_artel_fop_profiles.py --fop /path/to/FOP2021.txt --verify-search
```

## Ручной сценарий

1. Открыть `/`.
2. В правом AI-инспекторе проверить блок runtime.
3. Нажать `API smoke`.
4. Нажать `LES context`.
5. Перейти в `Каталог`.
6. Вернуться в `Задания`, открыть другую карточку.
7. Проверить, что UI не падает, а backend endpoints отвечают JSON.

## Ограничения текущего стенда

- Данные in-memory, после restart изменения сбрасываются.
- OpenRouter endpoint пока contract placeholder.
- Revit add-in остается legacy source snapshot.
- LES может быть `degraded/empty` после clean install; минимальная seed-база `FamilyLearningCase` уже есть, но реальные accepted RFA cases нужно добавлять отдельно.
