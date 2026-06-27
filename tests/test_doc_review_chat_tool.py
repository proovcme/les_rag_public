"""doc_review как ЧАТ-инструмент: зарегистрирован в LLM-агент-роутере + сервис-оркестратор review_dataset.
Чат («проверь комплект по ГОСТ») → роутер выбирает doc_review → блок chat.py исполняет на скоупном датасете.
"""

import pytest


def test_doc_review_registered_in_router():
    from proxy.services.agent_router_service import _BY_NAME, _FEWSHOT

    assert "doc_review" in _BY_NAME
    tool = _BY_NAME["doc_review"]
    assert tool["handler"] is not None
    assert "ГОСТ Р 21.101" in tool["desc"] or "нормоконтроль" in tool["desc"].lower()
    assert any(name == "doc_review" for _, name in _FEWSHOT)


def test_review_dataset_no_documents_raises():
    from proxy.services import doc_review_service as dr

    with pytest.raises(ValueError) as e:
        dr.review_dataset("no-such-dataset-xyz")
    assert str(e.value) == "no_documents"


def test_review_to_chat_text_shape():
    # рендер для чата: человекочитаемый отчёт + защита, а не служебная трассировка.
    from proxy.services import doc_review_service as dr
    from proxy.services.normcontrol_review_map_service import load_review_map

    rmap = load_review_map("gost_r_21_101_2026")
    text = dr.review_to_chat_text([], rmap)
    assert "ГОСТ Р 21.101" in text
    assert "предварительный отчёт ЛЕС" in text
    assert "### Как защищать отчёт" in text
    assert "инженер" in text.lower()
    assert "| Класс | Кол-во |" not in text
    assert "Рабочая память" not in text
    assert "LES.md" not in text
    assert "manual_required" not in text
    assert "review_needed" not in text
