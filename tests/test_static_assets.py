from pathlib import Path


def test_static_fonts_are_not_html_downloads():
    fonts_dir = Path("static/fonts")
    if not fonts_dir.exists():
        return

    for font_path in fonts_dir.glob("*"):
        if font_path.suffix.lower() not in {".ttf", ".otf", ".woff", ".woff2"}:
            continue
        prefix = font_path.read_bytes()[:256].lstrip().lower()
        assert not prefix.startswith(b"<!doctype html")
        assert not prefix.startswith(b"<html")


def test_admin_instruments_tab_is_mounted():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    app_shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    assert 'ui.tab("Инструменты"' in header
    assert "from sovushka.pages.instrumenty import build_instrumenty" in app_shell
    assert "build_instrumenty()" in app_shell


def test_admin_documents_tab_is_mounted():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    app_shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    page = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    router = Path("proxy/routers/documents.py").read_text(encoding="utf-8")

    assert 'ui.tab("Документы"' in header
    assert "include_documents" in header
    assert "from sovushka.pages.documents import build_documents" in app_shell
    assert "build_documents()" in app_shell
    assert "include_documents=True" in app_shell
    assert "tab_documents" in app_shell
    assert "Датасеты, файлы, карта проекта и Студия" in page


def test_documents_ui_is_a_visual_read_only_dataset_browser():
    page = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")
    router = Path("proxy/routers/documents.py").read_text(encoding="utf-8")
    app_shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    for class_name in (
        "sov-docs-shell",
        "sov-docs-topbar",
        "sov-docs-search",
        "sov-docs-workspace",
        "sov-dataset-card",
        "sov-document-card",
        "sov-docs-view-tabs",
    ):
        assert class_name in page
        assert f".{class_name}" in styles

    assert 'return name or "Без названия"' in page
    assert 'f"{name} · {did}"' not in page
    assert page.count("_render_dataset_kind_control()") == 1  # definition only, not the main surface
    assert 'on_click=lambda: _schedule(_run_pdf_extract())' not in page
    assert "min-height: 40px" in styles
    assert "scale: .96" in styles
    assert "Реестр датасета" in page
    assert '"Файлы и папки"' in page
    assert "_composition_files" in page
    assert 'ui.expansion("Реестр датасета", icon="o_inventory_2", value=False)' in page
    assert "sov-composition-folder" in page
    assert ".sov-composition-folder" in styles
    assert "Корень датасета" in page
    assert "DATASET_GROUP_OPTIONS" in page
    assert "_dataset_group" in page
    assert "sov-dataset-group-filter" in page
    assert "sov-composition-view-switch" in page
    for label in (
        "Дерево", "Плитка", "Список", "Таблица", "О датасете", "Выбранный файл",
        "Все папки", "Все форматы", "Все статусы", "Тип документа", "Qdrant/LES",
    ):
        assert label in page
    assert "sov-composition-table" in page
    assert "sov-composition-filters" in page
    assert "_inspect_composition_file" in page
    assert "_load_dataset_index_brief" in page
    assert "_indexed_dataset_brief" in page
    assert "def _plain_index_text" in page
    assert ".sov-composition-table" in styles
    assert ".sov-index-brief--dataset" in styles
    assert ".sov-index-brief--file" in styles
    assert "grid-template-columns: minmax(0, 1fr)" in styles
    assert "sov-doc-tree-folder" in page
    assert ".sov-doc-tree-folder" in styles
    tree_folder_css = styles.split(".sov-doc-tree-folder {", 1)[1].split("}", 1)[0]
    assert "flex: 0 0 auto" in tree_folder_css
    assert ".sov-selected-file-dock" in styles
    assert "--docs-border-strong" in styles
    assert "--docs-muted-strong" in styles
    assert "border: 1px solid var(--docs-border-strong)" in styles
    assert "Л.И.С.Т. проекта" not in page
    assert "Карта проекта" in page
    assert "Папки и разделы можно открыть" in page
    assert "Данные о датасете" in page
    assert '"map_target": "dataset"' in page
    assert 'state["map_target"] = "file"' in page
    assert "Открыть оригинал" in page
    assert "sov-file-content-preview" in page
    assert ".sov-project-map" in styles
    assert ".sov-project-map-node:hover" in styles
    assert "def _list_warning_messages" in page
    assert '"Проверить: " + "; ".join(warnings[:3])' not in page
    assert "таблицы не выделены автоматически" in page
    assert "sampled_documents') or 0)} файла" not in page
    assert 'coverage.get("files_ok") or coverage.get("files_extracted")' in page
    assert 'state.__setitem__("dataset_filter", str(e.args or "")), _render_datasets()' in page
    assert "warnings_truncated" in page
    assert "ui.mermaid(" not in page
    assert "Что попало в RAG" in page
    assert "sov-index-quality" in page
    assert ".sov-index-quality" in styles
    assert "sov-file-panel-filters" in page
    assert ".sov-file-panel-filters" in styles
    for filter_label in ("Папка", "Формат", "Статус", "Тип"):
        assert f'label="{filter_label}"' in page
    assert "Темы датасета" in page
    assert "Разделы внутри файлов" in page
    assert "Спросить по теме" in page
    assert "/api/rag/readiness" in page
    assert "Готовность поиска" in page
    assert "RRF не готов" in page
    assert "Механическая база готова" in page
    assert "Карточки норм не построены (необязательно)" in page
    assert "Это проверка retrieval, а не подтверждение применимости норм" in page
    assert 'ui.button("CAD/BIM"' in page
    assert "/api/cad-bim/imports?limit=300" in page
    assert "Слабые импорты" in page
    assert "Диагностика чтения" not in page
    assert "Дубли импортов" in page
    assert "_ask_about_cad_import" in page
    assert 'f"ds:{dataset_id}"' in page
    assert "topic_map" in page and "section_map" in page
    assert 'ui.button("Л.И.С.Т."' in page
    assert 'ui.button("Студия"' in page
    assert "Л.И.С.Т. · Студия документов" in page
    assert "Подготовить с Л.Е.С." in page
    assert "/api/forms/agent-draft" in page
    assert "Я проверил содержание, предположения и источники" in page
    assert "form_select.on_value_change" in page
    assert "project_select.on_value_change" in page
    assert "format_select.on_value_change" in page
    assert "/api/forms/artifacts" in page
    assert "Создать черновик" in page
    assert "неизменяемыми ревизиями" in page
    assert "def _office_notify" in page
    assert 'with panel:' in page
    assert "Паспорт PDF" in page
    assert "/pdf-contour?max_pages=80" in page
    assert "_load_pdf_contour_preview" in page
    assert "Координатные фрагменты" in page
    assert "sov-pdf-contour" in page
    assert ".sov-pdf-contour" in styles
    assert ".sov-pdf-page-grid" in styles
    assert "do not call LLMs" in router
    assert "request.query_params.get(\"question\")" in app_shell
    assert "request.query_params.get(\"tab\")" in app_shell
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    assert "target_file" in chat
    assert 'request.query_params.get("target_file")' in chat


def test_samovar_exposes_cloud_drive_intake():
    page = Path("sovushka/pages/samovar.py").read_text(encoding="utf-8")
    router = Path("proxy/routers/datasets.py").read_text(encoding="utf-8")

    assert "Google / Яндекс через веб" in page
    assert "/api/rag/cloud-drives/sync" in page
    assert "Web-диски:" in page
    assert 'router.post("/cloud-drives/sync")' in router
    assert 'router.post("/cloud-drives/list")' in router


def test_chat_exposes_documents_navigation():
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "tab_documents=None" in chat
    assert 'aria-label="Документы"' in chat
    assert "Открыть документы датасетов" in chat
    assert 'f"Источники · {len(srcs)}"' in chat
    assert 'value=False' in chat
    assert 'ui.link(lbl, str(item["open_url"]))' in chat
    assert 'if item.get("viewer_url")' in chat
    assert "sov-embedded-file-viewer" in chat
    assert "/rag/file/viewer" in Path("sovushka/answer_render.py").read_text(encoding="utf-8")
    assert '"target=_blank"' in chat
    assert "sov-source-detail" in chat
    assert ".sov-source-expansion" in styles
    assert ".sov-embedded-file-viewer iframe" in styles
    assert "max-height: min(42vh, 360px)" in styles
    assert "transition: all" not in styles


def test_deploy_allows_sovushka_shell():
    from tools import deploy_to_runtime as deploy

    assert deploy._allowed("sovushka_ng.py")
    assert deploy._allowed("sovushka/pages/documents.py")
    assert any(prefix == "sovushka_ng.py" and service == "com.les.sovushka"
               for prefix, service in deploy.SERVICE_BY_PREFIX)


def test_qdrant_visualizer_is_mounted_as_static_same_origin():
    app_shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert 'app.add_static_files("/qdrant-visualizer"' in app_shell
    assert 'RedirectResponse("/qdrant-visualizer/index.html")' in app_shell
