# Backend

## Стек MVP

Backend MVP предлагается делать на ASP.NET Core:

- .NET 8;
- C# minimal APIs;
- PostgreSQL после перехода от in-memory skeleton;
- object storage или filesystem-backed storage для RFA/исходников;
- OpenAPI contract в [`../openapi/agnostis-mvp.yaml`](../openapi/agnostis-mvp.yaml).

Причина выбора: Revit-плагин и существующая кодовая база уже C#-ориентированы. Единый язык для API DTO, клиента плагина и части доменной модели снижает интеграционные риски.

## Текущий skeleton

Проект:

```text
backend/Agnostis.Api
```

Сейчас это in-memory API skeleton без внешних NuGet-пакетов.

Endpoints:

- `GET /health`
- `GET /api/integrations/les/status`
- `GET /api/tasks`
- `POST /api/tasks`
- `GET /api/tasks/{taskId}`
- `POST /api/tasks/{taskId}/ai-analysis`
- `POST /api/tasks/{taskId}/rag-context`
- `GET /api/tasks/{taskId}/specification`
- `PUT /api/tasks/{taskId}/specification`
- `POST /api/tasks/{taskId}/specification/approve`
- `GET /api/revit/tasks`
- `GET /api/revit/tasks/{taskId}/package`
- `POST /api/revit/tasks/{taskId}/validation-reports`
- `GET /api/validation-reports`
- `GET /api/tasks/{taskId}/learning-case`
- `GET /api/validation-reports/{reportId}/learning-case`
- `GET /api/catalog`
- `GET /api/catalog/{catalogItemId}`
- `GET /api/catalog/{catalogItemId}/versions`
- `POST /api/catalog/{catalogItemId}/publish`
- `POST /api/catalog/{catalogItemId}/update-task`

## Запуск

Требуется установленный .NET SDK 8.

```bash
dotnet run --project backend/Agnostis.Api
```

Проверка:

```bash
curl http://localhost:5000/health
```

Backend also serves the ARTEL UI prototype from `/` when launched from this
repository layout:

```bash
dotnet run --project backend/Agnostis.Api --urls http://127.0.0.1:5057
open http://127.0.0.1:5057/
```

Manual test runbook: [`../RUNBOOK_HAND_TEST.md`](../RUNBOOK_HAND_TEST.md).

## Runtime data

Validation reports are persisted to disk and reloaded on backend startup. By
default the backend writes to:

```text
backend/Agnostis.Api/artel_data/validation_reports/
```

Override the root with:

```bash
ARTEL_DATA_DIR=/path/to/artel_data dotnet run --project backend/Agnostis.Api
```

`GET /api/validation-reports` returns archived reports newest first; add
`?taskId=task_0241` to filter a task.

To seed archived backend reports into LES:

```bash
python3 tools/seed_artel_backend_reports.py \
  --artel-url http://127.0.0.1:5057 \
  --task-id task_0241 \
  --runtime-root /Users/ovc/Projects/LES_v2_reinstall_stress \
  --proxy-url http://127.0.0.1:8050 \
  --verify-search
```

## Проверка

На текущей машине `dotnet` отсутствует, поэтому сборка backend skeleton здесь не выполнялась. Код и contract подготовлены для проверки в окружении с .NET SDK 8.

Фактическая проверка выполнена на Windows-хосте `legion` по SSH:

- `dotnet build backend/Agnostis.Api/Agnostis.Api.csproj --configuration Release`
- `dotnet run --no-build --configuration Release --urls http://127.0.0.1:5057`
- `GET /health`
- `GET /api/integrations/les/status`
- `POST /api/tasks/task_0241/ai-analysis`
- `POST /api/tasks/task_0241/rag-context`
- `GET /api/catalog/catalog_001`
- `GET /api/catalog/catalog_001/versions`
- `POST /api/catalog/catalog_001/publish`
- `POST /api/catalog/catalog_001/update-task`

Результат: build без предупреждений и ошибок, `/health` вернул `{"status":"ok"}`, AI-analysis endpoint вернул `provider: "openrouter"`, catalog endpoints вернули detail/versions, publish создал версию, update-task создал задание `FAM-0002`.

Persistence smoke на `legion` выполнен 2026-06-06:

- `ARTEL_DATA_DIR=C:\Users\Oleg\AppData\Local\Temp\artel-backend-persist\runtime-data`
- `POST /api/revit/tasks/task_0241/validation-reports`
- создан архивный файл `validation_reports/report_*.json`
- backend остановлен и запущен снова
- `GET /api/validation-reports?taskId=task_0241` вернул восстановленный report
- `GET /api/validation-reports/{reportId}/learning-case` вернул `case_id = validation_{reportId}`

LES smoke через ZeroTier:

- `LES_BASE_URL=http://10.195.146.98:8050`
- `GET /api/integrations/les/status` вернул `status: "ok"`
- `POST /api/tasks/task_0241/rag-context` проходит полный путь до LES `/api/search` и возвращает `status: "ok"` при успешном retrieval
- контрольный прогон с `LES_TIMEOUT_SECONDS=10` вернул `status: "timeout"`, то есть backend не зависает на долгом LES-вызове
- повторный прогон с рабочим timeout может вернуть `status: "upstream_error"` при `429` от LES, если локальный runtime занят или ограничивает параллельные запросы

Важно: `rag-context` в текущем MVP вызывает LES `/api/search`, а не `/api/chat`, поэтому не должен запускать локальную генерацию. Суммаризацию найденного контекста нужно делать отдельным шагом через OpenRouter или LES chat.

## LES configuration

```json
{
  "Les": {
    "BaseUrl": "http://127.0.0.1:8050",
    "ApiKey": "",
    "TimeoutSeconds": 120
  }
}
```

Environment variables:

```bash
LES_BASE_URL=http://127.0.0.1:8050
LES_API_KEY=
LES_TIMEOUT_SECONDS=120
```
