from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_memory_panel_uses_shared_uikit_and_explicit_api():
    source = (ROOT / "sovushka" / "pages" / "diag.py").read_text(encoding="utf-8")
    assert '"Память проектов"' in source
    assert "select_field(" in source
    assert "status_badge(" in source
    assert "action_button(" in source
    assert 'api_put("/api/memory/config"' in source
    assert "route_reuse" in source


def test_memory_panel_does_not_restart_runtime_directly():
    source = (ROOT / "sovushka" / "pages" / "diag.py").read_text(encoding="utf-8")
    memory_section = source[source.index('"Память проектов"'):]
    assert 'api_post("/api/runtime/restart' not in memory_section
