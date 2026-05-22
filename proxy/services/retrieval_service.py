"""Retrieval strategy helpers for chat."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional


@dataclass
class RerankedStub:
    content: str
    doc_name: str


async def resolve_dataset_ids(
    rag_backend,
    dataset_ids: Optional[list[str]],
    dataset_filter: Optional[str],
    logger: logging.Logger,
) -> Optional[list[str]]:
    if dataset_filter and not dataset_ids:
        try:
            ds_list = await rag_backend.list_datasets()
            target_name = f"{dataset_filter}_Index"
            ds_match = next((dataset for dataset in ds_list if dataset.name == target_name), None)
            if ds_match:
                logger.info("[CHAT] dataset_filter='%s' -> id=%s", dataset_filter, ds_match.id)
                return [ds_match.id]
            logger.warning("[CHAT] dataset_filter='%s' not found", dataset_filter)
        except Exception as e:
            logger.warning("[CHAT] dataset_filter resolve error: %s", e)
    return dataset_ids


async def retrieve_chat_chunks(
    *,
    question: str,
    dataset_ids: Optional[list[str]],
    rag_backend,
    reranker_enabled: bool,
    reranker_available: bool,
    reranker_cls,
    mlx_url: str,
    logger: logging.Logger,
):
    if reranker_available and reranker_enabled:
        raw_chunks = await rag_backend.retrieve(question, dataset_ids=dataset_ids, top_k=8)
        if raw_chunks and len(raw_chunks) > 5:
            try:
                reranker = reranker_cls(mlx_url=mlx_url, mode="batch")
                rerank_input = [
                    {
                        "text": chunk.content,
                        "metadata": {"doc_name": chunk.doc_name},
                        "score": getattr(chunk, "score", 0.0),
                    }
                    for chunk in raw_chunks
                ]
                ranked = await reranker.rerank(question, rerank_input, top_k=5)
                chunks = []
                for ranked_chunk in ranked:
                    match = next(
                        (chunk for chunk in raw_chunks if chunk.content == ranked_chunk.text),
                        None,
                    )
                    if match:
                        chunks.append(match)
                    else:
                        chunks.append(
                            RerankedStub(
                                content=ranked_chunk.text,
                                doc_name=ranked_chunk.metadata.get("doc_name", "?"),
                            )
                        )
                logger.info("[RERANKER] %s -> %s чанков", len(raw_chunks), len(chunks))
                return chunks
            except Exception as rerank_error:
                logger.warning("[RERANKER] Ошибка, fallback: %s", rerank_error)
                return raw_chunks[:5]
        return raw_chunks

    return await rag_backend.retrieve(question, dataset_ids=dataset_ids, top_k=5)
