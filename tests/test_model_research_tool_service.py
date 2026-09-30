from types import SimpleNamespace

import pytest

from proxy.services.model_research_tool_service import ModelResearchToolService


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
    assert [chunk.content for chunk in result.chunks] == [
        chunk.content for chunk in _Retrieval().chunks
    ]
    # Only one key may be added to a served card's meta: the pool size the search
    # matched.  Everything the RRF proved about the card still arrives unchanged.
    assert result.chunks[0].meta == {
        **_Retrieval().chunks[0].meta,
        "matched_before_cap": 1,
    }
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
    # Blocker § 2: the cap is what the model may see, not what was found.  A
    # measurement that counted this list would report found = 4 for every query.
    assert result.payload["result"]["matched_before_cap"] == 512
    assert result.payload["result"]["evidence_cap"] == 4
    assert result.chunks[0].meta["matched_before_cap"] == 512


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
    # Eight cards matched, four may reach the model: the fifth number is the one
    # the reader must never take for «найдено».
    assert result.payload["result"]["matched_before_cap"] == 8
    assert result.chunks[0].meta["matched_before_cap"] == 8
    assert result.payload["trace"]["rag"]["collection"] == "customer_configured_smeta_cards"
    assert result.payload["result"]["hits"][0]["meta"]["norm_code"] == "ГЭСНм08-02-001-01"
    assert "Состав работы: Монтаж; Проверка" in result.payload["result"]["hits"][0]["content"]


@pytest.mark.asyncio
async def test_estimator_search_reports_the_fused_pool_not_the_trimmed_cards():
    """The norm browser already measures its own pool (``fusion_candidates``).

    Blocker § 2 asks for найдено and показано as two numbers, so the search has to
    carry that pool out of the tool instead of dropping it at the cap: 23 cards
    were fused, 6 verified ones pass the provenance filter, 4 reach the model.
    """

    async def general_retrieve(**_kwargs):
        pytest.fail("smeta search must not read the general les_rag collection")

    service = ModelResearchToolService(
        retrieve=general_retrieve,
        frozen_dataset_ids=("smeta-system-dataset",),
        retrieval_kwargs={},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=lambda _query, *, limit: {
            "cards": [
                {
                    "norm_code": f"ГЭСН01-01-00{index}-01",
                    "title": f"Карточка {index}",
                    "source_ref": f"ФСНБ-2022#guid={index}",
                }
                for index in range(1, 7)
            ],
            "retrieval_trace": {
                "fusion_candidates": 23,
                "returned_candidates": 6,
                "rag": {"status": "ok"},
            },
        },
        model_evidence_k=4,
    )

    result = await service.execute(
        {"tool": "search_sources", "args": {"q": "монтаж перегородок"}}
    )

    assert len(result.chunks) == 4
    assert result.payload["result"]["count"] == 4
    assert result.payload["result"]["matched_before_cap"] == 23
    assert result.payload["result"]["verified_before_cap"] == 6


@pytest.mark.asyncio
async def test_estimator_card_keeps_source_resource_evidence_without_inventing_composition():
    card = {
        "norm_code": "ГЭСНм99-01-001-01",
        "norm_key": "norm-key",
        "title": "Монтаж оборудования",
        "measure_unit": "шт",
        "edition": "2022",
        "base_type": "ГЭСНм",
        "source_ref": "ФСНБ-2022#guid=norm-key",
        "work_steps": [],
        "resource_count": 23,
        "resource_kinds": {"machine": 2, "material": 20, "labor": 1},
        "resource_preview": [
            {"kind": "machine", "code": "91.01.01-001", "name": "Кран", "unit": "маш.-ч"},
            {"kind": "material", "code": "01.01.01-001", "name": "Крепление", "unit": "шт"},
        ],
    }
    service = ModelResearchToolService(
        retrieve=lambda **_: pytest.fail("mixed retrieval must not run"),
        frozen_dataset_ids=("smeta",), retrieval_kwargs={},
        fallback=lambda *_: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=lambda *_args, **_kwargs: {
            "cards": [card], "retrieval_trace": {"rag": {"status": "ok"}},
        },
    )
    result = await service.execute({"tool": "search_sources", "args": {"q": "монтаж оборудования"}})
    hit = result.payload["result"]["hits"][0]
    assert "91.01.01-001" in hit["content"] and "Кран" in hit["content"]
    assert "01.01.01-001" in hit["content"] and "Крепление" in hit["content"]
    assert "маш.-ч" in hit["content"]
    assert "ФСНБ-2022#guid=norm-key" in hit["content"]
    assert "Состав работ в карточке не указан" in hit["content"]
    assert "показано 2 из 23" in hit["content"]
    for key in ("work_steps", "resource_count", "resource_kinds", "resource_preview", "edition", "base_type", "norm_key"):
        assert hit["meta"][key] == card[key]
    assert not any(key in hit["meta"] for key in ("norm_status", "composition_covers", "selected_code"))


@pytest.mark.asyncio
async def test_estimator_degraded_dense_serves_verified_cards_but_stays_honest():
    """Dense channel down but the dedicated browser produced exact/FTS cards with
    verified typed-base provenance: they reach the model, yet the search is
    reported honestly as ``degraded_sparse_only`` (never ``ok``) with the concrete
    dense reason. Never fall back to the mixed general les_rag collection."""

    async def general_retrieve(**_kwargs):
        pytest.fail("degraded smeta RRF must not fall back to mixed les_rag")

    service = ModelResearchToolService(
        retrieve=general_retrieve,
        frozen_dataset_ids=("smeta-system-dataset",),
        retrieval_kwargs={"rag_backend": "les_rag"},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=lambda _query, *, limit: {
            "cards": [
                {
                    "norm_code": "ГЭСН01-01-001-01",
                    "title": "Разработка грунта",
                    "norm_key": "gesn01-01-001-01",
                    "source_ref": "ФСНБ-2022#guid=abc",
                }
            ],
            "retrieval_trace": {
                "rag": {
                    "status": "degraded_sparse_only",
                    "collection": "les_smeta_norm_cards",
                    "dense_error": True,
                    "dense_error_detail": "Сервис поискового представления недоступен",
                    "dense_endpoint": "http://127.0.0.1:8080",
                }
            },
        },
    )

    result = await service.execute(
        {"tool": "search_sources", "args": {"q": "разработка грунта"}}
    )

    assert len(result.chunks) == 1
    assert result.payload["status"] == "degraded_sparse_only"
    assert result.payload["result"]["hits"][0]["meta"]["norm_code"] == "ГЭСН01-01-001-01"
    assert any("exact/FTS" in w for w in result.payload["warnings"])
    assert any("Сервис поискового представления недоступен" in w for w in result.payload["warnings"])


@pytest.mark.asyncio
async def test_estimator_degraded_drops_cards_without_normative_provenance():
    """A leftover non-empty card list is never accepted as success when the cards
    lack typed-base provenance: they are dropped, so the honest status is
    ``missing`` and the model is still told a decision is required."""

    async def general_retrieve(**_kwargs):
        pytest.fail("unverified smeta cards must not fall back to mixed les_rag")

    service = ModelResearchToolService(
        retrieve=general_retrieve,
        frozen_dataset_ids=("smeta-system-dataset",),
        retrieval_kwargs={"rag_backend": "les_rag"},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=lambda _query, *, limit: {
            "cards": [{"norm_code": "ГЭСН01-01-001-01", "title": "Разработка грунта"}],
            "retrieval_trace": {
                "rag": {"status": "degraded_sparse_only", "collection": "les_smeta_norm_cards"}
            },
        },
    )

    result = await service.execute(
        {"tool": "search_sources", "args": {"q": "разработка грунта"}}
    )

    assert result.chunks == ()
    assert result.payload["status"] == "missing"
    assert any("provenance" in w for w in result.payload["warnings"])


@pytest.mark.asyncio
async def test_estimator_search_blocks_when_dedicated_rrf_unusable_and_no_cards():
    """A genuine infrastructure failure (neither ok nor degraded) that produced
    no cards stays blocked; it must not fabricate evidence or read general RRF."""

    async def general_retrieve(**_kwargs):
        pytest.fail("blocked smeta RRF must not fall back to mixed les_rag")

    service = ModelResearchToolService(
        retrieve=general_retrieve,
        frozen_dataset_ids=("smeta-system-dataset",),
        retrieval_kwargs={"rag_backend": "les_rag"},
        fallback=lambda *_args: pytest.fail("fallback must not run"),
        smeta_norm_retrieve=lambda _query, *, limit: {
            "cards": [],
            "retrieval_trace": {
                "rag": {
                    "status": "unavailable",
                    "collection": "",
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
