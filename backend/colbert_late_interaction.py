"""BGE-M3 late-interaction primitives used after native RRF.

The module is deliberately lazy: importing LES never loads Torch or a model.
Synthetic tests can inject token vectors, while Legion uses FlagEmbedding from
the ``windows-reranker`` extra. Navigation summaries are never accepted here;
only evidence point ids may be reranked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable


COLBERT_VECTOR_NAME = "colbert"
COLBERT_SCHEMA = "les.rag.colbert.bge-m3.v1"


class ColbertError(RuntimeError):
    pass


def _rows(value: Any) -> list[list[float]]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list) or not value:
        raise ColbertError("COLBERT_VECTOR_EMPTY")
    rows = [[float(component) for component in row] for row in value]
    dimension = len(rows[0])
    if dimension < 1 or any(len(row) != dimension for row in rows):
        raise ColbertError("COLBERT_VECTOR_DIMENSION_MISMATCH")
    return rows


def maxsim_score(query_vectors: Any, passage_vectors: Any) -> float:
    """ColBERT MaxSim: sum over query tokens of the best passage-token dot product."""
    query = _rows(query_vectors)
    passage = _rows(passage_vectors)
    if len(query[0]) != len(passage[0]):
        raise ColbertError("COLBERT_VECTOR_DIMENSION_MISMATCH")
    return sum(max(sum(a * b for a, b in zip(q, p)) for p in passage) for q in query)


def rerank_token_vectors(
    query_vectors: Any,
    candidates: Iterable[tuple[str, Any]],
    *,
    top_k: int,
) -> list[tuple[str, float]]:
    scored = [(str(point_id), maxsim_score(query_vectors, vectors)) for point_id, vectors in candidates]
    return sorted(scored, key=lambda item: (-item[1], item[0]))[: max(1, int(top_k))]


class BgeM3ColbertEncoder:
    """Lazy official BGE-M3 ColBERT encoder."""

    def __init__(self, model_name: str = "BAAI/bge-m3", *, use_fp16: bool = True):
        if model_name != "BAAI/bge-m3":
            raise ColbertError("COLBERT_MODEL_UNSUPPORTED")
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as exc:
                raise ColbertError("COLBERT_DEPENDENCY_MISSING: install windows-reranker extra") from exc
            self._model = BGEM3FlagModel(self.model_name, use_fp16=self.use_fp16)
        return self._model

    def encode(self, texts: list[str], *, max_length: int) -> list[list[list[float]]]:
        if not texts:
            return []
        result = self._load().encode(
            texts,
            batch_size=min(8, len(texts)),
            max_length=max(8, int(max_length)),
            return_dense=False,
            return_sparse=False,
            return_colbert_vecs=True,
        )
        vectors = result.get("colbert_vecs") if isinstance(result, dict) else None
        if vectors is None or len(vectors) != len(texts):
            raise ColbertError("COLBERT_ENCODER_CONTRACT_INVALID")
        return [_rows(vector) for vector in vectors]


@dataclass
class CircuitBreaker:
    failure_limit: int = 3
    cooldown_sec: int = 300
    failures: int = 0
    opened_at: float = 0.0

    def allow(self, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        if not self.opened_at:
            return True
        if current - self.opened_at >= self.cooldown_sec:
            self.failures = 0
            self.opened_at = 0.0
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = 0.0

    def failure(self, *, now: float | None = None) -> None:
        self.failures += 1
        if self.failures >= max(1, self.failure_limit):
            self.opened_at = time.monotonic() if now is None else now
