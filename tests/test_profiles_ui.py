from __future__ import annotations

import inspect

from sovushka.pages import chat as chat_page
from sovushka.pages import profiles as profiles_page


def test_chat_exposes_four_canonical_profiles_with_agent_default():
    assert chat_page.visible_chat_modes() == (
        "search",
        "agent",
        "estimator",
        "engineer",
    )
    assert chat_page.default_chat_mode() == "agent"
    assert set(chat_page.CHAT_MODE_GUIDANCE) == {
        "search",
        "agent",
        "estimator",
        "engineer",
    }


def test_profiles_page_projects_registry_into_human_version_options():
    registry = {
        "profiles": [
            {
                "mode": "search",
                "label": "Поиск",
                "active_revision_id": "base",
                "revisions": [
                    {"revision_id": "base", "name": "Поиск · Base", "is_factory": True},
                    {"revision_id": "v2", "name": "Рабочая документация", "is_factory": False},
                ],
            }
        ]
    }

    options = profiles_page.profile_revision_options(registry, "search")

    assert options == {
        "base": "Поиск · Base · Base · Активная",
        "v2": "Рабочая документация",
    }


def test_profiles_page_uses_bundled_markdown_editor_and_explicit_actions():
    source = inspect.getsource(profiles_page.build_profiles)

    assert "ui.codemirror" in source
    assert "ui.markdown" in source
    for label in (
        "Выбрать промпт",
        "Выбрать скилл",
        "Сохранить версию",
        "Сделать активной",
        "Создать копию",
        "Создать с нуля",
        "Удалить редакцию",
        "Температура модели",
        "Только по источникам",
        "Удалить",
    ):
        assert label in source


def test_chat_can_apply_the_current_active_profile_on_the_next_message():
    source = inspect.getsource(chat_page.build_chat)

    assert "Применить активную версию" in source
    assert 'payload["apply_profile_revision"] = True' in source
