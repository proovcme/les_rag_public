import inspect
from pathlib import Path


def test_model_connections_page_uses_safe_registry_actions():
    from sovushka.pages.model_connections import build_model_connections

    source = inspect.getsource(build_model_connections)
    for label in (
        "Подключения моделей",
        "Проверить",
        "Назначить",
        "Изменить",
        "Копировать",
        "Заменить ключ",
        "Отключить",
    ):
        assert label in source
    assert 'type="password"' in source
    assert "api_key" not in source
    assert "secret_ref" not in source
    assert "/api/model-connections" in source
    assert "panel(" in source
    assert "status_badge(" in source
    assert 'classes("sov-model-connections-page")' in source


def test_model_page_explains_locality_context_source_and_restart():
    source = Path("sovushka/pages/model_connections.py").read_text(encoding="utf-8")
    for label in (
        "На этом компьютере",
        "В доверенной сети",
        "Удалённое HTTPS-подключение",
        "Запрошено",
        "Действует",
        "Источник",
        "Перезапуск не требуется",
        "Состояние проверки",
    ):
        assert label in source
    assert "confirm(" in source
    assert "BOUND_CONNECTION" in source


def test_configuration_navigation_has_model_connections_tab():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert 'ui.tab("Модели"' in header
    assert 'tab_refs["model_connections"]' in header
    assert "build_model_connections" in shell
    assert '"Модели": tab_model_connections' in shell


def test_legacy_settings_points_to_registry_instead_of_provider_fields():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")

    assert "Конфигурация → Модели" in header
    assert 'ui.navigate.to("/les/classic?tab=models")' in header
    assert "on_click=lambda: settings_dialog.open()" not in header
