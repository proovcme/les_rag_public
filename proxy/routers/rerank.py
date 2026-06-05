"""Direct reranker route."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from proxy.security import require_admin
from proxy.services.resource_governor import chat_generation_allowed

try:
    from backend.reranker import Reranker

    RERANKER_AVAILABLE = True
except ImportError:
    Reranker = None
    RERANKER_AVAILABLE = False

router = APIRouter(prefix="/api", tags=["rerank"])


@dataclass
class RerankRouterState:
    llm_semaphore: Any
    current_mode: dict[str, Any] | None = None


_state: RerankRouterState | None = None


def set_rerank_state(state: RerankRouterState) -> None:
    global _state
    _state = state


@router.post("/rerank")
async def rerank_direct(request: Request, _admin=Depends(require_admin)):
    """
    Direct reranker call.
    Body: {"query": str, "chunks": [{"text": str, "score": float, "metadata": dict}], "top_k": int}
    """
    if not RERANKER_AVAILABLE:
        raise HTTPException(503, "reranker недоступен")
    body = await request.json()
    query = body.get("query", "")
    chunks = body.get("chunks", [])
    top_k = body.get("top_k", 5)

    if not query or not chunks:
        raise HTTPException(400, "query и chunks обязательны")

    state = _state
    if state is not None:
        allowed, resource_reason = chat_generation_allowed(state.current_mode)
        if not allowed:
            raise HTTPException(status_code=409, detail=resource_reason)

    mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")
    reranker = Reranker(mlx_url=mlx_url)
    if state is None:
        ranked = await reranker.rerank(query, chunks, top_k=top_k)
    else:
        async with state.llm_semaphore:
            ranked = await reranker.rerank(query, chunks, top_k=top_k)

    return {
        "ranked": [
            {
                "text": r.text,
                "score": r.score,
                "original_score": r.original_score,
                "rank": r.rank,
                "metadata": r.metadata,
            }
            for r in ranked
        ]
    }
