from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_exposes_platform_native_manual_update_flow_with_status():
    source = (ROOT / "sovushka" / "components" / "header.py").read_text(encoding="utf-8")
    section = source[source.index('ui.label("Обновление ЛЕС")') : source.index('ui.label("⚠ Опасная зона")')]
    assert '"Проверить обновление"' in section
    assert '"Установить"' in section
    assert '"/api/update/patch/check" if is_windows' in section
    assert '"/api/update/patch/install" if is_windows' in section
    assert '"/api/update/patch/status" if is_windows' in section
    assert '"/api/update/mac/check"' in section
    assert '"/api/update/mac/install"' in section
    assert '"/api/update/mac/status"' in section
    assert '"/api/update/check"' in section
    assert '"/api/update/install"' in section
    assert '"/api/update/status"' in section
    assert '"Переустановить выпуск"' in section
    assert "заменяет всё дерево программы" in section
    assert "api_get(update_check_path)" in section
    assert "api_post(update_install_path, {})" in section
    assert "api_get(update_status_path)" in section
    assert "Тесты и сборка по кнопке не запускаются" in section
    assert "предыдущая версия восстановлена" in section
    assert "ui.timer" not in section


def test_header_exposes_lightweight_application_update_separately_from_data_refresh():
    source = (ROOT / "sovushka" / "components" / "header.py").read_text(encoding="utf-8")

    assert '"Обновить ЛЕС"' in source
    assert "on_click=settings_dialog.open" in source
    assert '"Обновить данные"' in source


def test_header_checks_patch_feed_at_startup_and_daily():
    source = Path("sovushka/components/header.py").read_text(encoding="utf-8")

    assert "async def _check_update_in_background" in source
    assert "await api_get(update_check_path)" in source
    assert 'update_entry_button.set_text("Доступно обновление")' in source
    assert "ui.timer(5.0, _check_update_in_background, once=True)" in source
    assert "ui.timer(86400.0, _check_update_in_background)" in source


def test_windows_settings_hide_mlx_controls_and_default_to_ollama():
    source = (ROOT / "sovushka" / "components" / "header.py").read_text(encoding="utf-8")
    assert 'is_windows = sys.platform.startswith("win")' in source
    assert "mlx_settings.set_visibility(not is_windows)" in source
    assert 'value="ollama" if is_windows else "mlx"' in source
    assert "всегда локально на MLX" not in source
