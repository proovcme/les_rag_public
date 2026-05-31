import asyncio
import logging
from proxy.app import configure_router_state
from proxy.services.retrieval_service import retrieve_chat_chunks, resolve_dataset_ids
from proxy.services.context_expander_service import expand_context_windows
from proxy.services.saferag_service import concentrate_sources, rank_chunks_for_question
from proxy.routers.datasets import get_dataset_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_llm_chunks")

async def main():
    # Configure global state
    configure_router_state()
    state = get_dataset_state()
    question = "Нужно ли тушить серверную газом и от какой площади?"
    dataset_filter = "NTD_FIRE"
    
    # 1. Resolve dataset ids
    dataset_ids = await resolve_dataset_ids(
        state.backend, None, dataset_filter, logger, question=question
    )
    
    # 2. Retrieve chunks
    retrieval = await retrieve_chat_chunks(
        question=question,
        dataset_ids=dataset_ids,
        rag_backend=state.backend,
        reranker_enabled=False,
        reranker_available=False,
        reranker_cls=None,
        mlx_url="http://127.0.0.1:8080",
        logger=logger,
        return_trace=True
    )
    chunks = retrieval.chunks
    print(f"Retrieved {len(chunks)} chunks.")
    
    # 3. Rank and concentrate
    chunks = rank_chunks_for_question(question, chunks)
    focused_chunks = concentrate_sources(
        chunks,
        max_docs=3,
        min_score=0.35,
        max_chunks=8
    )
    print(f"Focused to {len(focused_chunks)} chunks.")
    
    # 4. Context expansion
    context_windows = expand_context_windows(
        focused_chunks,
        collection=getattr(state.backend, "collection_name", ""),
        logger=logger,
        max_chunks=6,
        radius=1
    )
    
    print("\n=== FINAL LLM CONTEXT CHUNKS ===")
    for i, c in enumerate(context_windows.chunks):
        print(f"\n--- Chunk {i+1} | Doc: {c.doc_name} | Score: {c.score:.4f} ---")
        meta = getattr(c, "meta", {}) or {}
        print("Meta context_expanded:", meta.get("context_expanded"))
        print("Meta chunk_ord:", meta.get("chunk_ord"))
        print("Text snippet:", repr(c.content[:400]))

if __name__ == "__main__":
    asyncio.run(main())
