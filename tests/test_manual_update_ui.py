from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_exposes_only_manual_update_actions():
    source = (ROOT / "sovushka" / "components" / "header.py").read_text(encoding="utf-8")
    assert '"Проверить обновление"' in source
    assert '"Обновить"' in source
    assert 'api_get("/api/update/check")' in source
    assert 'api_post("/api/update/install", {})' in source
    assert "Проверка выполняется только по нажатию кнопки." in source
    assert "ui.timer" not in source[source.index('ui.label("Обновление ЛЕС")') : source.index('ui.label("⚠ Опасная зона")')]
