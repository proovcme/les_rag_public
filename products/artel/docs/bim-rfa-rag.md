# BIM RFA RAG

## Коротко

АРТЕЛЬ — это не обычный RAG по текстовым документам.

Это **BIM RFA RAG**: поиск и использование контекста из заданий, стандартов, ФОП/shared parameters, принятых RFA-семейств, отчетов проверки и recipes для подготовки спецификации семейства и проверяемых действий Revit-плагина.

## Основная схема

```mermaid
flowchart LR
    Task["Задание на семейство"] --> Package["Task Package"]
    Sources["Исходники: PDF, DOCX, XLSX, DWG, изображения"] --> Package
    FOP["ФОП / shared parameters"] --> Package
    Standards["BIM-стандарты"] --> Package
    Template["RFT / базовый RFA"] --> Package

    Package --> Retrieval["BIM RFA Retrieval"]

    Retrieval --> TextRag["Text RAG<br/>ТЗ, стандарты, инструкции"]
    Retrieval --> ParamRag["Parameter RAG<br/>ФОП, GUID, группы"]
    Retrieval --> RfaRag["RFA RAG<br/>принятые семейства"]
    Retrieval --> ValidationRag["Validation RAG<br/>ошибки и отчеты"]
    Retrieval --> RecipeRag["Recipe RAG<br/>архетипы и recipes"]

    TextRag --> AI["AI Orchestrator"]
    ParamRag --> AI
    RfaRag --> AI
    ValidationRag --> AI
    RecipeRag --> AI

    AI --> DraftSpec["Draft Family Specification"]
    DraftSpec --> Review["Проверка BIM-менеджером"]
    Review --> ApprovedSpec["Approved Family Specification"]
    ApprovedSpec --> Addin["Revit Add-In"]

    Addin --> RevitActions["Проверяемые действия:<br/>параметры, типы, материалы, validation"]
    RevitActions --> RFA["RFA + Validation Report"]
    RFA --> Catalog["Каталог семейств"]
    Catalog --> Learning["Learning Loop"]
    Learning --> Retrieval
```

## Что ищем

```mermaid
flowchart TB
    Query["Новое задание"] --> Search["Поиск похожего контекста"]

    Search --> A["Похожие задания"]
    Search --> B["Похожие принятые RFA"]
    Search --> C["Утвержденные спецификации"]
    Search --> D["ФОП/shared parameters"]
    Search --> E["Validation reports"]
    Search --> F["Recipes и archetypes"]

    A --> Context["Контекст для AI"]
    B --> Context
    C --> Context
    D --> Context
    E --> Context
    F --> Context

    Context --> Output["Спецификация + план адаптации"]
```

## Почему это не просто чат

Обычный чат дает текстовый ответ.

АРТЕЛЬ должен производить рабочие артефакты:

- `FamilySpecification`;
- список параметров;
- таблицу типов;
- сопоставление с ФОП;
- список конфликтов;
- `TransformationPlan`;
- validation checklist;
- action preview для Revit-плагина;
- итоговый validation report.

## Reference-Based Generation

Ключевой сценарий:

```mermaid
sequenceDiagram
    participant BM as BIM-менеджер
    participant Web as Web-сервис
    participant RAG as BIM RFA RAG
    participant AI as AI
    participant Addin as Revit-плагин
    participant Catalog as Каталог

    BM->>Web: Создает задание и загружает исходники
    Web->>RAG: Ищет похожие семейства и recipes
    RAG->>AI: Передает контекст и ограничения
    AI->>Web: Draft specification + adaptation plan
    BM->>Web: Проверяет и утверждает спецификацию
    Addin->>Web: Получает approved package
    Addin->>Addin: Применяет параметры, типы, материалы
    Addin->>Web: Отправляет RFA и validation report
    Web->>Catalog: Публикует принятую версию
    Catalog->>RAG: Пополняет базу примеров
```

## Уровни автоматизации

| Уровень | Название | Что делает система |
| --- | --- | --- |
| L0 | Similarity Search | Находит похожие семейства и задания |
| L1 | Clone + Retype | Берет RFA-образец и меняет типы, параметры, материалы |
| L2 | Clone + Parametric Adaptation | Адаптирует формулы, диапазоны, обязательные параметры |
| L3 | Recipe Extraction | Извлекает recipe из принятых образцов |
| L4 | Generate from Recipe | Создает новое семейство по recipe через Revit API |

Для MVP целевой уровень: **L1-L2**.

## Learning Loop

```mermaid
flowchart LR
    A["Задание"] --> B["Спецификация"]
    B --> C["Действия Revit-плагина"]
    C --> D["RFA"]
    D --> E["Validation Report"]
    E --> F["Приемка"]
    F --> G["Каталог"]
    G --> H["Reference Library"]
    H --> I["Лучший retrieval для новых заданий"]
    I --> A
```

Система улучшается только если хранится вся связка:

```text
задание -> спецификация -> действия -> RFA -> проверка -> приемка -> использование
```

## Практический вывод

Чем больше принято качественных семейств, тем лучше система:

- чаще находит подходящий образец;
- точнее предлагает параметры;
- быстрее собирает типоразмеры;
- заранее предупреждает о типовых ошибках;
- лучше выбирает recipe;
- уменьшает число ручных исправлений на приемке.

Но это работает только при дисциплине хранения контекста, проверок и решений приемки.
