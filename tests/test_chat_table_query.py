import json
from types import SimpleNamespace

import pandas as pd
import pytest

from proxy.routers import chat as chat_router


class FakeBackend:
    collection_name = "test_collection"

    async def list_datasets(self):
        return [SimpleNamespace(id="ds-table", name="NTD_FIRE_Index")]


class FakeDispatcher:
    def __init__(self, **kwargs):
        pass

    def reindex_status_payload(self):
        return {"running": False}


@pytest.mark.asyncio
async def test_chat_table_query_uses_expanded_context_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    dataset_dir = tmp_path / "storage" / "datasets" / "ds-table"
    parquet_dir = dataset_dir / "_parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "source_file": "СП 3.13130 .docx",
                "name": "Гостиницы, общежития",
                "raw_row": json.dumps(
                    {
                        "Норматив": "СП 3.13130",
                        "Объект": "Гостиницы, общежития",
                        "Способ оповещения": "звуковой менее 3 500 м2; речевой 3 500 м2 и более",
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    ).to_parquet(parquet_dir / "sp.parquet", index=False)

    base_chunk = SimpleNamespace(
        content="Фрагмент около таблицы",
        doc_name="СП 3.13130 .docx",
        meta={"dataset_id": "ds-table"},
    )
    table_chunk = SimpleNamespace(
        content="Гостиницы, общежития: способ оповещения",
        doc_name="СП 3.13130 .docx",
        meta={"dataset_id": "ds-table", "parquet_path": "_parquet/sp.parquet"},
    )

    async def fake_retrieve_chat_chunks(**kwargs):
        return SimpleNamespace(
            chunks=[base_chunk],
            quality=SimpleNamespace(status="good"),
            payload=lambda: {"quality": {"status": "good"}, "merged_count": 1},
        )

    monkeypatch.setattr(chat_router, "RuntimeDispatcher", FakeDispatcher)
    monkeypatch.setattr(chat_router, "retrieve_chat_chunks", fake_retrieve_chat_chunks)
    monkeypatch.setattr(
        chat_router,
        "expand_context_windows",
        lambda *args, **kwargs: SimpleNamespace(
            chunks=[table_chunk],
            payload=lambda: {"enabled": True, "output_count": 1},
        ),
    )
    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=FakeBackend(),
            llm_semaphore=SimpleNamespace(_value=1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "chat"},
            metrics_cache={"ram_free_gb": 12.0, "swap_pct": 0.0},
        )
    )

    response = await chat_router.chat(
        chat_router.ChatRequest(
            question="покажи строки таблицы СП 3.13130 про гостиницы общежития способ оповещения",
            dataset_filter="NTD_FIRE",
            semantic_cache_enabled=False,
            validation_enabled=False,
        ),
        _user=object(),
    )

    assert response["crag_status"] == "VERIFIED"
    assert response["table_query"]["operation"] == "list"
    assert response["table_query"]["parquet_paths"] == ["_parquet/sp.parquet"]
    assert "Гостиницы, общежития" in response["answer"]
    assert "3 500 м2" in response["answer"]


@pytest.mark.asyncio
async def test_chat_table_query_can_answer_without_vector_embedding(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta_qwen.db"))
    dataset_dir = tmp_path / "storage" / "datasets" / "ds-smeta"
    parquet_dir = dataset_dir / "_parquet"
    parquet_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "source_file": "smeta.csv",
                "name": "Монтаж кабеля",
                "amount": 1200,
                "raw_row": json.dumps(
                    {"Наименование работ": "Монтаж кабеля", "Сумма": "1200"},
                    ensure_ascii=False,
                ),
            }
        ]
    ).to_parquet(parquet_dir / "smeta.parquet", index=False)

    class TableBackend:
        collection_name = "test_collection"

        async def list_datasets(self):
            return [SimpleNamespace(id="ds-smeta", name="TABLE_SMETA_Index")]

        async def retrieve_table_rows(self, dataset_ids=None, limit=64):
            raise AssertionError("table direct path should use local parquet refs first")

        async def retrieve(self, *args, **kwargs):
            raise AssertionError("table direct path should not call vector retrieval")

    monkeypatch.setattr(chat_router, "RuntimeDispatcher", FakeDispatcher)
    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=TableBackend(),
            llm_semaphore=SimpleNamespace(_value=0),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "paused"},
            metrics_cache={"ram_free_gb": 4.0, "swap_pct": 0.0},
        )
    )

    response = await chat_router.chat(
        chat_router.ChatRequest(
            question="посчитай общую стоимость по всем строкам сметы",
            semantic_cache_enabled=False,
            validation_enabled=False,
        ),
        _user=object(),
    )

    assert response["crag_status"] == "VERIFIED"
    assert response["cache"] == "deterministic_table"
    assert response["retrieval_trace"]["mode"] == "deterministic_table"
    assert response["table_query"]["total"] == 1200
