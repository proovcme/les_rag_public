# Встроенный просмотр источников Л.И.С.Т.

Статус: **✅ актуально для `list.file_viewer.v1` и `list.pdf_viewer.v1`**.

## Назначение

Клик по файловому источнику в ответе открывает его внутри панели артефактов
Совушки. Просмотрщик работает локально, одинаково в браузере и Tauri/WebView2,
не использует CDN, не вызывает модель и никогда не открывает оригинал на запись.
Кнопка «Оригинал» остаётся отдельным явным действием.

Поддерживаются:

- PDF — страница, масштаб, навигация и подсветка переданного bbox;
- DOCX — абзацы, заголовки и таблицы, переход к `#paraN`;
- XLSX/XLSM — листы, строки, значения и формулы, переход к `#Лист!RN`;
- PPTX — порядок слайдов и извлекаемый текст без имитации полной геометрии;
- EML — заголовки и безопасное plain-text тело;
- CSV/TSV, текстовые форматы и изображения.

Legacy `.doc`/`.xls` не выдаются за современные OOXML: для них доступен только
оригинал до появления отдельного совместимого парсера.

## Точки входа

- `proxy/services/file_viewer_service.py` — escaped HTML для Office/текста/почты;
- `proxy/services/pdf_viewer_service.py` — локальная PDF-оболочка;
- `proxy/services/pdf_contour_service.py::render_page_preview` — PNG и bbox highlight;
- `GET /api/rag/file/viewer` — единая точка входа GUI;
- `GET /api/rag/file/pdf-info`, `/pdf-preview`, `/pdf-viewer` — PDF primitives;
- `sovushka/answer_render.py::citation_drawer_item` — locator/page/bbox deep-link;
- `sovushka/pages/chat.py::_show_source_drawer` — embedded iframe в артефакте.

Все маршруты проходят тот же `path-guard`, что `/api/rag/file/raw`: разрешены
только `RAG_Content` и явно заданные `LES_EXTERNAL_SOURCE_ROOTS`. Абсолютный путь
не попадает в HTML. Ответы просмотра имеют `Cache-Control: private, no-store`.

## Ограничения и честность представления

Это контрольный read-only preview, а не редактор и не пиксельно точная замена
Word/Excel/PowerPoint. DOCX/PPTX показывают структуру и текст; XLSX ограничивает
одно окно 500 строками и 80 колонками; текст — 600 000 символами. Для больших
файлов GUI сообщает об ограничении и сохраняет ссылку на оригинал.

PDF рендерится PyMuPDF на сервере. Поэтому он стабилен без браузерного PDF-плагина,
но текущий растр не даёт выделять текст мышью. Координатная подсветка появляется,
только если evidence payload действительно содержит `bbox`/`bbox_pt`.

## Проверки

- `tests/test_files_router_w181.py` — guard, PDF info/PNG и unified Office route;
- `tests/test_file_viewer_service.py` — escaping, PPTX, EML и форматы;
- `tests/test_answer_render_v16.py` — page/locator/bbox deep-links;
- `tests/test_static_assets.py` — iframe и GUI wiring;
- browser smoke — PDF page 2→3, DOCX `para3`, XLSX `ВОР!R10` и лист `Итоги`,
  ноль console errors.
