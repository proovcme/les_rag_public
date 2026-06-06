# Technical Stack

## MVP Stack

### Backend

- ASP.NET Core / .NET 8.
- C# minimal APIs на первом этапе.
- PostgreSQL после замены in-memory skeleton.
- Object storage или filesystem-backed storage для файлов.
- OpenAPI как основной контракт для веба и Revit-плагина.

### Web Frontend

- На этапе прототипа: static HTML/CSS/JS.
- Для product MVP: React + TypeScript или Blazor WebAssembly требует отдельного решения.

Рекомендация: React + TypeScript для web workspace. Причина — быстрее собрать сложные таблицы, формы, вкладки, upload flow и review UI.

### Revit Add-In

- C#.
- WPF panel.
- .NET Framework 4.8 для Revit 2023-2025 совместимости.
- Typed API client, сгенерированный из OpenAPI или написанный вручную на старте.

### AI Layer

- Backend-owned orchestration.
- OpenRouter as the first provider.
- LES as the retrieval/local knowledge runtime.
- AI не вызывается напрямую из Revit-плагина.
- AI возвращает черновик спецификации, конфликты и вопросы, но не выполняет Revit-действия.

## Архитектурное решение

MVP разделяется на три независимых контура:

1. Web/backend — задания, файлы, спецификации, каталог.
2. Revit add-in — выполнение утвержденной спецификации.
3. AI orchestration — формализация задания и объяснение проверок.

Такое разделение важно: Revit-плагин должен работать и проверять семейство даже при недоступном AI.

## Что фиксируем сейчас

- Backend skeleton находится в [`backend/Agnostis.Api`](../backend/Agnostis.Api).
- OpenAPI contract находится в [`openapi/agnostis-mvp.yaml`](../openapi/agnostis-mvp.yaml).
- Документированный API contract находится в [`docs/mvp-api-contract.md`](mvp-api-contract.md).
- OpenRouter integration notes находятся в [`docs/openrouter.md`](openrouter.md).
- LES integration notes находятся в [`docs/les-integration.md`](les-integration.md).
- Windows build/test host доступен по SSH alias `legion`.

## Открытые технические решения

- Конкретная версия Revit для первого рабочего add-in.
- Способ авторизации плагина: token paste, device flow или OAuth.
- Физическое хранение shared parameter file для Revit API.
- Формат конвертации units между API и Revit internal units.
- Подход к генерации typed client для .NET Framework add-in.
