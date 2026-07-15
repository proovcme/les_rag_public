from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_exposes_manual_vps_patch_flow_with_status():
    source = (ROOT / "sovushka" / "components" / "header.py").read_text(encoding="utf-8")
    section = source[source.index('ui.label("Быстрое обновление ЛЕС")') : source.index('ui.label("⚠ Опасная зона")')]
    assert '"Проверить патч"' in section
    assert '"Установить"' in section
    assert 'api_get("/api/update/patch/check")' in section
    assert 'api_post("/api/update/patch/install", {})' in section
    assert 'api_get("/api/update/patch/status")' in section
    assert "Проверка выполняется только по нажатию." in section
    assert "предыдущая версия восстановлена" in section
    assert "ui.timer" not in section
