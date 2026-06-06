# АРТЕЛЬ

**АРТЕЛЬ** — AI-платформа для управления разработкой Revit-семейств: от задания и исходников до спецификации, проверки, приемки и публикации во внутренний каталог.

Расшифровка: **Автоматизированная Разработка Типовых Элементов и Локальных семейств**.

Проект ранее назывался **Agnostis**. Это имя сохраняется в части технических путей, OpenAPI-файлов и legacy-кода до отдельного механического rename.

## About

В основе продукта — связка веб-сервиса и Revit-плагина.

Веб-сервис хранит задания, исходники, шаблоны, ФОП/shared parameters, стандарты, AI-спецификации, версии семейств и каталог. Revit-плагин получает формализованное задание, помогает разработчику применить параметры и типы, проверяет открытое семейство и отправляет RFA с отчетом обратно.

Главная продуктовая сущность — задание на разработку семейства. Каталог — результат принятых заданий и база для дальнейшего поиска и переиспользования.

Подробнее: [About](docs/about.md)

## Архитектурная позиция

АРТЕЛЬ не строит отдельный RAG с нуля. Для локального знания, поиска по BIM/RFA/CAD_BIM данным и объектному контексту используется LES.

Разделение ответственности:

- АРТЕЛЬ — задания, исходники, шаблоны, ФОП/shared parameters, AI-спецификации, Revit workflow, приемка и каталог.
- LES — retrieval, Qdrant/SQLite, CAD/BIM JSON ingestion, локальная модель, dataset routing и object-level context.
- OpenRouter — внешний AI provider для анализа, генерации черновиков спецификаций и объяснений поверх найденного контекста.

Ключевой принцип BIM RFA RAG: модель вторична, качество исходных данных первично. Чем больше принятых семейств, спецификаций, отчетов проверок и RFA-derived JSON попадает в контур знаний, тем лучше следующая разработка семейств.

## UI-прототип

- GitHub Pages: <https://proovcme.github.io/Agnostis/>
- Исходники макета: [app](app)
- Документация макета: [docs/ui-prototype.md](docs/ui-prototype.md)

## Документация

- [About](docs/about.md)
- [Концепция продукта](docs/product-concept.md)
- [Состав MVP](docs/mvp-scope.md)
- [MVP Roadmap](docs/mvp-roadmap.md)
- [MVP User Stories](docs/mvp-user-stories.md)
- [MVP API Contract](docs/mvp-api-contract.md)
- [Revit Add-In MVP](docs/revit-addin-mvp.md)
- [Technical Stack](docs/technical-stack.md)
- [OpenRouter Integration](docs/openrouter.md)
- [LES Integration](docs/les-integration.md)
- [Learning Loop](docs/learning-loop.md)
- [BIM RFA RAG](docs/bim-rfa-rag.md)
- [Архитектура системы](docs/system-architecture.md)
- [Доменная модель](docs/domain-model.md)
- [Backlog](docs/backlog.md)
- [UI-прототип](docs/ui-prototype.md)
- [Открытые вопросы](docs/open-questions.md)

## Codex skill

Для работы с проектом подготовлен skill:

- исходник в репозитории: [skills/agnostis/SKILL.md](skills/agnostis/SKILL.md)
- локальная установленная копия: `/Users/ovc/.codex/skills/agnostis/SKILL.md`

Skill фиксирует рабочий контекст АРТЕЛЬ, связь с LES, правила проверки backend/OpenAPI, документационный closeout и ограничения: Revit-плагин идет через backend АРТЕЛЬ, АРТЕЛЬ вызывает LES/OpenRouter, LES runtime не трогаем без явного запроса.

## Текущий состав репозитория

- `app/` — статический прототип веб-интерфейса АРТЕЛЬ.
- `docs/` — продуктовая и техническая документация.
- `backend/Agnostis.Api/` — skeleton backend API для MVP.
- `openapi/agnostis-mvp.yaml` — начальная OpenAPI-схема MVP.
- `skills/agnostis/` — Codex skill для работы с АРТЕЛЬ и LES RAG контуром.
- `.github/workflows/pages.yml` — публикация макета на GitHub Pages.
- `MyVeras.*`, `MyVeras.sln` — существующая кодовая база Revit-плагина, сохраненная как legacy/исходный материал. Бинарный `Dist/` в LES snapshot не переносится.

## Проверка прототипа локально

Рекомендуемый ручной стенд запускается через backend, чтобы UI сразу проверял API и LES:

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

Подробный сценарий: [RUNBOOK_HAND_TEST.md](RUNBOOK_HAND_TEST.md).

Статический прототип без backend все еще можно открыть отдельно:

```bash
python3 -m http.server 4173
```

После запуска открыть:

```text
http://127.0.0.1:4173/app/index.html
```
