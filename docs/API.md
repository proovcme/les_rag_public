# LES API

Базовый proxy URL локального runtime: `http://127.0.0.1:8050`.

`https://les.ovc.me` — отдельный симулятор леса и homepage проекта, не relay и не API endpoint ЛЕС. Сетевой backend задаётся оператором явно.

## Auth

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/auth/verify` | Проверить API key / admin password |
| `GET` | `/api/auth/trust` | Диагностика trusted-network доступа |
| `GET` | `/api/auth/keys` | Список ключей, admin only |
| `POST` | `/api/auth/keys` | Создать ключ, admin only |
| `POST` | `/api/auth/keys/toggle` | Включить/выключить ключ |
| `POST` | `/api/auth/keys/reset-device` | Сбросить device binding |
| `DELETE` | `/api/auth/keys/{key_value}` | Удалить ключ |

Для public access используйте `X-API-Key`. Trusted networks настраиваются через `.env`; не расширяйте CIDR без явной причины.

## Runtime

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/health` | Health proxy, RAG backend, validator/embedder metadata |
| `GET` | `/api/status` | Runtime status, memory profile, MLX process status |
| `GET` | `/api/metrics` | Метрики proxy/RAG |
| `GET` | `/api/diag` | Диагностический отчет |
| `GET` | `/api/indexing-mode` | Текущий режим chat/indexing |
| `POST` | `/api/indexing-mode` | Переключить runtime profile |
| `GET` | `/api/runtime/dispatcher/status` | Dispatcher, memory gate, reindex status |
| `POST` | `/api/runtime/dispatcher/reindex/start` | Запустить guarded reindex |
| `POST` | `/api/runtime/dispatcher/reindex/pause` | Поставить guarded reindex на паузу |
| `POST` | `/api/runtime/dispatcher/reindex/resume` | Возобновить guarded reindex |
| `POST` | `/api/runtime/dispatcher/mlx/unload` | Выгрузить MLX модели |

## Doc Review / Normcontrol

Самостоятельные `/api/normcontrol` и `/api/doc-review` удалены в
0.30.18/0.30.21. Живой операторский workflow — `/api/checklist-review`; он
переиспользует внутренние `normcontrol_service` и `doc_review_service`.

## Search

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/search` | Retrieval-only поиск без LLM generation |

`/api/search` предназначен для АТЛАС, АРТЕЛЬ и других UI, которым нужен быстрый ranked context без запуска chat model.

Request:

```json
{
  "query": "Найди похожие BIM/RFA/CAD_BIM кейсы для шкафа",
  "dataset_filter": "CAD_BIM",
  "top_k": 8,
  "max_chars": 1600,
  "include_trace": false,
  "include_context": false
}
```

`question` принимается как alias к `query` для совместимости с существующими chat-oriented clients.

Response:

```json
{
  "query": "Найди похожие BIM/RFA/CAD_BIM кейсы для шкафа",
  "dataset_filter": "CAD_BIM",
  "dataset_ids": ["..."],
  "top_k": 8,
  "count": 1,
  "route": {
    "dataset_filter": "CAD_BIM",
    "reason": "explicit_filter"
  },
  "chunks": [
    {
      "rank": 1,
      "score": 0.81,
      "doc_id": "...",
      "doc_name": "cad_bim_json_....md",
      "content": "...",
      "metadata": {},
      "source_id": "..."
    }
  ]
}
```

## Chat

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/chat` | RAG chat с источниками и SafeRAG validation |
| `GET` | `/api/chat/history` | История сообщений |
| `GET` | `/api/chat/sessions` | Сессии чата |
| `POST` | `/api/chat/history/{history_id}/feedback` | Feedback: good/bad/wrong dataset/source |
| `GET` | `/api/chat/learning` | Learning trace для будущей настройки routing |

`/api/chat` возвращает документные `sources` для UI-чипов и отдельный `source_map`: карту
фактических prompt-блоков `Источник N`, по которым модель цитирует ответ. Один документ может дать
несколько чанков (`Источник 1`, `Источник 5` и т.п.), поэтому `source_map` — канон для проверки
номеров источников в тексте ответа. Поле `latency_phases` дублируется в `retrieval_trace` и показывает
фазы `retrieval/context/generation/validation/overhead/total`.

Минимальный запрос:

```bash
curl -X POST http://127.0.0.1:8050/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Что есть в базе по эвакуационным путям?","dataset_filter":"NTD_Index"}'
```

## RAG Datasets

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/rag/datasets` | Список datasets |
| `POST` | `/api/rag/datasets` | Создать dataset |
| `DELETE` | `/api/rag/datasets/{dataset_id}` | Удалить dataset |
| `GET` | `/api/rag/documents` | Документы и статусы |
| `GET` | `/api/rag/sources` | Источники |
| `GET` | `/api/rag/smart-plan` | Dry-run routing плана |
| `POST` | `/api/rag/sync-smart` | Зарегистрировать файлы по smart routing |
| `POST` | `/api/rag/upload-smart` | Загрузить файл и выбрать dataset автоматически |
| `POST` | `/api/rag/parse-batch/{dataset_id}` | Parse/index batch |
| `POST` | `/api/rag/parse-scheduler` | Guarded parse scheduler |
| `POST` | `/api/rag/retrieve-debug` | Debug retrieval без генерации |
| `GET` | `/api/rag/watch/status` | Folder watcher status |
| `POST` | `/api/rag/watch/scan` | Зарегистрировать new/changed |
| `GET` | `/api/rag/watch/reindex-plan` | Dry-run route_changed reindex |

## Служебные Источники

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/service-sources` | Реестр файлов/датасетов, нужных ЛЕСу для смет и нормоконтроля; для сложных источников отдаёт `required_documents` manifest |
| `GET` | `/api/service-sources/{source_id}` | Один служебный источник: status, файлы, факты, missing-action, manifest требуемых документов |
| `POST` | `/api/service-sources/{source_id}/process` | Безопасная операторская Play-проверка источника: найдено/не найдено, какие классы документов ready/partial/missing/blocked |

Реестр задаётся в `config/service_sources.yaml`: ГЭСН, ФГИС ЦС, сметные коэффициенты/шаблоны,
`SMETA_SERVICE`, СПДС rulepack, нормативный RAG и layout-reference. В GUI это блок
**Инструменты → Служебные источники данных** и кнопка **Служебные источники** в чате. Для
`SMETA_SERVICE` Play проверяет классы: нормы/ресурсы, цены/ФГИС/КАЦ/индексы, методика/НР/СП/РИМ
и формы/шаблоны.

## CAD/BIM

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/cad-bim/import` | Импорт canonical `cad_bim_graph.json` |
| `GET` | `/api/cad-bim/source` | Источник для АТЛАС viewer |
| `GET` | `/api/cad-bim/graph/summary` | Сводка CAD/BIM graph |
| `GET`/`POST` | `/api/cad-bim/highlight` | Последняя подсветка элементов (W6.7) |

Внешний Speckle-коннектор (`/api/speckle/*`) удалён 2026-06-14. Путь CAD/BIM: exporter -> JSON graph -> `/api/cad-bim/import` -> `SYNC CAD/BIM` в САМОВАРе.

## ВОР (ведомости объёмов работ)

Старый `/api/bor` удалён в 0.30.21. Живые входы — чатовый
`build_vor_workbook` и MCP `les_bor`/`les_spec_to_bor`; расчётные сервисы
сохранены.

## Дифф (исторический W12.1)

Изолированный `/api/diff/*` удалён в 0.30.17: он не имел UI, model tool или
runtime-потребителя и не прошёл live-приёмку. Активный список импортов модели
остаётся в `GET /api/cad-bim/imports`; CAD/BIM viewer и graph data не изменялись.

## Нормоконтроль (формальный)

Legacy `/api/normcontrol/*` и `/api/doc-review/*` удалены. Формальные NK-01…NK-04
остаются внутренним слоем checklist review.

Проверки v1 (детерминированные, без LLM): NK-01 форматы листов по ГОСТ 2.301 (вкл. кратные), NK-02 текстовый слой (сканы), NK-03 согласованность шифра комплекта, NK-04 ведомость чертежей ↔ фактический состав. v2 (графы основной надписи/подписи) — требует layout-анализа штампа, см. LES3_PLAN W13.1.

## Карта файлов (сканер папок)

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/filemap/scan` | Скан/инкрементальный рескан корня `{path}` — только метаданные |
| `GET` | `/api/filemap/search?q=&ext=&cipher=` | Поиск по карте (имя/путь/шифр НТД-комплекта) |
| `POST` | `/api/filemap/index` | Проиндексировать выбранное из карты (создать/дополнить датасет) |
| `GET` | `/api/filemap/candidates` | Папки-кандидаты (с шифрами НТД) |
| `GET` | `/api/filemap/stats` | Корни, топ расширений, файлы с шифрами |

«ЛЕС поверх файлопомойки» (W15): карта строится без чтения содержимого и без LLM; из неё — выборочная индексация (W15.2).

## External Radar

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/external-radar/summary?limit=15` | Обзор внешних корней, filemap-кандидатов и уже in-place документов без reindex/OCR/LLM |
| `GET` | `/api/rag/cloud-drives` | Статус web-провайдеров Google Drive / Яндекс Диск и найденные локальные sync-папки |
| `POST` | `/api/rag/cloud-drives/list` | Посмотреть содержимое облачной папки по Google folder id/link или `disk:/...` пути Яндекс Диска |
| `POST` | `/api/rag/cloud-drives/sync` | Синхронизировать облачную папку в mirror-кэш и зарегистрировать её как датасет через `index-external` |

Радар объединяет `LES_EXTERNAL_SOURCE_ROOTS`, web/sync cloud roots, `file_map.db` и MetaDB `documents.source_path`.
Он делает только shallow-статистику корней; глубокий обход диска остаётся явным действием
`POST /api/filemap/scan`.

## Задачник

| Метод | Путь | Назначение |
|---|---|---|
| `POST` | `/api/tasks` | Создать задачу `{title, details?, dataset_filter?, link?}` |
| `GET` | `/api/tasks?status=` | Список (open/in_progress/done/dropped) |
| `PATCH` | `/api/tasks/{id}` | Обновить статус/текст |

Чат-команды (детерминированно, без LLM, работают даже при memory-guard): «поставь задачу …», «что по задачам?», «задача N готова».

Заметки оператора (W16.3, та же механика): «запомни: …», «заметки», «забудь заметку N». REST: `POST/GET /api/notes`, `DELETE /api/notes/{id}`. UI: вкладка «ЗАДАЧИ» классической админки. Релевантные заметки и прошлые удачные ответы подмешиваются в контекст ответа автоматически (лексический recall, W16.1).

## Mail

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/mail/status` | Mail settings/status без раскрытия секретов |
| `POST` | `/api/mail/import-local` | Импорт локальных `.eml/.msg` |
| `POST` | `/api/mail/import-imap` | Импорт IMAP писем |
| `POST` | `/api/mail/import-apple-mail` | Импорт Apple Mail |
| `GET` | `/api/mail/messages` | Поиск писем |
| `GET` | `/api/mail/threads` | Список цепочек |
| `GET` | `/api/mail/threads/{thread_key}` | Детали цепочки |

## Jobs And Logs

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/jobs` | История jobs |
| `GET` | `/api/jobs/summary` | Сводка active/recent jobs |
| `GET` | `/api/logs/recent` | Последние proxy logs |
| `GET` | `/api/logs/stream` | Log stream |

## Settings

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/api/settings` | Runtime/provider settings без секретов |
| `POST` | `/api/settings` | Обновить provider/mail settings |

`GET /api/settings` не должен раскрывать реальные API keys. Секреты задаются через `.env` или write-only settings payload.
