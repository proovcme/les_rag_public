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
    assert "from sovushka.pages.documents import build_documents" in app_shell
    assert "build_documents()" in app_shell
    assert "датасет → документ → фрагменты, без модели" in page
    assert "do not call LLMs" in router


def test_deploy_allows_sovushka_shell():
    from tools import deploy_to_runtime as deploy

    assert deploy._allowed("sovushka_ng.py")
    assert deploy._allowed("sovushka/pages/documents.py")
    assert any(prefix == "sovushka_ng.py" and service == "com.les.sovushka"
               for prefix, service in deploy.SERVICE_BY_PREFIX)
