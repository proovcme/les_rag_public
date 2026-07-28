from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from proxy.services.retrieval_service import (
    classify_query,
    expand_retrieval_query,
    infer_dataset_filter,
    hybrid_backend,
    resolve_dataset_ids,
    retrieve_chat_chunks,
)
from proxy.services.lexical_index_service import LexicalIndex
from proxy.services.saferag_service import rank_chunks_for_question
from backend.interface import EmbeddingContractError


@dataclass
class Dataset:
    id: str
    name: str


@dataclass
class Chunk:
    content: str
    doc_name: str
    score: float
    meta: dict | None = None


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.doc_filters = []
        self.collection_name = "test_collection"

    async def list_datasets(self):
        return [
            Dataset("ds-1", "NTD_FIRE_Index"),
            Dataset("ds-4", "NTD_OTHER_Index"),
            Dataset("ds-2", "Other_Index"),
            Dataset("ds-3", "GKRF_Index"),
        ]

    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        return [Chunk(f"text-{i}", f"doc-{i}", 1.0 - i * 0.01) for i in range(top_k)]

    async def retrieve_native_hybrid(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        return await self.retrieve(question, dataset_ids=dataset_ids, top_k=top_k, doc_filter=doc_filter)


class EmptyBackend:
    def __init__(self):
        self.calls = []
        self.doc_filters = []
        self.collection_name = "empty_collection"

    async def list_datasets(self):
        return []

    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        raise AssertionError("empty retrieval should not call backend.retrieve")


class ContractMismatchBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        raise EmbeddingContractError(
            "embedding contract mismatch: expected=qwen3-embedding-0.6b, actual=BAAI/bge-m3"
        )


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


class NativeHybridBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.native_calls = []

    async def retrieve_native_hybrid(self, question, dataset_ids=None, top_k=8, doc_filter=None):
        self.native_calls.append(
            {"question": question, "dataset_ids": dataset_ids, "top_k": top_k, "doc_filter": doc_filter}
        )
        return [Chunk("native text", "native.docx", 0.99)]


class FailingNativeBackend(FakeBackend):
    async def retrieve_native_hybrid(self, question, dataset_ids=None, top_k=8, doc_filter=None):
        raise RuntimeError("qdrant unavailable")


class ExactSourceBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        chunks = [
            Chunk("old Revit projection", "cad_bim_json_8f98ad7e9242.md", 0.99),
            Chunk("Import ID: db1941fd7ee6\nObject type: ACAD_TABLE", "cad_bim_json_db1941fd7ee6.md", 0.1),
        ]
        chunks.extend(Chunk(f"tail-{idx}", f"tail-{idx}.md", 0.05) for idx in range(max(top_k - 2, 0)))
        return chunks[:top_k]


class ExactIdentifierBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        chunks = [
            Chunk("Related equipment B454 and valve schedule", "schedule.xlsx", 0.99),
            Chunk("LES-SMOKE-B454-VALVE-731 AIRFLOW 7310 M3/H", "drawing.pdf", 0.10),
            Chunk("General project notes", "notes.docx", 0.50),
        ]
        chunks.extend(Chunk(f"tail-{idx}", f"tail-{idx}.md", 0.05) for idx in range(max(top_k - 3, 0)))
        return chunks[:top_k]


class ExactNormBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        chunks = [
            Chunk("Ссылка на СП 7.13130 в требованиях", "СП 484.1311500.docx", 0.99),
            Chunk("Пункт 7.3 противодымной вентиляции", "СП 7.13130.docx", 0.10),
        ]
        chunks.extend(Chunk(f"tail-{idx}", f"tail-{idx}.docx", 0.05) for idx in range(max(top_k - 2, 0)))
        return chunks[:top_k]


class CadSourceNameBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        chunks = [
            Chunk(
                "# CAD/BIM JSON projection\nSource formats: DWG, DXF, RVT, IFC",
                "cad_bim_json_8f98ad7e9242.md",
                0.99,
            ),
            Chunk(
                "Source path: /RAG/00_Лесной 64_Котельная/04_ГСВ/лесной ГСВ Спецификация.dwg\n"
                "Object type: DXFModel\nProperties: dxf_read_mode=repaired_group_codes",
                "cad_bim_json_502617b60ad4.md",
                0.1,
            ),
        ]
        chunks.extend(Chunk(f"tail-{idx}", f"tail-{idx}.md", 0.05) for idx in range(max(top_k - 2, 0)))
        return chunks[:top_k]


class CadAtmSourceNameBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        chunks = [
            Chunk(
                "# CAD/BIM JSON projection\nSource formats: DWG, DXF, RVT, IFC",
                "cad_bim_json_8f98ad7e9242.md",
                0.99,
            ),
            Chunk(
                "Source path: /RAG/00_Лесной 64_Котельная/АТМ/3.Лесной_64-АТМ-Р-Планы.dwg\n"
                "Import ID: e9c1e1822523",
                "cad_bim_json_e9c1e1822523.md",
                0.1,
            ),
        ]
        chunks.extend(Chunk(f"tail-{idx}", f"tail-{idx}.md", 0.05) for idx in range(max(top_k - 2, 0)))
        return chunks[:top_k]


class FirstOrdinalBackend(FakeBackend):
    async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
        self.calls.append({"question": question, "dataset_ids": dataset_ids, "top_k": top_k})
        self.doc_filters.append(doc_filter)
        return [
            SimpleNamespace(
                content=(
                    "### CAD drawn table drawn_table_3 first positions / первые три позиции\n"
                    "- position 6 / позиция 6 | name: later"
                ),
                doc_name="cad_bim_json_db1ce53f08be.md",
                score=0.99,
                metadata={
                    "chunk_ord": 3,
                    "section_heading": "CAD drawn table drawn_table_3 first positions / первые три позиции",
                },
            ),
            SimpleNamespace(
                content=(
                    "### CAD drawn table drawn_table_1 first positions / первые три позиции\n"
                    "- position 1 / позиция 1 | name: first"
                ),
                doc_name="cad_bim_json_db1ce53f08be.md",
                score=0.4,
                metadata={
                    "chunk_ord": 30,
                    "section_heading": "CAD drawn table drawn_table_1 first positions / первые три позиции",
                },
            ),
            SimpleNamespace(
                content="## Element noise",
                doc_name="cad_bim_json_db1ce53f08be.md",
                score=0.3,
                metadata={"chunk_ord": 100, "section_heading": "Element noise"},
            ),
        ][:top_k]


@pytest.mark.asyncio
async def test_resolve_dataset_ids_uses_named_filter_when_ids_missing():
    backend = FakeBackend()

    resolved = await resolve_dataset_ids(backend, None, "NTD", SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))

    assert resolved == ["ds-1", "ds-4"]


@pytest.mark.asyncio
async def test_resolve_dataset_ids_accepts_dataset_uuid_filter():
    backend = FakeBackend()

    resolved = await resolve_dataset_ids(backend, None, "ds-2", SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))

    assert resolved == ["ds-2"]


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


def test_retrieval_query_normalization_never_injects_domain_answer():
    expanded = expand_retrieval_query(
        "  список   разделов проектной документации по постановлению 87  "
    )

    assert expanded == "список разделов проектной документации по постановлению 87"
    assert "Пояснительная записка" not in expanded


def test_retrieval_query_normalization_keeps_fire_and_hvac_questions_intact():
    fire = expand_retrieval_query("В каких случаях допускается не выполнять систему дымоудаления?")
    hvac = expand_retrieval_query("Где смотреть требования к воздухообмену и расходу воздуха?")

    assert fire == "В каких случаях допускается не выполнять систему дымоудаления?"
    assert hvac == "Где смотреть требования к воздухообмену и расходу воздуха?"


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
async def test_resolve_dataset_ids_returns_empty_scope_when_no_datasets():
    backend = EmptyBackend()

    resolved = await resolve_dataset_ids(
        backend,
        None,
        None,
        SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        question="smoke",
    )

    assert resolved == []


@pytest.mark.asyncio
async def test_resolve_dataset_ids_does_not_broaden_missing_inferred_scope():
    backend = FakeBackend()
    resolution = {}

    resolved = await resolve_dataset_ids(
        backend,
        None,
        "NTD_HVAC",
        SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        resolution_trace=resolution,
        scope_source="inferred_filter",
    )

    assert resolved == []
    assert resolution == {
        "status": "blocked",
        "error_code": "dataset_scope_not_found",
        "resolved_dataset_ids": [],
        "scope_source": "inferred_filter",
    }


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_returns_empty_without_backend_call():
    backend = EmptyBackend()

    result = await retrieve_chat_chunks(
        question="smoke",
        dataset_ids=[],
        rag_backend=backend,
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks == []
    assert result.trace.mode == "blocked"
    assert result.trace.status == "blocked"
    assert result.trace.error_code == "no_datasets"
    assert result.trace.fallback_reason == "no_datasets"
    assert backend.calls == []


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_blocks_when_required_reranker_is_disabled():
    backend = FakeBackend()

    result = await retrieve_chat_chunks(
        question="q",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=False,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks == []
    assert result.trace.status == "blocked"
    assert result.trace.error_code == "reranker_disabled"
    assert backend.calls[0] == {"question": "q", "dataset_ids": ["ds-1"], "top_k": 256}


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_passes_doc_filter_to_qdrant_backend():
    backend = FakeBackend()

    result = await retrieve_chat_chunks(
        question="что в файле 02_Состав проекта.docx",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
        doc_filter=["BAI/OUT/ИОС 5.2/02_Состав проекта.docx"],
    )

    assert result.chunks
    assert backend.doc_filters[0] == ["BAI/OUT/ИОС 5.2/02_Состав проекта.docx"]
    assert "file:BAI/OUT/ИОС 5.2/02_Состав проекта.docx" in result.trace.exact_refs


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_can_use_qdrant_native_hybrid(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_BACKEND", "qdrant_native")
    backend = NativeHybridBackend()

    result = await retrieve_chat_chunks(
        question="q",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
        doc_filter=["doc.md"],
    )

    assert result.trace.mode == "qdrant_native_hybrid"
    assert result.trace.retrieval_channels == ["dense", "qdrant_sparse"]
    assert result.trace.fusion == "rrf"
    assert result.chunks[0].doc_name == "native.docx"
    assert backend.native_calls == [
        {"question": "q", "dataset_ids": ["ds-1"], "top_k": 256, "doc_filter": ["doc.md"]}
    ]
    assert backend.calls == []


def test_qdrant_native_rrf_is_the_default_hybrid_backend(monkeypatch):
    monkeypatch.delenv("RAG_HYBRID_BACKEND", raising=False)

    assert hybrid_backend() == "qdrant_native"


@pytest.mark.asyncio
async def test_native_rrf_failure_is_blocked_without_legacy_retrieval():
    backend = FailingNativeBackend()

    result = await retrieve_chat_chunks(
        question="q",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
        scope_source="explicit_dataset_ids",
    )

    assert result.chunks == []
    assert result.trace.status == "blocked"
    assert result.trace.error_code == "native_rrf_failed"
    assert result.trace.resolved_dataset_ids == ["ds-1"]
    assert result.trace.scope_source == "explicit_dataset_ids"
    assert backend.calls == []


def test_legacy_hybrid_backend_env_cannot_change_native_rrf(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_BACKEND", "sidecar_sparse")

    assert hybrid_backend() == "qdrant_native"


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

    # W2.3: реранкер переупорядочивает гибридный пул, не режет его:
    # топ — порядок реранкера (metadata._idx), хвост — исходный порядок.
    assert [c.content for c in chunks[:2]] == ["text-2", "text-0"]
    assert len(chunks) == 64  # полный видимый пул CHAT_TOP_K, без старого среза до 8
    assert backend.calls[0]["top_k"] == 64


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_reranks_two_candidate_pool_when_available():
    class TwoChunkBackend(FakeBackend):
        async def retrieve(self, question, dataset_ids=None, top_k=5, doc_filter=None):
            return [Chunk("first", "first.pdf", 0.9), Chunk("second", "second.pdf", 0.8)]

    class TwoChunkReranker:
        def __init__(self, mlx_url, mode):
            pass

        async def rerank(self, question, chunks, top_k=5):
            return [SimpleNamespace(text=chunks[1]["text"], metadata=chunks[1]["metadata"])]

    chunks = await retrieve_chat_chunks(
        question="second",
        dataset_ids=None,
        rag_backend=TwoChunkBackend(),
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=TwoChunkReranker,
        mlx_url="http://reranker",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    )

    assert chunks[0].content == "second"


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_reranker_receives_full_visible_pool():
    backend = FakeBackend()
    seen_top_k = []

    class PoolReranker:
        def __init__(self, mlx_url, mode):
            pass

        async def rerank(self, question, chunks, top_k=5):
            seen_top_k.append(top_k)
            return [SimpleNamespace(text=chunks[3]["text"], metadata=chunks[3]["metadata"])]

    chunks = await retrieve_chat_chunks(
        question="q",
        dataset_ids=None,
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=PoolReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
    )

    assert seen_top_k == [64]
    assert chunks[0].content == "text-3"


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_blocks_on_embedding_contract_mismatch(monkeypatch, tmp_path):
    db_path = tmp_path / "lex.db"
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    monkeypatch.setenv("RAG_HYBRID_BACKEND", "lexical")
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

    result = await retrieve_chat_chunks(
        question="ширина путей эвакуации по СП 1.13130",
        dataset_ids=["ds-1"],
        rag_backend=ContractMismatchBackend(),
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks == []
    assert result.trace.mode == "blocked"
    assert result.trace.status == "blocked"
    assert result.trace.error_code == "embedding_contract_mismatch"
    assert result.trace.fallback_reason == "embedding_contract_mismatch"
    assert "expected=qwen3-embedding-0.6b" in result.trace.embedding_contract
    assert result.trace.query_embedding == "raw-v1"
    assert result.quality.status == "blocked"


@pytest.mark.asyncio
async def test_retrieval_trace_records_opt_in_qwen_query_contract(monkeypatch):
    monkeypatch.setenv("LES_EMBED_PROFILE", "qwen")
    monkeypatch.setenv("RAG_QUERY_EMBEDDING_MODE", "qwen-retrieval-v1")
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")

    result = await retrieve_chat_chunks(
        question="Какие документы есть?",
        dataset_ids=["ds-1"],
        rag_backend=FakeBackend(),
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.trace.query_embedding == "qwen-retrieval-v1"
    assert result.trace.payload()["query_embedding"] == "qwen-retrieval-v1"


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

    # W2.3: семафор держит только LLM-реранкер (cls.__name__ == "Reranker");
    # cross-encoder и прочие — нет (Metal не занят). Порядок: топ от реранкера, хвост исходный.
    assert chunks[0].content == "text-0"
    assert len(chunks) == 64
    assert budget.entered is False


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_blocks_on_reranker_error():
    backend = FakeBackend()

    result = await retrieve_chat_chunks(
        question="q",
        dataset_ids=None,
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FailingReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks == []
    assert result.trace.status == "blocked"
    assert result.trace.error_code == "reranker_failed"


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_promotes_exact_source_after_rerank(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")
    backend = ExactSourceBackend()

    result = await retrieve_chat_chunks(
        question="cad_bim_json_db1941fd7ee6.md",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks[0].doc_name == "cad_bim_json_db1941fd7ee6.md"
    assert "source_exact" in result.trace.mode
    assert "source:cad_bim_json_db1941fd7ee6.md" in result.trace.exact_refs


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_promotes_exact_identifier_after_rerank(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")
    backend = ExactIdentifierBackend()

    result = await retrieve_chat_chunks(
        question="LES-SMOKE-B454-VALVE-731",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks[0].doc_name == "drawing.pdf"
    assert "identifier_exact_guard" in result.trace.mode
    assert "identifier:les-smoke-b454-valve-731" in result.trace.exact_refs


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_promotes_explicit_norm_document_over_citations(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")
    backend = ExactNormBackend()

    result = await retrieve_chat_chunks(
        question="Найди пункт 7.3 в СП 7.13130",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks[0].doc_name == "СП 7.13130.docx"
    assert "norm_ref_exact" in result.trace.mode
    assert "сп 7.13130" in result.trace.exact_refs


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_promotes_cad_source_name_after_rerank(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")
    backend = CadSourceNameBackend()

    result = await retrieve_chat_chunks(
        question="лесной ГСВ Спецификация CAD BIM",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks[0].doc_name == "cad_bim_json_502617b60ad4.md"
    assert "source_name_boost" in result.trace.mode


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_promotes_cad_source_name_with_compact_path(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")
    backend = CadAtmSourceNameBackend()

    result = await retrieve_chat_chunks(
        question="АТМ планы Лесной64 CAD BIM 3.Лесной64-АТМ-Р-Планы",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.chunks[0].doc_name == "cad_bim_json_e9c1e1822523.md"
    assert "source_name_boost" in result.trace.mode


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_promotes_earliest_first_positions_with_doc_filter(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_RETRIEVAL_ENABLED", "false")
    backend = FirstOrdinalBackend()

    result = await retrieve_chat_chunks(
        question="назови первые три позиции спецификации",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
        doc_filter=["cad_bim_json_db1ce53f08be.md"],
    )

    assert "drawn_table_1 first positions" in result.chunks[0].content
    reranked = rank_chunks_for_question(
        "первые три позиции из таблицы спецификации ГСВ",
        list(result.chunks),
    )
    assert "drawn_table_1 first positions" in reranked[0].content
    assert "first_ordinal_guard" in result.trace.mode


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
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.trace.mode.startswith("qdrant_native_hybrid")
    assert result.trace.lexical_count == 1
    assert result.payload()["quality"]["status"] == "good"
    assert any(chunk.doc_name == "СП 1.13130.docx" for chunk in result.chunks)


@pytest.mark.asyncio
async def test_retrieve_chat_chunks_uses_lexical_with_minor_stale_drift(monkeypatch, tmp_path):
    db_path = tmp_path / "lex.db"
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(db_path))
    index = LexicalIndex(str(db_path))
    rows = [
        {
            "point_id": f"lex-{idx}",
            "dataset_id": "ds-1",
            "doc_id": f"doc-{idx}",
            "doc_name": "СП 4.13130.docx" if idx == 0 else f"doc-{idx}.docx",
            "text": "проезды пожарных автомобилей" if idx == 0 else f"other text {idx}",
        }
        for idx in range(99)
    ]
    index.upsert_chunks("test_collection", rows)
    index.mark_collection("test_collection", point_count=100, indexed_count=100)
    backend = FakeBackend()

    result = await retrieve_chat_chunks(
        question="проезды пожарных автомобилей по СП 4.13130",
        dataset_ids=["ds-1"],
        rag_backend=backend,
        reranker_enabled=True,
        reranker_available=True,
        reranker_cls=FakeReranker,
        mlx_url="http://mlx",
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        return_trace=True,
    )

    assert result.trace.mode.startswith("qdrant_native_hybrid")
    assert result.trace.lexical_count >= 1
    assert any(chunk.doc_name == "СП 4.13130.docx" for chunk in result.chunks)
