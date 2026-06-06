# АРТЕЛЬ Hand Test Runbook

Цель: запустить АРТЕЛЬ как локальный ручной стенд и проверить основной MVP-контур без Revit.

## Что должно работать

- открыть UI из backend root `/`;
- увидеть live Backend API status;
- увидеть live LES status;
- увидеть seed data из backend;
- запросить LES RAG context по заданию `task_0241`;
- проверить catalog/task endpoints через `curl`.

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

Если LES после переустановки пустой, это не блокер для ручного UI-теста. В этом случае `LES context` должен вернуть успешный backend response с пустым retrieval result.

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
- LES может быть `degraded/empty` после clean install; для полноценного RAG нужна seed-база `FamilyLearningCase`.
