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
