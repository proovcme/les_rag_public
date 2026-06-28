import inspect

from proxy.routers import chat as chat_router
from proxy.routers.chat import _notebook_study_validation_status
from proxy.services.saferag_service import SAFE_FALLBACK, final_answer_for_status


def test_notebook_study_validation_warns_instead_of_erasing_contextual_answer():
    status = _notebook_study_validation_status("HALLUCINATION", has_context=True)

    answer, final_status = final_answer_for_status("инженерная сводка по источникам", status)

    assert final_status == "UNVALIDATED"
    assert answer != SAFE_FALLBACK
    assert "инженерная сводка" in answer


def test_notebook_study_empty_context_still_blocks_unknown_answer():
    status = _notebook_study_validation_status("UNKNOWN", has_context=False)

    answer, final_status = final_answer_for_status("ничем не подтверждено", status)

    assert final_status == "UNKNOWN"
    assert answer == SAFE_FALLBACK


def test_notebook_study_has_no_special_short_token_cap():
    source = inspect.getsource(chat_router._run_chat)

    assert "LES_NOTEBOOK_STUDY_CHAT_MAX_TOKENS" not in source
    assert "5-8 строк" not in source
    assert "до 6 строк" not in source


def test_notebook_study_artifact_is_markdown_not_auto_table_text():
    source = inspect.getsource(chat_router._run_chat)

    assert '"title": "Инженерный блокнот"' in source
    assert '"mode": "markdown"' in source


def test_sovushka_formats_source_markers_as_quotes():
    from pathlib import Path

    chat_ui = Path("sovushka/pages/chat.py").read_text()
    styles = Path("sovushka/styles.py").read_text()

    assert "_format_sources_as_quotes" in chat_ui
    assert "Источники:" in chat_ui
    assert ".sov-chat-md blockquote" in styles
