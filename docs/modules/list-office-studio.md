# Л.И.С.Т. · Студия офисных документов

Статус: **✅ актуально для агентного GUI-среза**.

## Назначение

Студия превращает действующие дескрипторы Forms в самостоятельный пользовательский GUI-поток:
выбрать датасет, том и конкретные файлы-основания, затем шаблон и объект, получить от Л.Е.С. предложения
по ручным полям с evidence/confidence, проверить и применить их, создать DOCX/XLSX
и скачать его из журнала ревизий.

Оригиналы датасета не открываются на запись. Сформированный файл является новым
артефактом Л.И.С.Т., а не исправленной копией источника.

## Точки входа

- GUI: `sovushka/pages/documents.py` → отдельная вкладка «Студия»;
- API: `POST /api/forms/agent-draft`, `GET/POST /api/forms/artifacts`,
  `GET /api/forms/artifacts/{revision_id}/download`;
- typed IR: `proxy/services/list_office_agent_service.py`;
- реестр и immutable-layout: `proxy/services/list_office_service.py`;
- дескрипторы/рендереры: `proxy/services/forms_service.py`;
- шаблоны: `config/forms/*.yaml`, `config/forms/templates/`.

## Данные

Рабочий каталог по умолчанию: `data/list_office/`. Его можно заменить через
`LES_LIST_OFFICE_DIR`.

```text
data/list_office/
└── documents/<document_id>/revisions/<revision_id>/
    ├── <form_id>_r<revision_no>.docx|xlsx
    └── manifest.json
```

`manifest.json` имеет schema `list.office_artifact.v1` и хранит logical document,
revision, state=`draft`, форму, поля и их deterministic source, незаполненные поля,
датасет, выбранные файлы-основания, размер и SHA-256 артефакта. Для агентного
черновика manifest дополнительно хранит проверенный `office_document_ir_v1`,
`agent_assisted=true` и `review_confirmed=true`.

Ревизия append-only: повторный выпуск создаёт новый каталог. Скачивание fail-closed:
если файл отсутствует или его SHA-256 не совпадает с manifest, API не отдаёт его.

## Поток

1. GUI получает список датасетов; пользователь выбирает датасет, том/папку и точные
   файлы-основания, после чего Студия получает реестр `config/forms` и список объектов.
2. Поля разрешаются действующим Forms-движком: `project.*`, `field.*`, `edges.*`,
   `date.today`, `manual` — без LLM.
3. Пользователь видит источник и пустое состояние каждого поля.
4. `POST /api/forms/agent-draft` читает bounded exact/FTS-фрагменты только выбранных
   документов, делает field-specific поиск (в том числе имени и адреса объекта) и вызывает
   штатный schema-constrained provider LES.
5. Модель возвращает предложения для всех фактически незаполненных полей:
   `grounded|assumption|missing`, confidence,
   evidence ids и комментарий. Код принимает лишь известные ключи и серверные evidence ids;
   неподтверждённый `grounded` становится видимым assumption/missing.
6. GUI показывает предложения и фрагменты-основания. «Применить к полям» не создаёт файл.
7. После применения оператор обязан отметить ручную проверку. До этого «Создать черновик»
   disabled, а API также отклоняет агентный IR без `review_confirmed`.
8. Предпросмотр не создаёт ревизию. Отдельное подтверждённое действие формирует
   DOCX/XLSX и manifest; журнал показывает формат, ревизию, пропуски, SHA и скачивание.

## Границы model-first

Л.Е.С. предлагает содержание, но не редактирует OOXML и не вызывает рендерер. Л.И.С.Т.
детерминированно проверяет typed IR, сохраняет provenance и выпускает новый файл только
после отдельного пользовательского подтверждения. Транспортная/JSON-ошибка модели видна
как ошибка; готовый предметный fallback кодом не подставляется. Оригиналы не открываются
на запись.

## Тесты

- `tests/test_list_office_service.py` — append-only ревизии, неизменность источника,
  missing fields, provenance, SHA fail-closed и path guard;
- `tests/test_list_office_agent_service.py` — exact selected docs, schema/evidence gate,
  извлечение имени/адреса из выбранного проектного листа при пустой карточке объекта,
  model failure, assumption downgrade, review gate и сохранение IR в manifest;
- `tests/test_forms_service_w113.py`, `tests/test_forms_templates.py` — резолв и DOCX/XLSX;
- `tests/test_static_assets.py` — GUI-проводка Студии;
- браузерный smoke — выбрать другой шаблон, подготовить поля с Л.Е.С., раскрыть evidence,
  применить предложения, подтвердить проверку, создать ревизию и увидеть скачивание.

## Не входит в текущий срез

- workflow `reviewed/approved/issued` и ЭП;
- модельное редактирование уже заполненных пользователем полей и совместный редактор;
- PDF-экспорт и редактирование произвольного PDF;
- совместное редактирование и полноценная ERP.
