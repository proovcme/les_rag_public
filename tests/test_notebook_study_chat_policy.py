import inspect

from proxy.routers import chat as chat_router
from proxy.routers.chat import _notebook_study_validation_status
from proxy.services import chat_evidence_application_service
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
    source = inspect.getsource(chat_router._run_chat) + inspect.getsource(
        chat_evidence_application_service._execute_chat_evidence_application
    )

    assert "LES_NOTEBOOK_STUDY_CHAT_MAX_TOKENS" not in source
    assert "5-8 строк" not in source
    assert "до 6 строк" not in source


def test_notebook_study_artifact_is_markdown_not_auto_table_text():
    source = inspect.getsource(chat_evidence_application_service._execute_chat_evidence_application)

    assert '"title": "Инженерный блокнот"' in source
    assert '"mode": "markdown"' in source


def test_sovushka_moves_source_notes_to_artifact_instead_of_quote_blocks():
    from pathlib import Path

    chat_ui = Path("sovushka/pages/chat.py").read_text()

    assert "_format_sources_as_quotes" in chat_ui
    assert "source_notes_artifact" in chat_ui
    assert "> Источники:" not in chat_ui


def test_local_notebook_study_uses_model_owned_tools_without_hidden_prefetch():
    router_source = inspect.getsource(chat_router._prepare_notebook_reader_memory)
    app_source = inspect.getsource(chat_evidence_application_service._execute_chat_evidence_application)

    assert '_env_bool("LES_NOTEBOOK_READER_ON_STUDY", False)' in router_source
    assert '_env_bool("LES_CHAT_TOOL_LOOP_ENABLED", True)' in app_source
    assert '"model_owns_selection": True' in app_source
    assert '"reason": "local_single_pass"' not in app_source
    assert '"reason": "model_first_single_rrf"' in app_source
    assert "LES_TOPIC_GUIDED_PREFETCH_ENABLED" not in app_source
    assert "LES_NOTEBOOK_QUERY_PREFETCH_ENABLED" not in app_source
    assert "build_notebook_study_pack(" not in app_source
    assert "_study_retrieve_file" not in app_source
