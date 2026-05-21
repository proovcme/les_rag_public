from dataclasses import dataclass

from proxy.services.saferag_service import build_context, concentrate_sources, final_answer_for_status, source_names


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float = 1.0


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


def test_source_names_are_unique():
    assert set(source_names([Chunk("a", "doc-a"), Chunk("b", "doc-a"), Chunk("c", "doc-b")])) == {
        "doc-a",
        "doc-b",
    }


def test_final_answer_for_status_blocks_unknown_statuses():
    assert final_answer_for_status("answer", "VERIFIED") == ("answer", "VERIFIED")
    answer, status = final_answer_for_status("answer", "BOGUS")

    assert status == "UNKNOWN"
    assert answer != "answer"
