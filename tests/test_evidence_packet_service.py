from types import SimpleNamespace as N

from proxy.services.evidence_packet_service import (
    SCHEMA,
    build_retrieval_evidence_packet,
    render_retrieval_evidence_for_model,
    verify_answer_source_labels,
)


def _chunk(content="Требование к системе", **meta):
    return N(
        content=content,
        doc_id="doc-1",
        doc_name="BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx",
        score=0.81,
        meta={"dataset_id": "bai", "page": 7, "parent_heading": "Система связи", **meta},
    )


def test_packet_keeps_navigation_outside_evidence_and_preserves_coordinates():
    packet = build_retrieval_evidence_packet(
        question="Какие решения по связи?",
        chunks=[_chunk()],
        retrieval_trace={"mode": "hybrid", "quality_status": "good", "embedding_model": "qwen"},
        navigation=[{"kind": "dataset_brief", "available": True}],
        deterministic_evidence=[{"source": "metadb.documents", "kind": "project_inventory"}],
    )

    payload = packet.to_dict(max_chars=4000)

    assert payload["schema"] == SCHEMA
    assert payload["evidence_status"] == "available"
    assert payload["navigation"] == [{
        "kind": "dataset_brief", "available": True, "context_role": "navigation", "is_evidence": False,
    }]
    source = payload["evidence"]["sources"][0]
    assert source["context_label"] == "Источник 1"
    assert source["locator"]["dataset_id"] == "bai"
    assert source["locator"]["page"] == 7
    assert source["locator"]["parent_heading"] == "Система связи"
    assert payload["deterministic_evidence"][0]["is_evidence"] is True


def test_degraded_retrieval_is_partial_even_when_chunks_exist():
    packet = build_retrieval_evidence_packet(
        question="Найди требование",
        chunks=[_chunk()],
        retrieval_trace={"mode": "lexical_only", "quality_status": "degraded", "fallback_reason": "contract"},
    )

    payload = packet.to_dict(max_chars=4000)

    assert payload["evidence_status"] == "partial"
    assert payload["retrieval"]["fallback_reason"] == "contract"
    assert payload["answer_status"] == "separate_in_chat_response"
    assert payload["calculation_status"] == "not_applicable"
    rendered = render_retrieval_evidence_for_model(packet, max_chars=4000)
    assert "ЧАСТИЧНОЕ ПОКРЫТИЕ" in rendered
    assert "не называй их полным покрытием корпуса" in rendered


def test_empty_packet_is_missing_and_model_renderer_does_not_invent_source():
    packet = build_retrieval_evidence_packet(
        question="Где раздел?",
        chunks=[],
        retrieval_trace={"quality_status": "good"},
        missing=["Нужен целевой документ"],
    )

    payload = packet.to_dict(max_chars=4000)

    assert payload["evidence_status"] == "missing"
    assert payload["evidence"]["sources"] == []
    assert payload["missing"] == ["Нужен целевой документ"]
    rendered = render_retrieval_evidence_for_model(packet, max_chars=4000)
    assert "ФРАГМЕНТЫ НЕ НАЙДЕНЫ" in rendered
    assert "Нет найденных фрагментов" in rendered


def test_renderer_and_packet_source_map_use_the_same_visible_citation_numbering():
    chunks = [
        _chunk("Первый фрагмент"),
        N(content="Второй фрагмент", doc_id="doc-2", doc_name="BAI/IN/КСБ.pdf", score=0.72, meta={}),
    ]
    packet = build_retrieval_evidence_packet(
        question="Покажи решения",
        chunks=chunks,
        retrieval_trace={"quality_status": "good"},
    )

    rendered = render_retrieval_evidence_for_model(packet, max_chars=4000)
    payload = packet.to_dict(max_chars=4000)

    assert "[Источник 1 | BAI/OUT/ИОС 5.2/03_Пояснительная записка.docx" in rendered
    assert "[Источник 2 | BAI/IN/КСБ.pdf" in rendered
    assert [item["context_label"] for item in payload["evidence"]["sources"]] == ["Источник 1", "Источник 2"]


def test_answer_citation_check_rejects_invented_and_missing_labels():
    source_map = [{"index": 1, "doc_name": "one.pdf"}, {"index": 2, "doc_name": "two.pdf"}]

    assert verify_answer_source_labels("Факт [Источник 1 | one.pdf]", source_map)["status"] == "supported_labels"
    assert verify_answer_source_labels("Факт [Источник 3 | fake.pdf]", source_map)["status"] == "invalid_labels"
    assert verify_answer_source_labels("Факт без ссылки", source_map)["status"] == "missing_labels"
