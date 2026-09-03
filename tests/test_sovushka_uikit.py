from pathlib import Path
from types import SimpleNamespace

import pytest

from sovushka.styles import CUSTOM_CSS, _DARK_THEME, _LIGHT_THEME, theme_vars_css
from sovushka.uikit import components as components_module
from sovushka.uikit.components import BUTTON_VARIANTS, PANEL_VARIANTS, tab_name
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


def test_lazy_tab_panel_uses_same_name_for_element_and_event_value():
    tab = SimpleNamespace(_props={"name": "Студия"})

    assert tab_name(tab) == "Студия"
    assert tab_name("Студия") == "Студия"


def test_lazy_tab_panels_builds_initial_and_each_later_panel_once(monkeypatch):
    panel_options = {}

    class FakeTimer:
        def __init__(self):
            self.active = False

        def activate(self):
            self.active = True

        def deactivate(self):
            self.active = False

    class FakeElement:
        def __init__(self, name=""):
            self._props = {"name": name} if name else {}
            self.on_change = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def classes(self, *_args, **_kwargs):
            return self

        def style(self, *_args, **_kwargs):
            return self

        def props(self, *_args, **_kwargs):
            return self

        def clear(self):
            return None

        def on_value_change(self, callback):
            self.on_change = callback
            return self

    class FakeUi:
        def tab_panels(self, *_args, **kwargs):
            panel_options.update(kwargs)
            return FakeElement()

        def tab_panel(self, tab):
            return FakeElement(tab_name(tab))

        def element(self, *_args, **_kwargs):
            return FakeElement()

        def label(self, *_args, **_kwargs):
            return FakeElement()

    monkeypatch.setattr(components_module, "ui", FakeUi())
    chat = SimpleNamespace(_props={"name": "Чат"})
    studio = SimpleNamespace(_props={"name": "Студия"})
    built = []
    chat_timer = FakeTimer()
    studio_timer = FakeTimer()

    def build(name, timer):
        built.append(name)
        return {"timers": [timer]}

    container = components_module.lazy_tab_panels(
        FakeElement(),
        [
            (chat, lambda: build("Чат", chat_timer)),
            (studio, lambda: build("Студия", studio_timer)),
        ],
        initial=chat,
    )

    assert built == ["Чат"]
    assert panel_options["animated"] is False
    assert panel_options["keep_alive"] is True
    assert chat_timer.active is True
    assert studio_timer.active is False
    container.on_change(SimpleNamespace(value="Студия"))
    container.on_change(SimpleNamespace(value="Студия"))
    assert built == ["Чат", "Студия"]
    assert chat_timer.active is False
    assert studio_timer.active is True


def test_heavy_tab_builders_return_pauseable_timers():
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    samovar = Path("sovushka/pages/samovar.py").read_text(encoding="utf-8")

    assert 'return {"timers": [resource_gate_timer, model_chip_timer]}' in chat
    assert 'return {"timers": [timer for timer in (status_timer, refresh_timer) if timer is not None]}' in samovar


def test_classic_surfaces_use_shared_lazy_panels():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert shell.count("lazy_tab_panels(") == 2
    assert "with ui.tab_panels(" not in shell


def test_uikit_has_accessible_motion_and_control_contract():
    assert "--sov-ui-hit: 44px" in UIKIT_CSS
    assert ":focus-visible" in UIKIT_CSS
    assert "outline: 2px solid var(--accent) !important" in UIKIT_CSS
    assert "prefers-reduced-motion: reduce" in UIKIT_CSS
    assert "@view-transition" in UIKIT_CSS
    assert "navigation: auto" in UIKIT_CSS
    assert "sov-route-out 130ms ease-in" in UIKIT_CSS
    assert "sov-route-in 180ms cubic-bezier(.2, 0, 0, 1)" in UIKIT_CSS
    assert "::view-transition-old(root)" in UIKIT_CSS
    assert "animation-duration: .001ms !important" in UIKIT_CSS
    assert "transition: all" not in UIKIT_CSS
    assert "scale(.96)" in UIKIT_CSS
    assert "font-variant-numeric: tabular-nums" in UIKIT_CSS
    assert "text-wrap: balance" in UIKIT_CSS
    assert "text-wrap: pretty" in UIKIT_CSS
    assert "grid-template-columns: 200px minmax(0, 1fr)" in UIKIT_CSS
    assert "@media (max-width: 900px)" in UIKIT_CSS
    assert '--sov-ui-font-prose: "Segoe UI Variable Text", "Segoe UI"' in UIKIT_CSS
    assert "--sov-ui-font-size-body: 16px" in UIKIT_CSS
    assert "--sov-ui-font-size-control: 15px" in UIKIT_CSS
    assert "--sov-ui-font-size-meta: 14px" in UIKIT_CSS
    assert "--fs-xs: 14px" in CUSTOM_CSS
    assert "--fs-sm: 15px" in CUSTOM_CSS
    assert ".sov-ui-version-badge {" in UIKIT_CSS
    assert "font-size: var(--sov-ui-font-size-meta) !important;" in UIKIT_CSS
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


def test_desktop_typography_uses_readable_system_sans_scale():
    """The installed shell must not shrink rem text or inherit a terminal font."""
    assert "html {\n  font-size: 16px;" in UIKIT_CSS
    assert "html { font-size: 12px !important; }" not in CUSTOM_CSS
    assert "--sov-ui-font-size-body: 16px" in UIKIT_CSS
    assert "--sov-ui-font-size-control: 15px" in UIKIT_CSS
    assert "--sov-ui-font-size-meta: 14px" in UIKIT_CSS

    for css in (CUSTOM_CSS, theme_vars_css(True), theme_vars_css(False)):
        compact = css.replace(" ", "")
        assert "--font:var(--sov-ui-font-prose)" in compact
        assert "--font-chat:var(--sov-ui-font-prose)" in compact
        assert "ui-monospace" not in css

    assert ".sov-nav-switch {" in UIKIT_CSS
    assert "font-size: var(--sov-ui-font-size-control) !important;" in UIKIT_CSS


def test_mobile_chat_keeps_full_identity_and_uses_compact_send_action():
    assert ".sov-ui-shell .sov-chat-identity {\n    max-width: min(230px, calc(100vw - 112px));" in UIKIT_CSS
    assert ".sov-send-btn {\n    width: var(--sov-ui-hit) !important;" in UIKIT_CSS
    assert ".sov-send-btn .q-btn__content {\n    gap: 0 !important;\n    font-size: 0 !important;" in UIKIT_CSS
    assert ".sov-send-btn .q-icon {\n    font-size: 23px;" in UIKIT_CSS


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
    assert "height: 40px !important" in UIKIT_CSS
    assert "padding: 0 9px !important" in UIKIT_CSS
    assert "padding: 0 8px !important" in UIKIT_CSS
    assert "gap: var(--sov-ui-icon-gap)" in UIKIT_CSS
    assert "flex: 0 0 var(--sov-ui-icon-column)" in UIKIT_CSS

    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    assert 'with ui.row().classes("sov-primary-nav sov-mobile-primary-nav")' in header
    assert header.count("_primary_button(") == 3
    assert '"sov-nav-switch sov-nav-switch--studio sov-nav-switch--placeholder"' in header
    assert ".sov-mobile-primary-nav" in UIKIT_CSS
    assert "env(safe-area-inset-bottom)" in UIKIT_CSS
    mobile_nav = UIKIT_CSS[UIKIT_CSS.index(".sov-mobile-primary-nav") :]
    assert ".sov-nav-switch .q-btn__content {\n    width: 100%;\n    gap: 2px;" in mobile_nav


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


def test_workspace_navigation_has_no_separate_smeta_project():
    from sovushka.components import header as header_module

    sections = getattr(header_module, "visible_workspace_sections", lambda: ("rim",))()

    assert "rim" not in sections


def test_chat_ui_cannot_disable_required_reranker():
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")

    assert 'ui.switch("Реранкер"' not in chat
    assert '"reranker_enabled":' not in chat


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

    for page in ("diag.py", "volk.py", "mail.py", "documents.py"):
        source = Path("sovushka/pages", page).read_text(encoding="utf-8")
        assert "acronym_identity(" in source
    samovar = Path("sovushka/pages/samovar.py").read_text(encoding="utf-8")
    assert 'ui.label(workspace_title).classes("sov-datasets-hero__title")' in samovar


def test_documents_surface_contract_is_keyword_only_and_complete():
    page = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert "def build_documents(" in page
    assert 'surface: str = "documents"' in page
    assert "build_data_workspace(is_admin=is_admin)" in shell
    for surface in ("studio", "cad_bim"):
        assert f'build_documents(surface="{surface}")' not in shell


def test_product_navigation_has_one_data_destination_and_dormant_surfaces():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert 'tab_refs["data"] = ui.tab("Данные", icon="o_database")' in header
    assert 'ui.tab("Документы"' not in header
    assert 'ui.tab("Датасеты"' not in header
    assert 'ui.tab("Почта"' not in header
    assert '"CAD/BIM · скоро"' in header
    assert 'aria-label="CAD/BIM — скоро"' in header
    assert '"documents": "data"' in shell
    assert '"datasets": "data"' in shell
    assert '"mail": "chat"' in shell
    assert '"studio": "chat"' in shell
    assert '"cad_bim": "chat"' in shell
    assert 'build_documents(surface="studio")' not in shell
    assert 'build_documents(surface="cad_bim")' not in shell
    assert "build_mail()" not in shell
    assert "build_mail_settings()" not in shell


def test_critical_navigation_and_stage_three_to_five_controls_are_visible():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    mail = Path("sovushka/pages/mail.py").read_text(encoding="utf-8")

    for key, label, icon in (
        ("chat", "Чат", "o_forum"),
        ("config", "Конфигурация", "o_tune"),
    ):
        assert f'"{key}",' in header
        assert f'"{label}",' in header
        assert f'"{icon}",' in header
    assert "sov-primary-nav sov-mobile-primary-nav" in header
    assert "Рабочие разделы" in header
    assert 'tab_refs["history"]  = ui.tab("История",' in header
    assert 'ui.tab("ИСТОРИЯ"' not in header
    assert "sov-runtime-state" in header
    assert "ЛЕС на связи" in header
    assert 'ui.button("Обновить данные", icon="o_refresh"' in header
    assert '"Обновить ЛЕС",' in header
    assert '"Тема",' in header
    assert 'ui.label("Qdrant")' in header
    assert '"Профиль",' in header
    assert "Сеанс: {account_detail}" in header
    assert 'ui.button("Разделы", icon="o_apps")' in header
    assert "ui.menu_item(" in header
    assert 'tab_refs[key].tooltip(label)' in header
    assert 'f"sov-nav-switch sov-nav-switch--{key}"' in header
    assert "sov-nav-switch--active" in header
    assert '"Студия · скоро"' in header
    assert '"Раздел готовится к выпуску"' in header
    assert '"sov-nav-switch sov-nav-switch--studio sov-nav-switch--placeholder"' in header
    assert '.props(\'flat no-caps disable aria-label="Студия — скоро"\')' in header
    assert ".sov-nav-switch--placeholder.q-btn--disabled" in UIKIT_CSS
    assert "/classic?tab=studio" not in header
    assert "tabs.set_value(tab_refs[key])" in header
    assert "window.history.replaceState" in header
    assert 'active_primary="config"' in Path("sovushka_ng.py").read_text(encoding="utf-8")
    assert "sov-docs-sticky-ask" in documents
    assert '"Спросить в чате"' in documents
    assert '"Забрать ещё"' in mail
    assert "sov-mail-status-strip" in mail
    assert '"target_file"' in mail


def test_hidden_studio_route_falls_back_to_chat_without_deleting_studio_code():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")

    assert 'build_documents(surface="studio")' not in shell
    assert 'build_documents(surface="cad_bim")' not in shell
    assert '"studio": "chat"' in shell
    assert '"cad_bim": "chat"' in shell
    assert '"studio"' in documents
    assert '"cad_bim"' in documents


def test_configuration_home_uses_uikit_and_progressive_disclosure():
    diag = Path("sovushka/pages/diag.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert 'classes("sov-config-page")' in diag
    assert 'variant="primary"' in diag
    assert '"Проверить систему"' in diag
    assert '"Рабочие контуры"' in diag
    assert '"Контур RAG"' in diag
    for stage in (
        "Native RRF",
        "Иерархия",
        "RAPTOR",
        "ColBERT",
        "Cross-encoder",
        "Parent / context",
        "Exact evidence",
    ):
        assert stage in diag
    assert 'status_badge("Загрузка…", "muted")' in diag
    assert 'api_get("/api/health")' in diag
    assert 'api_get("/api/rag/advanced/preflight")' in diag
    assert 'api_post("/api/rag/advanced/raptor/build", {})' in diag
    assert '"Danger · построить RAPTOR"' in diag
    assert '"Preflight без загрузки модели"' in diag
    assert '"Ошибок до stop ColBERT"' in diag
    assert '"Локальный API резюме"' in diag
    assert "Основной RAG/RRF работает независимо" in diag
    assert "Политика включена, индекс ещё не построен" in diag
    assert "Модель не загружена; базовый поиск продолжает работать" in diag
    for internal_detail in (
        "model_loaded=false",
        'f"checkpoint {raptor.get',
        'detail_parts.append(f"circuit',
        'detail_parts.append(f"ошибка',
    ):
        assert internal_detail not in diag
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


def test_diag_initial_pipeline_timer_is_registered_after_loader_definition():
    source = Path("sovushka/pages/diag.py").read_text(encoding="utf-8")

    assert source.index("async def load_rag_pipeline()") < source.index(
        "ui.timer(0.1, lambda: asyncio.create_task(load_rag_pipeline())"
    )


def test_dataset_registry_uses_uikit_and_keeps_operator_controls_secondary():
    source = Path("sovushka/pages/samovar.py").read_text(encoding="utf-8")
    active = source.split("def build_samovar_legacy()", maxsplit=1)[0]

    assert '.classes("w-full sov-datasets-page")' in active
    assert '"Добавить набор"' in active
    assert '"Сводка корпуса"' in active
    assert '"Найти набор данных"' in active
    assert '"Открыть файлы"' in active
    assert "files_dialog" not in active
    assert "'tab': open_tab" in active
    assert 'ui.navigate.to(f"{target_path}?' in active
    assert '"Путь к папке"' in active
    assert '"Проводник…"' in active
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


def test_documents_service_upload_is_a_compact_action_until_a_file_is_selected():
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")

    assert "sov-service-file-upload" in documents
    assert ".sov-service-file-upload .q-uploader__subtitle" in UIKIT_CSS
    assert ".sov-service-file-upload .q-uploader__list" in UIKIT_CSS
    assert "display: none" in UIKIT_CSS


def test_documents_deep_link_selects_requested_dataset():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    data_workspace = Path("sovushka/pages/data_workspace.py").read_text(encoding="utf-8")

    assert '"documents": "data"' in shell
    assert 'query_params.get("dataset_id")' in data_workspace
    assert 'query_params.get("dataset_id")' in documents
    assert 'await _select_dataset(initial_dataset)' in documents


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


def test_tools_surface_contains_sources_without_competing_prompt_editor():
    tools = Path("sovushka/pages/instrumenty.py").read_text(encoding="utf-8")

    assert "sov-tools-page" in tools
    assert '"Источники данных"' in tools
    assert '"Системные промпты"' not in tools
    assert "/api/prompts" not in tools
    assert "_refresh_prompts" not in tools
    assert "_render_prompt_block" not in tools
    assert "action_button(" in tools
    assert "panel(" in tools


def test_remaining_operator_surfaces_use_uikit_without_page_local_visual_styles():
    history = Path("sovushka/pages/history.py").read_text(encoding="utf-8")
    access = Path("sovushka/pages/volk.py").read_text(encoding="utf-8")
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")

    assert "sov-history-page" in history
    assert "render_feedback_state(" in history
    assert "action_button(" in history
    assert "format_chat_request_clock(" in history
    assert "ui.card(" not in history
    assert "_html(" not in history
    assert ".style(" not in history

    assert "sov-access-page" in access
    assert "select_field(" in access
    assert "sov-access-key-row" in access
    assert "ui.table(" not in access
    assert ".style(" not in access

    visual = shell[shell.index("def _build_qdrant_visualizer_panel"):shell.index(
        "_LIGHT_THEME_MIGRATION"
    )]
    assert "sov-visual-page" in visual
    assert "action_button(" in visual
    assert 'title="Граф знаний ЛЕС"' in visual
    assert ".style(" not in visual

    for contract in (
        ".sov-history-page",
        ".sov-history-row",
        ".sov-access-page",
        ".sov-access-key-row",
        ".sov-visual-page",
        ".sov-visual-iframe",
    ):
        assert contract in UIKIT_CSS


def test_uikit_registry_exposes_select_with_shared_control_contract():
    components = Path("sovushka/uikit/components.py").read_text(encoding="utf-8")

    assert "def select_field(" in components
    assert '"sov-ui-select"' in components
    assert 'props.append("stack-label")' in components
    assert ".sov-ui-select .q-field__control" in UIKIT_CSS

    for contract in (
        ".sov-tools-hero",
        ".sov-tools-source",
        ".sov-tools-prompt",
        ".sov-tools-layer",
    ):
        assert contract in UIKIT_CSS


def test_samovar_exposes_index_recovery_dispositions_and_skips():
    samovar = Path("sovushka/pages/samovar.py").read_text(encoding="utf-8")

    assert '("skip",   "Пропущено"' in samovar
    assert '"SKIPPED": "SKIPPED"' in samovar
    assert "retryable:" in samovar
    assert "terminal:" in samovar
    assert "auto-repair:" in samovar
    assert "item.get('error_code')" in samovar


def test_rag_advanced_polling_obeys_lazy_tab_lifecycle():
    diagnostics = Path("sovushka/pages/diag.py").read_text(encoding="utf-8")

    assert "advanced_status_timer = ui.timer(3.0" in diagnostics
    assert 'return {"timers": [advanced_status_timer]}' in diagnostics
