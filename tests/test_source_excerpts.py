"""Цитаты из источников: конкретные фрагменты норм под ответом (дедуп, обрезка)."""
from types import SimpleNamespace as N

from proxy.routers.chat import _generation_token_budget, _local_context_budget, source_excerpts
from proxy.services.saferag_service import source_map_for_context


def test_dedup_truncate_skip_empty():
    chunks = [
        N(content="Ширина путей эвакуации 1,2 м " * 50, doc_name="NTD/СП 4.13130.docx", score=0.81, meta={"dataset_id": "ds1"}),
        N(content="", doc_name="empty.docx", score=0.5, meta={}),
        N(content="Ширина путей эвакуации 1,2 м " * 50, doc_name="NTD/СП 4.13130.docx", score=0.79, meta={}),  # дубль
        N(content="Дымоудаление по СП 7.13130", doc_name="NTD/СП 7.13130.docx", score=0.7, meta={"dataset_id": "ds2"}),
    ]
    ex = source_excerpts(chunks, max_n=6, max_chars=100)
    assert len(ex) == 2  # пустой пропущен, дубль дедуплицирован
    assert ex[0]["doc"] == "NTD/СП 4.13130.docx"
    assert ex[0]["text"].endswith("…")  # длинный обрезан
    assert ex[0]["score"] == 0.81 and ex[0]["dataset_id"] == "ds1"
    assert ex[1]["doc"] == "NTD/СП 7.13130.docx"


def test_max_n_limit():
    chunks = [N(content=f"фрагмент {i}", doc_name=f"d{i}.docx", score=0.5, meta={}) for i in range(10)]
    assert len(source_excerpts(chunks, max_n=3)) == 3


def test_empty_input():
    assert source_excerpts([]) == []
    assert source_excerpts(None) == []


def test_short_text_not_truncated():
    ex = source_excerpts([N(content="короткий пункт", doc_name="d.docx", score=0.6, meta={})], max_chars=700)
    assert ex[0]["text"] == "короткий пункт"  # без многоточия


def test_source_map_matches_context_numbering_and_limit():
    chunks = [
        N(
            content="первый фрагмент",
            doc_name="СП 1.docx",
            score=0.81,
            meta={"dataset_id": "ds1", "page": 7, "source_ref": "СП 1.docx#p7"},
        ),
        N(content="второй фрагмент " * 20, doc_name="СП 2.docx", score=0.7, meta={}),
    ]

    full = source_map_for_context(chunks, max_chars=2000, include_metadata=True)

    assert [item["label"] for item in full] == ["Источник 1", "Источник 2"]
    assert full[0]["doc_name"] == "СП 1.docx"
    assert full[0]["page"] == 7
    assert full[0]["dataset_id"] == "ds1"
    assert full[0]["source_ref"] == "СП 1.docx#p7"

    limited = source_map_for_context(chunks, max_chars=180, include_metadata=True)
    assert len(limited) == 1
    assert limited[0]["label"] == "Источник 1"


def test_local_context_budget_is_smaller_than_cloud(monkeypatch):
    monkeypatch.delenv("RAG_LOCAL_CHAT_CONTEXT_CHARS", raising=False)
    cloud = _local_context_budget(local_big=False, big_context=True)
    local = _local_context_budget(local_big=True, big_context=False)

    assert local["context_chars_limit"] < cloud["context_chars_limit"]
    assert local["context_max_chunks"] < cloud["context_max_chunks"]
    assert local["focus_max_chunks"] == 8
    assert local["context_window_chars"] == 1200


def test_local_generation_budget_caps_verbose_forms(monkeypatch):
    monkeypatch.delenv("RAG_LOCAL_CHAT_MAX_TOKENS", raising=False)

    assert _generation_token_budget(max_tokens=8192, local_big=True, attempt=1, intent="default") == 700
    assert _generation_token_budget(max_tokens=1024, local_big=True, attempt=1, intent="brief") == 700
    assert _generation_token_budget(max_tokens=8192, local_big=False, attempt=1, intent="default") == 8192
    assert _generation_token_budget(max_tokens=8192, local_big=True, attempt=2, intent="default") == 2048
