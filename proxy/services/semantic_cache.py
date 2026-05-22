"""Semantic answer cache for verified SafeRAG responses."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


_WS_RE = re.compile(r"\s+")


@dataclass
class SemanticCacheHit:
    answer: str
    sources: list[str]
    similarity: float


def semantic_cache_enabled() -> bool:
    return os.getenv("SEMANTIC_CACHE_ENABLED", "true").lower() == "true"


def semantic_cache_threshold() -> float:
    try:
        return float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.94"))
    except ValueError:
        return 0.94


def normalize_question(question: str) -> str:
    return _WS_RE.sub(" ", question.strip().lower())


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def dataset_scope_key(datasets: list[Any], dataset_ids: Optional[list[str]]) -> str:
    selected = set(dataset_ids or [])
    items = []
    for dataset in datasets:
        dataset_id = getattr(dataset, "id", "")
        if selected and dataset_id not in selected:
            continue
        items.append({
            "id": dataset_id,
            "name": getattr(dataset, "name", ""),
            "status": getattr(dataset, "status", ""),
            "chunks": getattr(dataset, "chunk_count", 0) or 0,
        })
    items.sort(key=lambda item: item["id"])
    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def backend_can_embed(rag_backend: Any) -> bool:
    embed = getattr(rag_backend, "embed", None)
    return callable(getattr(embed, "encode_async", None))


async def embed_question(rag_backend: Any, question: str) -> Optional[list[float]]:
    if not backend_can_embed(rag_backend):
        return None
    vectors = await rag_backend.embed.encode_async([question])
    return vectors[0] if vectors else None


class SemanticCache:
    def __init__(self, db_path: str = "./data/les_meta.db"):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semantic_answer_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_question TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                crag_status TEXT NOT NULL,
                created_at REAL NOT NULL,
                hit_count INTEGER DEFAULT 0,
                last_hit_at REAL DEFAULT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_semantic_cache_scope "
            "ON semantic_answer_cache(scope_key, crag_status, created_at)"
        )
        return conn

    def lookup(
        self,
        question: str,
        scope_key: str,
        query_embedding: list[float],
        threshold: float,
        limit: int = 500,
    ) -> Optional[SemanticCacheHit]:
        normalized = normalize_question(question)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, normalized_question, embedding_json, answer, sources_json
                FROM semantic_answer_cache
                WHERE scope_key=? AND crag_status='VERIFIED'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (scope_key, limit),
            ).fetchall()

            best = None
            best_similarity = 0.0
            for row in rows:
                try:
                    embedding = json.loads(row[2])
                except Exception:
                    continue
                similarity = 1.0 if row[1] == normalized else cosine_similarity(query_embedding, embedding)
                if similarity > best_similarity:
                    best = row
                    best_similarity = similarity

            if not best or best_similarity < threshold:
                return None

            now = time.time()
            conn.execute(
                "UPDATE semantic_answer_cache SET hit_count=hit_count+1, last_hit_at=? WHERE id=?",
                (now, best[0]),
            )
            try:
                sources = json.loads(best[4])
            except Exception:
                sources = []
            return SemanticCacheHit(answer=best[3], sources=sources, similarity=best_similarity)

    def store(
        self,
        question: str,
        scope_key: str,
        query_embedding: list[float],
        answer: str,
        sources: list[str],
        crag_status: str,
    ) -> None:
        if crag_status != "VERIFIED":
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO semantic_answer_cache
                (normalized_question, scope_key, embedding_json, answer, sources_json, crag_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalize_question(question),
                    scope_key,
                    json.dumps(query_embedding, separators=(",", ":")),
                    answer,
                    json.dumps(sources, ensure_ascii=False),
                    crag_status,
                    time.time(),
                ),
            )
