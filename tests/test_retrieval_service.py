from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from proxy.services.retrieval_service import (
    classify_query,
    expand_retrieval_query,
    infer_dataset_filter,
    resolve_dataset_ids,
    retrieve_chat_chunks,
)
from proxy.services.lexical_index_service import LexicalIndex


@dataclass
class Dataset:
    id: str
    name: str


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.collection_name = "test_collection"

    async def list_datasets(self):
        return [
            Dataset("ds-1", "NTD_FIRE_Index"),
            Dataset("ds-4", "NTD_OTHER_Index"),
            Dataset("ds-2", "Other_Index"),
            Dataset("ds-3", "GKRF_Index"),
        ]

    async def retrieve(self, question, dataset_ids=None, top_k=5):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        return [Chunk(f"text-{i}", f"doc-{i}", 1.0 - i * 0.01) for i in range(top_k)]


class FakeReranker:
    def __init__(self, mlx_url, mode):
        self.mlx_url = mlx_url
        self.mode = mode

    async def rerank(self, question, chunks, top_k=5):
        return [
            SimpleNamespace(text=chunks[2]["text"], metadata=chunks[2]["metadata"]),
            SimpleNamespace(text=chunks[0]["text"], metadata=chunks[0]["metadata"]),
        ][:top_k]


class FailingReranker:
    def __init__(self, mlx_url, mode):
        pass

    async def rerank(self, question, chunks, top_k=5):
        raise RuntimeError("rerank failed")


@pytest.mark.asyncio
async def test_resolve_dataset_ids_uses_named_filter_when_ids_missing():
    backend = FakeBackend()

    resolved = await resolve_dataset_ids(backend, None, "NTD", SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))

    assert resolved == ["ds-1", "ds-4"]


@pytest.mark.asyncio
async def test_resolve_dataset_ids_preserves_explicit_ids():
    backend = FakeBackend()

    resolved = await resolve_dataset_ids(backend, ["explicit"], "NTD", SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))

    assert resolved == ["explicit"]


def test_infer_dataset_filter_routes_normative_queries():
    assert infer_dataset_filter("ширина путей эвакуации") == "NTD_FIRE"
    assert infer_dataset_filter("список разделов проектной документации по постановлению 87") == "GKRF"


def test_classify_query_explains_route():
    route = classify_query("какое сечение кабеля заземления")

    assert route.dataset_filter == "NTD_ELECTRICAL"
    assert route.reason == "electrical_keyword"
    assert route.expanded_query == "какое сечение кабеля заземления"


def test_expand_retrieval_query_for_pp87_section_list():
    expanded = expand_retrieval_query("список разделов проектной документации по постановлению 87")

    assert "Проектная документация на объекты капитального строительства состоит из 12 разделов" in expanded
    assert "Раздел 1 Пояснительная записка" in expanded
    assert "линейные объекты" in expanded


def test_expand_retrieval_query_for_fire_and_hvac_normative_anchors():
    fire = expand_retrieval_query("В каких случаях допускается не выполнять систему дымоудаления?")
    hvac = expand_retrieval_query("Где смотреть требования к воздухообмену и расходу воздуха?")

    assert "СП 7.13130" in fire
    assert "противодымная вентиляция" in fire
    assert "СП 60.13330" in hvac
    assert "воздухообмен" in hvac


@pytest.mark.asyncio
async def test_resolve_dataset_ids_infers_filter_from_question():
    backend = FakeBackend()

    resolved = await resolve_dataset_ids(
        backend,
        None,
        None,
        SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        question="список разделов проектной документации по постановлению 87",
    )

    assert resolved == ["ds-3"]


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_uses_plain_retrieval_when_reranker_disabled():
    backend = FakeBackend()

    chunks = await retrieve_chat_chunks(
        question="q",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=False,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    )

    assert len(chunks) == 8
    assert backend.calls == [{"question": "q", "dataset_ids": ["ds-1"], "top_k": 8}]


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_reranks_pool_when_available():
    backend = FakeBackend()

    chunks = await retrieve_chat_chunks(
        question="q",
        dataset_ids=None,
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    )

    assert [chunk.content for chunk in chunks] == ["text-2", "text-0"]
    assert backend.calls[0]["top_k"] == 12


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_runs_reranker_inside_llm_budget():
    backend = FakeBackend()

    class TrackingSemaphore:
        def __init__(self):
            self.entered = False
            self.active = False
            self.seen_inside = False

        async def __aenter__(self):
            self.entered = True
            self.active = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self.active = False

    budget = TrackingSemaphore()

    class ObservingReranker:
        def __init__(self, mlx_url, mode):
            pass

        async def rerank(self, question, chunks, top_k=5):
            budget.seen_inside = budget.active
            return [SimpleNamespace(text=chunks[0]["text"], metadata=chunks[0]["metadata"])]

    chunks = await retrieve_chat_chunks(
        question="q",
        dataset_ids=None,
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=ObservingReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        llm_semaphore=budget,
    )

    assert [chunk.content for chunk in chunks] == ["text-0"]
    assert budget.entered is True
    assert budget.seen_inside is True
    assert budget.active is False


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_falls_back_to_top_five_on_reranker_error():
    backend = FakeBackend()

    chunks = await retrieve_chat_chunks(
        question="q",
        dataset_ids=None,
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FailingReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    )

    assert [chunk.content for chunk in chunks] == [f"text-{i}" for i in range(6)]


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_returns_hybrid_trace(monkeypatch, tmp_path):
    db_path = tmp_path / "lex.db"
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    index = LexicalIndex(str(db_path))
    index.upsert_chunks(
        "test_collection",
        [
            {
                "point_id": "lex-1",
                "dataset_id": "ds-1",
                "doc_id": "doc-lex",
                "doc_name": "СП 1.13130.docx",
                "text": "СП 1.13130 ширина путей эвакуации",
            }
        ],
    )
    index.mark_collection("test_collection", point_count=1, indexed_count=1)
    backend = FakeBackend()

    result = await retrieve_chat_chunks(
        question="ширина путей эвакуации по СП 1.13130",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.trace.mode == "hybrid"
    assert result.trace.lexical_count == 1
    assert result.payload()["quality"]["status"] == "good"
    assert any(chunk.doc_name == "СП 1.13130.docx" for chunk in result.chunks)
