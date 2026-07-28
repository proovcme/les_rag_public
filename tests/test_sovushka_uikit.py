from pathlib import Path

import pytest

from sovushka.styles import _DARK_THEME, _LIGHT_THEME
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
    assert "С.О.В.А. · Чат" in chat
    assert "Система обработки и выдачи ответов" in chat
    assert 'class="sov-owl-mark"' in chat
    assert 'aria-label="С.О.В.А. — Система обработки и выдачи ответов"' in chat
    assert 'aria-label="Выбрать область"' not in chat
    assert "sov-attach-btn" in chat
    assert 'render_feedback_state(' in chat
    assert '"blocker": blocker' in chat


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
