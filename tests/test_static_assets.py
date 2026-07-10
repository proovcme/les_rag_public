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
    assert "Л.И.С.Т.: карта проекта, файлы и вопросы по источникам" in page
    assert "Реестр файлов" in page
    assert "Тип датасета" in page
    assert "profile/kind" in page
    assert "Заметка к проекту" in page
    assert "Л.И.С.Т. проекта" in page
    assert "Структура Л.И.С.Т." in page
    assert 'coverage.get("files_ok") or coverage.get("files_extracted")' in page
    assert 'state.__setitem__("dataset_filter", str(e.args or "")), _render_datasets()' in page
    assert "warnings_truncated" in page
    assert "ui.mermaid(diagram)" in page
    assert "profile/guidance" in page
    assert "Темы датасета" in page
    assert "Разделы внутри файлов" in page
    assert "Спросить по теме" in page
    assert 'ui.button("CAD"' in page
    assert "/api/cad-bim/imports?limit=300" in page
    assert "Слабые импорты" in page
    assert "Диагностика чтения" not in page
    assert "Дубли импортов" in page
    assert "_ask_about_cad_import" in page
    assert 'f"ds:{dataset_id}"' in page
    assert "topic_map" in page and "section_map" in page
    assert 'ui.button("Карта"' in page
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

    assert "tab_documents=None" in chat
    assert 'aria-label="Документы"' in chat
    assert "Открыть документы датасетов" in chat


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
