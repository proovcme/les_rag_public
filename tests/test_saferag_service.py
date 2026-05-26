from dataclasses import dataclass

from proxy.services.saferag_service import (
    build_context,
    build_validation_context,
    concentrate_sources,
    final_answer_for_status,
    rank_chunks_for_question,
    source_names,
)


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float = 1.0
    meta: dict | None = None


def test_concentrate_sources_keeps_top_documents_and_filters_noise():
    chunks = [
        Chunk("a1", "doc-a", 0.9),
        Chunk("b1", "doc-b", 0.7),
        Chunk("c1", "doc-c", 0.4),
        Chunk("a2", "doc-a", 0.6),
    ]

    focused = concentrate_sources(chunks, max_docs=1, min_score=0.45)

    assert [c.content for c in focused] == ["a1", "a2"]


def test_concentrate_sources_relaxes_threshold_when_all_scores_are_low():
    chunks = [
        Chunk("weak-best", "doc-a", 0.2),
        Chunk("weak-close", "doc-a", 0.17),
        Chunk("weak-far", "doc-b", 0.1),
    ]

    focused = concentrate_sources(chunks, max_docs=1, min_score=0.45)

    assert [c.content for c in focused] == ["weak-best", "weak-close"]


def test_build_context_respects_character_limit_before_adding_next_chunk():
    chunks = [
        Chunk("short", "doc-a"),
        Chunk("this is too long for the chosen limit", "doc-b"),
    ]

    context = build_context(chunks, max_chars=20)

    assert context == "[doc-a]:\nshort"


def test_build_context_can_include_evidence_metadata():
    context = build_context(
        [Chunk("text", "doc-a", 0.73, {"source_page": 5, "doc_type": "NORMATIVE"})],
        max_chars=500,
        include_metadata=True,
    )

    assert context.startswith("[Источник 1 | doc-a | score=0.730 | стр. 5 | NORMATIVE]:")


def test_rank_chunks_for_question_boosts_lexical_matches():
    chunks = [
        Chunk("общий текст", "doc-a", 0.8),
        Chunk("требования противодымной защиты", "doc-b", 0.7),
    ]

    ranked = rank_chunks_for_question("Что относится к противодымной защите?", chunks)

    assert ranked[0].doc_name == "doc-b"


def test_concentrate_sources_uses_lexical_rank_score():
    chunks = [
        Chunk("общий текст", "doc-a", 0.8),
        Chunk("требования противодымной защиты", "doc-b", 0.7),
    ]

    ranked = rank_chunks_for_question("Что относится к противодымной защите?", chunks)
    focused = concentrate_sources(ranked, max_docs=1, min_score=0.35)

    assert [chunk.doc_name for chunk in focused] == ["doc-b"]


def test_concentrate_sources_deduplicates_copied_documents():
    chunks = [
        Chunk("same text", "ГОСТ Р 59638-2021.docx", 0.8),
        Chunk("same text", "ГОСТ Р 59638-2021 (1).docx", 0.79),
        Chunk("other", "СП 1.13130.docx", 0.78),
    ]

    focused = concentrate_sources(chunks, max_docs=3, min_score=0.35)

    assert [chunk.doc_name for chunk in focused] == ["ГОСТ Р 59638-2021.docx", "СП 1.13130.docx"]


def test_build_validation_context_keeps_cited_windows():
    long_text = "x" * 500
    chunks = [
        Chunk(long_text, "doc-a"),
        Chunk("second cited window", "doc-b"),
    ]

    context = build_validation_context(chunks, max_chars=1200)

    assert "[doc-a]:\n" + long_text in context
    assert "[doc-b]:\nsecond cited window" in context


def test_source_names_are_unique_and_ordered():
    assert source_names([Chunk("a", "doc-b"), Chunk("b", "doc-a"), Chunk("c", "doc-b")]) == [
        "doc-b",
        "doc-a",
    ]


def test_final_answer_for_status_blocks_unknown_statuses():
    assert final_answer_for_status("answer", "VERIFIED") == ("answer", "VERIFIED")
    assert final_answer_for_status("answer", "UNVALIDATED") == ("answer", "UNVALIDATED")
    answer, status = final_answer_for_status("answer", "BOGUS")

    assert status == "UNKNOWN"
    assert answer != "answer"
