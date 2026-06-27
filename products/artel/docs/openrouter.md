# OpenRouter Integration

## Decision

АРТЕЛЬ MVP uses OpenRouter as the first AI provider for task analysis and specification drafting.

OpenRouter is treated as a backend dependency. The Revit add-in must not call OpenRouter directly.

Official docs:

- <https://openrouter.ai/docs/api-reference/overview>
- <https://openrouter.ai/docs/api-reference/chat-completion>

## MVP Responsibilities

AI через OpenRouter должен помогать с:

- разбором ТЗ;
- извлечением параметров;
- извлечением типоразмеров;
- сопоставлением требований с ФОП;
- генерацией черновика спецификации;
- генерацией уточняющих вопросов;
- объяснением validation issues.

AI не должен:

- менять Revit-документ напрямую;
- выдавать неподтвержденную спецификацию в Revit-плагин;
- принимать решение о публикации семейства в каталог.

## Configuration

Backend получает ключ из environment variable:

```text
OPENROUTER_API_KEY
```

Пример конфигурации:

```json
{
  "Ai": {
    "Provider": "OpenRouter",
    "OpenRouter": {
      "BaseUrl": "https://openrouter.ai/api/v1",
      "ApiKeyEnvironmentVariable": "OPENROUTER_API_KEY",
      "DefaultModel": "<openrouter-model-id>",
      "HttpReferer": "https://proovcme.github.io/Agnostis/",
      "AppTitle": "ARTEL"
    }
  }
}
```

Model ID не хардкодится в MVP-документации. Его нужно выбрать отдельно под задачу: быстрый разбор документов, точная структуризация JSON, стоимость, доступность и лимиты.

## Request Shape

OpenRouter использует OpenAI-compatible chat completions API.

Backend adapter должен отправлять:

- system prompt с правилами формализации спецификации;
- task context;
- extracted source snippets;
- parsed FOP definitions;
- expected JSON schema;
- selected model ID.

## Output Contract

OpenRouter response должен быть преобразован backend-сервисом в доменную структуру:

- `FamilySpecification`;
- `SpecificationParameter[]`;
- `SpecificationType[]`;
- `SpecificationMaterial[]`;
- `acceptanceChecklist[]`;
- `conflicts[]`;
- `clarifyingQuestions[]`.

Плагин получает только утвержденную `FamilySpecification`, не raw AI response.

## MVP Endpoint

```http
POST /api/tasks/{taskId}/ai-analysis
```

В текущем backend skeleton endpoint зарезервирован и возвращает draft specification без фактического вызова OpenRouter. Реальный adapter добавляется после выбора модели и формата JSON schema.

## Risks

- Модели могут отличаться по качеству структурированного JSON.
- Нужно логировать model ID, provider, token usage и source references.
- Нужна защита от prompt injection в загруженных документах.
- Нужен retry/fallback policy.
- Нужен лимит размера task context.
