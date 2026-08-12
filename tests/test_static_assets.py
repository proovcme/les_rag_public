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


def test_work_surfaces_are_mounted_outside_configurator():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    app_shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    page = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")

    for label in ("Документы", "Студия", "CAD/BIM", "Почта"):
        assert f'ui.tab("{label}"' in header
    # Quasar outlined set has o_edit_note; o_edit_document is missing → empty Studio tab icon.
    assert 'ui.tab("Студия", icon="o_edit_note")' in header
    assert "o_edit_document" not in header
    for surface in ("documents", "studio", "cad_bim"):
        assert f'build_documents(surface="{surface}")' in app_shell
    assert 'def build_documents(*, surface: str = "documents")' in page
    assert "include_documents=True" in app_shell

    admin_shell = app_shell.split("async def classic_admin_page", 1)[1]
    assert "build_documents" not in admin_shell
    assert "build_mail()" not in admin_shell
    assert 'ui.tab("Настройка почты"' in header
    assert "build_mail_settings()" in admin_shell


def test_documents_ui_shows_only_rag_content_and_original():
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
        "sov-document-reader-summary",
        "sov-document-reader-fragment",
        "sov-document-reader-original",
    ):
        assert class_name in page
        assert f".{class_name}" in styles

    assert "Что есть в RAG" in page
    assert "Показать оригинал" in page
    assert "Извлечённого текста для этого файла нет." in page
    assert "Краткая справка" not in page
    assert "Пока пусто, зато честно" not in page
    assert "sov-docs-view-tabs" not in page
    assert "min-height: 40px" in styles
    assert "scale: .96" in styles
    assert "DATASET_GROUP_OPTIONS" in page
    assert "sov-dataset-group-filter" in page
    assert 'state.__setitem__("dataset_filter", str(e.args or "")), _render_datasets()' in page
    assert "ui.mermaid(" not in page
    assert "do not call LLMs" in router
    assert "request.query_params.get(\"question\")" in app_shell
    assert "request.query_params.get(\"tab\")" in app_shell
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    assert "target_file" in chat
    assert 'request.query_params.get("target_file")' in chat


def test_studio_uses_dataset_volume_and_explicit_source_files():
    page = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    service = Path("proxy/services/list_office_agent_service.py").read_text(encoding="utf-8")

    assert "Датасет → том → файлы-основания" in page
    assert "Тома и файлы-основания" in page
    assert '"selected_doc_ids": []' in page
    assert "Выбрать том" in page
    assert "_office_source_refs" in page
    assert "FIELD_QUERY_HINTS" in service
    assert '"object_name"' in service
    assert '"object_address"' in service


def test_mail_settings_are_configurator_only():
    app_shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    mail = Path("sovushka/pages/mail.py").read_text(encoding="utf-8")
    styles = Path("sovushka/styles.py").read_text(encoding="utf-8")

    assert "def build_mail_settings()" in mail
    assert "Настройка почтовой сборки" in mail
    assert "Classic Outlook на Legion" in mail
    assert "запускается только вручную" in mail
    assert "Забрать новые письма" in mail
    assert ".sov-mail-settings-page" in styles
    admin_shell = app_shell.split("async def classic_admin_page", 1)[1]
    assert "build_mail_settings()" in admin_shell
    assert "build_mail()" not in admin_shell
    work_mail = mail.split("def build_mail_settings()", 1)[0]
    assert "open_add_account_dialog" not in work_mail
    assert "Синхронизировать" not in work_mail


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
