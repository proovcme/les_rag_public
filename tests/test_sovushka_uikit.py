from pathlib import Path

import pytest

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


def test_critical_surfaces_use_uikit_and_blocked_state():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    chat = Path("sovushka/pages/chat.py").read_text(encoding="utf-8")
    documents = Path("sovushka/pages/documents.py").read_text(encoding="utf-8")
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")

    assert "ui.add_head_html(UIKIT_CSS)" in shell
    assert shell.count("sov-ui-shell") >= 2
    assert "sov-ui-header" in header
    assert "sov-ui-documents" in documents
    assert "sov-ui-evidence-card" in chat
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

    assert '"Чат",' in header and 'icon="o_forum"' in header
    assert '"Конфигурация",' in header and 'icon="o_tune"' in header
    assert "sov-nav-switch--chat" in header
    assert "sov-nav-switch--config" in header
    assert "sov-docs-sticky-ask" in documents
    assert '"Спросить в чате"' in documents
    assert '"Забрать ещё"' in mail
    assert "sov-mail-status-strip" in mail
    assert '"target_file"' in mail
