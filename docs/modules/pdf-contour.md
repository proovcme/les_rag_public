# PDF-контур Л.И.С.Т. и RAG

Статус: **✅ актуально для page-passport v1**.

## Назначение

PDF-контур даёт один общий постраничный контракт для индексации RAG и интерфейса
Л.И.С.Т. Каждая проверенная страница получает тип, качество текстового слоя,
признак необходимости OCR, геометрию, таблицы/графику, штамп и координаты
репрезентативных фрагментов. Это маршрутизация и evidence, а не инженерный вывод.

Исходный PDF открывается только на чтение. Паспорт и PNG-превью не записываются
рядом с оригиналом и не меняют его байты.

## Точки входа

- единый сервис: `proxy/services/pdf_contour_service.py`;
- RAG ingestion: `backend/qdrant_adapter.py` → `_sync_pdf_page_text_nodes`;
- API: `GET /api/documents/by-id/{doc_id}/pdf-contour`;
- evidence preview: `GET /api/documents/by-id/{doc_id}/pdf-contour/pages/{page}/preview`;
- встроенный источник чата: `GET /api/rag/file/viewer?path=...&page=N&bbox=...`;
- GUI: `sovushka/pages/documents.py` → выбранный PDF → «Паспорт PDF»;
- стили: `sovushka/styles.py`.

## Контракт страницы

Schema `list.pdf_page_passport.v1` различает:

```text
digital_text
table
drawing
scan
mixed
damaged_text_layer
```

Карточка содержит `source_ref=file.pdf#page=N`, `routing_confidence`,
`requires_ocr`, `recognition_quality`, формат/ориентацию, число текстовых блоков,
изображений, графических объектов и таблиц, статус штампа, номер листа best-effort,
warnings и до пяти `evidence_fragments` с bbox.

`list.pdf_contour.v1` агрегирует страницы одного файла и честно помечает `partial`,
если GUI-лимит меньше реального числа страниц. API не возвращает абсолютный путь
к локальному оригиналу.

## Встройка в RAG

PDF page-level nodes остаются основным searchable baseline. При включённом
`RAG_PDF_PAGE_PASSPORT_ENABLED=true` payload `pdf_page_text` дополнительно хранит:

```text
pdf_page_type / pdf_page_type_label
pdf_routing_confidence
pdf_requires_ocr
pdf_recognition_quality
pdf_page_signals
pdf_stamp_status / pdf_sheet_number
pdf_fragment_bboxes
source_ref
```

OCR-маршрут больше не отключает page nodes. Splitter понимает оба заголовка
`## Page N` и `## Стр. N`; распознанный текст скана получает
`source_layer=pdf_ocr_text`, обычный текстовый слой — `pdf_text_layer`.
Сбой page-passport остаётся enrichment warning и не удаляет базовый searchable text.
Общий markdown-порог шума не применяется повторно к уже выделенной непустой PDF-странице:
короткий лист со штампом, маркой, номером помещения или обозначением оборудования остаётся
самостоятельным evidence-узлом с точным `page` и `source_ref`.

## GUI

При выборе PDF Л.И.С.Т. параллельно читает indexed fragments и паспорт. Пользователь
видит сводные числа, все проверенные страницы, тип/формат/OCR-флаг, confidence,
качество, выбранное PNG-превью и раскрываемые координатные фрагменты. Переключение
страниц не создаёт sidecar и не запускает reindex.
Для файлов ручной загрузки, где MetaDB не хранит абсолютный `source_path`, viewer и
паспорт безопасно разрешают оригинал по `dataset_id + file_name` только внутри
канонического `storage/datasets`; traversal и абсолютный fallback запрещены.

В чате тот же PDF открывается в локальном `list.pdf_viewer.v1`: страница из
`source_ref`, переданный evidence bbox, масштаб и навигация. Viewer использует
`render_page_preview`, не браузерный plugin/CDN, и хранит оригинал read-only.
Универсальный контракт источников описан в [file-viewer.md](file-viewer.md).

## Тесты и проверка

- `tests/test_pdf_contour_service.py` — шесть типов/маршрутов, short-page regression,
  partial, bbox preview, неизменность SHA, RAG payload и API routes;
- `tests/test_qdrant_adapter_parse.py` — page-node contract;
- `tests/test_static_assets.py` — GUI wiring;
- визуальная проверка: synthetic пятистраничный PDF через Poppler и browser smoke
  `файл → Паспорт PDF → страница 1 → страница 2/Скан`.

## Не входит в текущий срез

- OCR всех страниц автоматически при простом открытии карточки;
- геометрическое понимание чертежа или DWG recovery;
- автоматическое инженерное решение по содержимому страницы;
- сохранение превью/паспорта как долговечного sidecar (может стать отдельным
  resumable enrichment после измерения производительности на реальном архиве).
