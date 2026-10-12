from types import SimpleNamespace

import pytest

from proxy.services.model_research_tool_service import ModelResearchToolService


def test_model_rag_failure_preserves_search_boundary_without_query_or_raw_trace():
    from proxy.services.model_research_tool_service import model_rag_failure_detail
    rows = [
        {'status': 'ok'},
        {'status': 'missing', 'operation': 'smeta_norm_native_rrf',
         'inputs': [{'q': 'original model query'}],
         'trace': {'rag': {'status': 'ok', 'collection': 'les_smeta_norm_cards'}}},
        {'status': 'blocked', 'operation': 'native_rrf',
         'trace': {'error_code': 'RAG_NOT_READY', 'reason': 'generation_coverage_incomplete',
                   'collection': 'les_rag', 'exception': 'password=secret'}},
    ]
    detail = model_rag_failure_detail(rows)
    assert detail['code'] == 'MODEL_RAG_SEARCH_INCOMPLETE'
    # До 17.09 выполненный поиск без совпадений (строка 2) тоже считался отказом прохода.
    # Аудит Codex P2: это ответ базы, он уходит модели как пустая выдача; остановкой
    # остаётся только технический отказ (строка 3). См. test_model_rag_empty_search.
    assert detail['blocked_queries'] == [3]
    assert detail['query_failures'][0]['error_code'] == 'RAG_NOT_READY'
    assert 'secret' not in str(detail) and 'original model query' not in str(detail)
    assert model_rag_failure_detail([{'status': 'ok'}]) is None


def test_failed_tool_guard_ignores_call_id_but_allows_changed_args_and_success():
    from proxy.services.model_research_tool_service import FailedToolCallGuard
    guard = FailedToolCallGuard()
    call = {"call_id": "one", "tool": "dataset_map", "args": {"dataset_id": "d", "depth": "deep"}}
    assert not guard.repeated(call)
    guard.record(call, {"status": "error", "warnings": ["TOOL_RESULT_BUDGET_EXCEEDED"]})
    assert guard.repeated({"call_id": "two", "tool": "dataset_map", "args": {"depth": "deep", "dataset_id": "d"}})
    changed = {"tool": "dataset_map", "args": {"dataset_id": "d", "depth": "shallow"}}
    assert not guard.repeated(changed)
    guard.record(changed, {"status": "ok"})
    assert not guard.repeated(changed)
    assert not FailedToolCallGuard().repeated(call)


class _Retrieval:
    def __init__(self):
        self.chunks = [
            SimpleNamespace(
                content="Точный фрагмент",
                doc_name="Письмо.pdf",
                score=0.73,
                meta={
                    "dataset_id": "selected-a",
                    "chunk_id": "chunk-7",
                    "page": 4,
                    "rrf_score": 0.031,
                    "retrieval_channels": ["dense", "bm25_sparse"],
                },
            )
        ]

    def payload(self):
        return {
            "schema": "retrieval_trace_v1",
            "fusion": "native_rrf",
            "retrieval_channels": ["dense", "bm25_sparse"],
        }


@pytest.mark.asyncio
async def test_search_sources_uses_canonical_retriever_and_frozen_scope():
    calls = []

    async def retrieve(**kwargs):
        calls.append(kwargs)
        return _Retrieval()

    service = ModelResearchToolService(
        retrieve=retrieve,
        frozen_dataset_ids=("selected-a", "selected-b"),
        retrieval_kwargs={"rag_backend": "backend", "return_trace": True},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        retrieval_candidate_k=64,
        document_diversity_k=2,
        model_evidence_k=4,
    )

    result = await service.execute(
        {
            "tool": "search_sources",
            "args": {"q": "котёл", "dataset_ids": ["foreign-dataset"]},
        }
    )

    assert calls == [
        {
            "question": "котёл",
            "dataset_ids": ["selected-a", "selected-b"],
            "rag_backend": "backend",
            "return_trace": True,
            "result_limit": 4,
            "candidate_limit": 64,
            "document_diversity_k": 2,
        }
    ]
    assert result.chunks == tuple(_Retrieval().chunks)
    assert result.payload["trace"]["fusion"] == "native_rrf"
    assert result.payload["result"]["hits"][0]["content"] == "Точный фрагмент"


@pytest.mark.asyncio
async def test_search_sources_preserves_rrf_provenance_in_tool_payload():
    async def retrieve(**_kwargs):
        return _Retrieval()

    service = ModelResearchToolService(
        retrieve=retrieve,
        frozen_dataset_ids=("selected-a",),
        retrieval_kwargs={},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
    )

    result = await service.execute({"tool": "search_sources", "args": {"q": "письмо"}})
    hit = result.payload["result"]["hits"][0]

    assert hit["meta"]["chunk_id"] == "chunk-7"
    assert hit["meta"]["rrf_score"] == 0.031
    assert hit["meta"]["retrieval_channels"] == ["dense", "bm25_sparse"]
    assert result.payload["trace"]["retrieval_channels"] == ["dense", "bm25_sparse"]


@pytest.mark.asyncio
async def test_search_sources_exposes_only_configured_evidence_limit_to_the_model():
    class LargeRetrieval:
        chunks = [
            SimpleNamespace(
                content=f"Фрагмент {index}",
                doc_name="Большой корпус.pdf",
                score=1.0 / index,
                meta={"chunk_id": f"chunk-{index}"},
            )
            for index in range(1, 513)
        ]

        @staticmethod
        def payload():
            return {"schema": "retrieval_trace_v1", "fusion": "native_rrf"}

    async def retrieve(**_kwargs):
        return LargeRetrieval()

    service = ModelResearchToolService(
        retrieve=retrieve,
        frozen_dataset_ids=("selected-a",),
        retrieval_kwargs={},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        retrieval_candidate_k=64,
        document_diversity_k=2,
        model_evidence_k=4,
    )

    result = await service.execute(
        {"tool": "search_sources", "args": {"q": "точный запрос"}}
    )

    assert len(result.chunks) == 4
    assert result.payload["result"]["count"] == 4
    assert len(result.payload["result"]["hits"]) == 4


@pytest.mark.asyncio
async def test_estimator_search_uses_dedicated_smeta_rrf_and_configured_limit():
    general_calls = []
    smeta_calls = []

    async def general_retrieve(**kwargs):
        general_calls.append(kwargs)
        pytest.fail("estimator search must not read the general les_rag collection")

    def smeta_retrieve(query, *, limit):
        smeta_calls.append((query, limit))
        return {
            "backend": "typed_sqlite_fts+smeta_norm_qdrant_hybrid",
            "cards": [
                {
                    "norm_code": f"ГЭСНм08-02-001-{index:02d}",
                    "title": f"Карточка {index}",
                    "measure_unit": "100 м",
                    "work_steps": ["Монтаж", "Проверка"],
                    "source_ref": f"fsnb#norm={index}",
                }
                for index in range(1, 9)
            ],
            "retrieval_trace": {
                "rag": {
                    "status": "ok",
                    "collection": "customer_configured_smeta_cards",
                    "retrieval_channels": ["dense", "bm25_sparse"],
                    "fusion": "rrf",
                }
            },
        }

    service = ModelResearchToolService(
        retrieve=general_retrieve,
        frozen_dataset_ids=("smeta-system-dataset",),
        retrieval_kwargs={"rag_backend": "les_rag"},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=smeta_retrieve,
        model_evidence_k=4,
    )

    result = await service.execute(
        {"tool": "search_sources", "args": {"q": "монтаж контрольного кабеля"}}
    )

    assert general_calls == []
    assert smeta_calls == [("монтаж контрольного кабеля", 4)]
    assert len(result.chunks) == 4
    assert len(result.payload["result"]["hits"]) == 4
    assert result.payload["trace"]["rag"]["collection"] == "customer_configured_smeta_cards"
    assert result.payload["result"]["hits"][0]["meta"]["norm_code"] == "ГЭСНм08-02-001-01"
    assert "Состав работы: Монтаж; Проверка" in result.payload["result"]["hits"][0]["content"]


@pytest.mark.asyncio
async def test_smeta_trace_does_not_claim_user_dataset_filter_was_applied_to_norms():
    calls = []
    def norm_retrieve(query, *, limit):
        calls.append((query, limit))
        return {'cards': [], 'retrieval_trace': {
            'filters': {'base_types': ['explicit-family'], 'collections': []},
            'rag': {'status': 'ok', 'collection': 'dedicated-generation'}}}
    service = ModelResearchToolService(
        retrieve=lambda **kwargs: pytest.fail('No general search expected'),
        frozen_dataset_ids=('selected-user-archive', 'selected-normative-reference'),
        retrieval_kwargs={}, fallback=lambda *args: pytest.fail('No fallback expected'),
        smeta_norm_retrieve=norm_retrieve, model_evidence_k=6)
    result = await service.execute({'tool': 'search_sources', 'args': {'q': 'literal query'}})
    assert calls == [('literal query', 6)]
    assert result.payload['status'] == 'missing'
    routing = result.retrieval_trace['scope_routing']
    assert routing['user_rag']['dataset_ids'] == ['selected-user-archive', 'selected-normative-reference']
    assert routing['user_rag']['applied_to_normative'] is False
    assert routing['normative']['collection'] == 'dedicated-generation'
    assert routing['normative']['filters'] == {'base_types': ['explicit-family'], 'collections': []}
    assert routing['practice']['user_dataset_filter_applied'] is False
    assert result.payload['trace']['scope_routing'] == routing


@pytest.mark.asyncio
async def test_estimator_search_never_falls_back_when_dedicated_rrf_is_not_ready():
    async def general_retrieve(**_kwargs):
        pytest.fail("blocked smeta RRF must not fall back to mixed les_rag")

    service = ModelResearchToolService(
        retrieve=general_retrieve,
        frozen_dataset_ids=("smeta-system-dataset",),
        retrieval_kwargs={"rag_backend": "les_rag"},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=lambda _query, *, limit: {
            "cards": [{"norm_code": "ГЭСН01-01-001-01", "title": "Лексический шум"}],
            "retrieval_trace": {
                "rag": {
                    "status": "degraded_sparse_only",
                    "collection": "les_smeta_norm_cards",
                }
            },
        },
    )

    result = await service.execute(
        {"tool": "search_sources", "args": {"q": "разработка грунта"}}
    )

    assert result.chunks == ()
    assert result.payload["status"] == "blocked"
    assert result.payload["result"]["hits"] == []
    assert result.payload["missing"] == ["dedicated smeta native RRF is not ready"]


@pytest.mark.asyncio
async def test_non_search_tool_delegates_unchanged():
    delegated = []
    payload = {"schema": "les_tool_result_v1", "tool": "read_source", "result": {"x": 1}}

    async def fallback(tool, args):
        delegated.append((tool, args))
        return payload

    service = ModelResearchToolService(
        retrieve=lambda **_kwargs: pytest.fail("retriever must not run"),
        frozen_dataset_ids=("selected-a",),
        retrieval_kwargs={},
        fallback=fallback,
    )

    result = await service.execute({"tool": "read_source", "args": {"doc_id": "d1"}})

    assert delegated == [("read_source", {"doc_id": "d1"})]
    assert result.payload is payload
    assert result.chunks == ()


def test_failed_tool_call_guard_reports_calls_for_the_prompt():
    """Модель должна видеть, какие вызовы уже неуспешны, иначе повторяет их."""
    from proxy.services.model_research_tool_service import FailedToolCallGuard

    guard = FailedToolCallGuard()
    assert guard.failed_summary() == ()

    call = {"tool": "dataset_map", "args": {"dataset_id": "x", "depth": "deep"}}
    guard.record(call, {"status": "error"})
    guard.record({"tool": "search_sources", "args": {"q": "вентиляция"}}, {"status": "ok"})

    summary = guard.failed_summary()
    assert len(summary) == 1
    assert summary[0]["tool"] == "dataset_map"
    assert summary[0]["args"] == {"dataset_id": "x", "depth": "deep"}
    # Успешный вызов в сводку не попадает.
    assert all(item["tool"] != "search_sources" for item in summary)
