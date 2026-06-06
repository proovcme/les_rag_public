# MVP API Contract

## Назначение

Этот документ фиксирует минимальный контракт между веб-сервисом, AI-слоем и Revit-плагином.

Формат ниже не является финальной OpenAPI-схемой, но задает структуру данных, endpoints и границы ответственности для MVP.

## Auth

MVP поддерживает token-based авторизацию.

Revit-плагин хранит access token пользователя локально и передает его в заголовке:

```http
Authorization: Bearer <token>
```

Минимальные роли:

- `bim_manager`
- `family_developer`
- `catalog_user`

## Endpoints для веб-сервиса

### Tasks

```http
GET /api/tasks
POST /api/tasks
GET /api/tasks/{taskId}
PATCH /api/tasks/{taskId}
POST /api/tasks/{taskId}/status
```

### Source Files

```http
POST /api/tasks/{taskId}/files
GET /api/tasks/{taskId}/files
GET /api/files/{fileId}/download
```

### Shared Parameter Profiles

```http
POST /api/shared-parameter-profiles
GET /api/shared-parameter-profiles
GET /api/shared-parameter-profiles/{profileId}
GET /api/shared-parameter-profiles/{profileId}/definitions
```

### Specifications

```http
POST /api/tasks/{taskId}/ai-analysis
GET /api/tasks/{taskId}/specification
PUT /api/tasks/{taskId}/specification
POST /api/tasks/{taskId}/specification/approve
```

### Revit Add-In

```http
GET /api/revit/tasks
GET /api/revit/tasks/{taskId}/package
POST /api/revit/tasks/{taskId}/validation-reports
POST /api/revit/tasks/{taskId}/submissions
```

### Catalog

```http
GET /api/catalog
GET /api/catalog/{catalogItemId}
GET /api/catalog/{catalogItemId}/versions
POST /api/catalog/{catalogItemId}/publish
POST /api/catalog/{catalogItemId}/update-task
GET /api/catalog/{catalogItemId}/download
```

`POST /api/catalog/{catalogItemId}/update-task` создает новое задание на обновление опубликованного семейства. Это основной мост от каталога обратно к производственному workflow.

## Task Package для Revit

Endpoint:

```http
GET /api/revit/tasks/{taskId}/package
```

Response:

```json
{
  "task": {
    "id": "task_0241",
    "number": "FAM-0241",
    "title": "Шкаф архивный металлический",
    "status": "ready_for_development",
    "revitCategory": "Furniture",
    "dueDate": "2026-06-12"
  },
  "specification": {
    "id": "spec_0241",
    "familyName": "Шкаф архивный металлический",
    "revitCategory": "Furniture",
    "templateFileId": "file_template_001",
    "sharedParameterProfileId": "fop_2026",
    "parameters": [],
    "types": [],
    "materials": [],
    "acceptanceChecklist": []
  },
  "files": [
    {
      "id": "file_001",
      "name": "ТЗ_шкаф_архивный.pdf",
      "kind": "brief",
      "downloadUrl": "/api/files/file_001/download"
    }
  ]
}
```

## SpecificationParameter

```json
{
  "id": "param_001",
  "name": "ADSK_Наименование",
  "source": "shared_parameter",
  "sharedParameterGuid": "4f5cb6a1-0000-0000-0000-000000000000",
  "dataType": "Text",
  "group": "Identity Data",
  "isInstance": false,
  "isRequired": true,
  "defaultValue": null,
  "formula": null,
  "notes": "Обязательный параметр каталога"
}
```

Allowed `source`:

- `shared_parameter`
- `family_parameter`
- `built_in`

## SpecificationType

```json
{
  "id": "type_001",
  "name": "Шкаф 800x400x1800",
  "values": {
    "Ширина": 800,
    "Глубина": 400,
    "Высота": 1800,
    "ADSK_Код изделия": "CAB-800-400-1800"
  },
  "notes": null
}
```

## Validation Report

Revit-плагин отправляет отчет:

```http
POST /api/revit/tasks/{taskId}/validation-reports
```

Payload:

```json
{
  "familyDocument": {
    "name": "Шкаф архивный металлический.rfa",
    "revitVersion": "2024",
    "category": "Furniture",
    "familyName": "Шкаф архивный металлический"
  },
  "status": "warning",
  "summary": "Найдены 2 предупреждения, критических ошибок нет.",
  "issues": [
    {
      "severity": "warning",
      "code": "missing_material_value",
      "title": "Не заполнен материал фасада",
      "description": "Тип Шкаф 1000x500x2000 не содержит значения параметра Материал фасада.",
      "revitElementId": null,
      "suggestedFix": "Заполнить значение параметра перед отправкой на приемку."
    }
  ],
  "actions": [
    {
      "type": "create_parameter",
      "target": "ADSK_Наименование",
      "status": "success"
    }
  ]
}
```

Allowed report `status`:

- `pass`
- `warning`
- `fail`

Allowed issue `severity`:

- `info`
- `warning`
- `error`

## Submission

```http
POST /api/revit/tasks/{taskId}/submissions
```

Multipart payload:

- `rfaFile`
- `validationReportId`
- `comment`
- `metadata`

Result:

```json
{
  "familyVersionId": "version_001",
  "version": "0.1.0",
  "status": "submitted_for_review"
}
```

## Ошибки

Все API ошибки возвращаются в одном формате:

```json
{
  "error": {
    "code": "specification_not_approved",
    "message": "Спецификация не утверждена и не может быть выдана в Revit.",
    "details": {}
  }
}
```

## Важные ограничения

- Revit-плагин не должен получать draft specification.
- Shared parameter добавляется только при наличии GUID.
- Backend не должен доверять validation report как единственному источнику истины для приемки.
- AI не имеет прямого endpoint для выполнения действий в Revit.
