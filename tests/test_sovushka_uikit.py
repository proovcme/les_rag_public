from pathlib import Path

import pytest

from sovushka.styles import _DARK_THEME, _LIGHT_THEME
from sovushka.uikit.components import BUTTON_VARIANTS, PANEL_VARIANTS
from sovushka.uikit.states import feedback_state
from sovushka.uikit.tokens import UIKIT_CSS


@pytest.mark.parametrize("kind", ["loading", "empty", "error", "blocked"])
def test_feedback_states_have_human_copy(kind: str):
    state = feedback_state(kind, error_code="rag_test")

    assert state["kind"] == kind
    assert state["title"]
    assert state["detail"]
    assert state["error_code"] == "rag_test"


def test_feedback_state_rejects_unknown_kind():
    with pytest.raises(ValueError, match="Unknown feedback state"):
        feedback_state("mystery")


def test_uikit_has_accessible_motion_and_control_contract():
    assert "--sov-ui-hit: 40px" in UIKIT_CSS
    assert ":focus-visible" in UIKIT_CSS
    assert "outline: 2px solid var(--accent) !important" in UIKIT_CSS
    assert "prefers-reduced-motion: reduce" in UIKIT_CSS
    assert "transition: all" not in UIKIT_CSS
    assert "scale(.96)" in UIKIT_CSS
    assert "font-variant-numeric: tabular-nums" in UIKIT_CSS
    assert "text-wrap: balance" in UIKIT_CSS
    assert "text-wrap: pretty" in UIKIT_CSS
    assert "grid-template-columns: 160px minmax(0, 1fr)" in UIKIT_CSS
    assert "@media (max-width: 900px)" in UIKIT_CSS
    assert "--sov-ui-font-size-body: 14px" in UIKIT_CSS
    assert "--sov-ui-font-size-control: 13px" in UIKIT_CSS
    assert "font-synthesis: none" in UIKIT_CSS
    assert ".sov-nav-switch--active .q-btn__content" in UIKIT_CSS
    assert ".sov-ui-shell .sov-chat-title" in UIKIT_CSS
    assert "color: var(--accent)" in UIKIT_CSS
    assert "justify-content: flex-start !important" in UIKIT_CSS
    assert ".sov-runtime-state" in UIKIT_CSS
    assert ".sov-ui-header-account" in UIKIT_CSS
    assert ".sov-mobile-sections-button" in UIKIT_CSS
    assert ".sov-mobile-sections-menu" in UIKIT_CSS
    assert ".sov-app-content .nicegui-tab-panel" in UIKIT_CSS
    assert "--sov-ui-icon-column: 20px" in UIKIT_CSS
    assert "--sov-ui-icon-gap: 8px" in UIKIT_CSS
    assert ".sov-ui-button--primary" in UIKIT_CSS
    assert ".sov-ui-button--danger" in UIKIT_CSS
    assert ".sov-ui-panel--inset" in UIKIT_CSS


def test_component_registry_stays_small_and_explicit():
    assert BUTTON_VARIANTS == {"primary", "secondary", "quiet", "danger"}
    assert PANEL_VARIANTS == {"plain", "raised", "inset"}

    components = Path("sovushka/uikit/components.py").read_text(encoding="utf-8")
    for primitive in (
        "action_button",
        "text_field",
        "panel",
        "section_heading",
        "status_badge",
        "render_feedback_state",
        "acronym_identity",
    ):
        assert f"def {primitive}(" in components


def test_navigation_has_one_icon_column_and_equal_primary_rows():
    assert ".sov-nav-switch--config .q-btn__content" not in UIKIT_CSS
    assert "height: 36px !important" in UIKIT_CSS
    assert "padding: 0 7px !important" in UIKIT_CSS
    assert "padding: 0 8px !important" in UIKIT_CSS
    assert "gap: var(--sov-ui-icon-gap)" in UIKIT_CSS
    assert "flex: 0 0 var(--sov-ui-icon-column)" in UIKIT_CSS

    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    assert 'with ui.row().classes("sov-primary-nav")' in header
    assert header.count("_primary_button(") == 4


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(hex_color: str) -> float:
        channels = [
            int(hex_color[index:index + 2], 16) / 255
            for index in (1, 3, 5)
        ]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted(
        (luminance(foreground), luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", [_LIGHT_THEME, _DARK_THEME])
def test_theme_text_contrast_meets_wcag_aa(theme):
    surface = theme["--bg-panel"]
    assert _contrast_ratio(theme["--text"], surface) >= 4.5
    assert _contrast_ratio(theme["--dim"], surface) >= 4.5
    assert _contrast_ratio(theme["--warn"], surface) >= 4.5
    assert _contrast_ratio(theme["--err"], surface) >= 4.5


def test_primary_green_action_contrast_meets_wcag_aa():
    assert _contrast_ratio("#ffffff", _LIGHT_THEME["--accent"]) >= 4.5


def test_critical_surfaces_use_uikit_and_blocked_state():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")

    assert "ui.add_head_html(UIKIT_CSS)" in shell
    assert shell.count("sov-ui-shell") >= 2
    assert shell.count("sov-app-shell") == 2
    assert shell.count("sov-app-content") == 2
    assert "sov-ui-header" in header
    assert "sov-ui-documents" in documents
    assert "sov-ui-evidence-card" in chat
    assert '<span class="sov-chat-title sov-acronym-title">С.О.В.У.Ш.К.А.</span>' in chat
    assert "С.О.В.У.Ш.К.А. · Чат" not in chat
    assert "Умная, Шаблонизированная, " in chat
    assert "Классифицированная, Автоматизированная" in chat
    assert 'class="sov-owl-mark"' in chat
    assert 'aria-label="С.О.В.У.Ш.К.А. — Система Обработки и Выдачи: ' in chat
    assert 'aria-label="Выбрать область"' not in chat
    assert "sov-attach-btn" in chat
    assert 'render_feedback_state(' in chat
    assert '"blocker": blocker' in chat
    assert "action_button(" in chat
    assert "text_field(" in documents


def test_project_ui_skill_is_complete_and_points_to_canonical_contract():
    skill = Path("skills/sovushka-ui/SKILL.md").read_text(encoding="utf-8")
    reference = Path(
        "skills/sovushka-ui/references/review-checklist.md"
    ).read_text(encoding="utf-8")
    module_doc = Path("docs/modules/sovushka-uikit.md").read_text(encoding="utf-8")

    assert "TODO" not in skill
    assert "docs/modules/sovushka-uikit.md" in skill
    assert "icon-to-label gap at 8 px" in skill
    assert "No page-level horizontal overflow at 390 px" in reference
    assert "## Реестр компонентов" in module_doc


def test_acronym_identity_is_shared_and_user_can_hide_expansions():
    components = Path("sovushka/uikit/components.py").read_text(encoding="utf-8")
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert "def acronym_identity(" in components
    assert "sov-acronym-title" in components
    assert "sov-acronym-expansion" in components
    assert "Показывать расшифровки акронимов" in header
    assert 'app.storage.user["show_acronym_expansions"]' in header
    assert "sov-hide-acronym-expansions" in shell
    assert ".sov-hide-acronym-expansions .sov-acronym-expansion" in UIKIT_CSS

    for page in ("diag.py", "volk.py", "prorab.py", "overview.py", "samovar.py", "mail.py", "documents.py"):
        source = Path("sovushka/pages", page).read_text(encoding="utf-8")
        assert "acronym_identity(" in source


def test_documents_surface_contract_is_keyword_only_and_complete():
    page = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert 'def build_documents(*, surface: str = "documents")' in page
    for surface in ("documents", "studio", "cad_bim"):
        assert f'build_documents(surface="{surface}")' in shell


def test_critical_navigation_and_stage_three_to_five_controls_are_visible():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    mail = Path("sovushka/pages/mail.py").read_text(encoding="utf-8")

    for key, label, icon in (
        ("chat", "Чат", "o_forum"),
        ("studio", "Студия", "o_edit_note"),
        ("config", "Конфигурация", "o_tune"),
    ):
        assert f'"{key}",' in header
        assert f'"{label}",' in header
        assert f'"{icon}",' in header
    assert "sov-primary-nav" in header
    assert "Рабочие разделы" in header
    assert "sov-runtime-state" in header
    assert "ЛЕС на связи" in header
    assert 'ui.button("Обновить", icon="o_refresh"' in header
    assert '"Тема",' in header
    assert 'ui.label("Qdrant")' in header
    assert '"Профиль",' in header
    assert "Сеанс: {account_detail}" in header
    assert 'ui.button("Разделы", icon="o_apps")' in header
    assert "ui.menu_item(" in header
    assert 'tab_refs[key].tooltip(label)' in header
    assert 'f"sov-nav-switch sov-nav-switch--{key}"' in header
    assert "sov-nav-switch--active" in header
    assert "/classic?tab=studio" in header
    assert 'active_primary="config"' in Path("sovushka_ng.py").read_text(encoding="utf-8")
    assert "sov-docs-sticky-ask" in documents
    assert '"Спросить в чате"' in documents
    assert '"Забрать ещё"' in mail
    assert "sov-mail-status-strip" in mail
    assert '"target_file"' in mail


def test_configuration_home_uses_uikit_and_progressive_disclosure():
    diag = Path("sovushka/pages/diag.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert 'classes("sov-config-page")' in diag
    assert 'variant="primary"' in diag
    assert '"Проверить систему"' in diag
    assert '"Рабочие контуры"' in diag
    for disclosure in (
        "Детали последней проверки",
        "С.У.Х.А.Р.И.К. · Резервные копии",
        "Словарь системных сокращений",
        "Технический журнал",
    ):
        assert disclosure in diag

    assert "rgba(59,130,246" not in diag
    assert "ЗАПУСТИТЬ ПРОВЕРКУ" not in diag
    assert "kpi-box" not in diag
    assert "diag-live-map" not in diag
    assert "build_log_terminal()" not in shell
    assert ".sov-config-status-strip" in UIKIT_CSS
    assert ".sov-config-contours" in UIKIT_CSS
    assert ".sov-config-disclosure" in UIKIT_CSS


def test_dataset_registry_uses_uikit_and_keeps_operator_controls_secondary():
    source = Path("sovushka/pages/samovar.py").read_text(encoding="utf-8")
    active = source.split("def build_samovar_legacy()", maxsplit=1)[0]

    assert '.classes("w-full sov-datasets-page")' in active
    assert '"Добавить датасет"' in active
    assert '"Сводка корпуса"' in active
    assert '"Найти датасет по названию"' in active
    assert '"Открыть файлы"' in active
    assert '"Управление индексатором"' in active
    assert '"Тонкая настройка партий и памяти"' in active
    assert "render_feedback_state(" in active
    assert "action_button(" in active
    assert "text_field(" in active
    assert '"mode": "table"' not in active
    assert 'ui.button("Добавить"' not in active

    for contract in (
        ".sov-dataset-summary",
        ".sov-dataset-registry",
        ".sov-dataset-row",
        ".sov-dataset-toolbar",
        ".sov-dataset-disclosure",
    ):
        assert contract in UIKIT_CSS


def test_mail_surfaces_use_uikit_and_keep_host_names_out_of_product_copy():
    mail = Path("sovushka/pages/mail.py").read_text(encoding="utf-8")

    assert "sov-mail-page" in mail
    assert "sov-mail-workbench" in mail
    assert "sov-mail-settings-hero" in mail
    assert '"Спросить в чате"' in mail
    assert "action_button(" in mail
    assert "text_field(" in mail
    assert "render_feedback_state(" in mail
    assert "Legion" not in mail
    assert "легион" not in mail.casefold()
    assert 'placeholder="Поиск по теме, отправителю или получателю"' in mail
    assert 'aria_label="Поиск по теме и участникам"' in mail
    assert '\n                label="Поиск по теме и участникам"' not in mail

    for contract in (
        ".sov-mail-workbench",
        ".sov-mail-account--active",
        ".sov-mail-message",
        ".sov-mail-settings-section",
    ):
        assert contract in UIKIT_CSS


def test_tools_surface_separates_sources_from_connected_prompt_editor():
    tools = Path("sovushka/pages/instrumenty.py").read_text(encoding="utf-8")

    assert "sov-tools-page" in tools
    assert '"Источники данных"' in tools
    assert '"Системные промпты"' in tools
    assert '"Подключён"' in tools
    assert "лишних: {extra}" in tools
    assert "_render_prompt_block" not in tools
    assert "action_button(" in tools
    assert "panel(" in tools

    for contract in (
        ".sov-tools-hero",
        ".sov-tools-source",
        ".sov-tools-prompt",
        ".sov-tools-layer",
    ):
        assert contract in UIKIT_CSS
