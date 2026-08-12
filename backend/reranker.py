from __future__ import annotations
"""
С.А.М.О.В.А.Р. // reranker.py
==============================
Реранкер на базе Qwen3-4B (cross-encoder режим).

Схема работы:
    Запрос → bge-m3 → Qdrant top-20 (грубо, по векторам)
                            ↓
                    Qwen3-4B оценивает каждую пару (запрос, чанк) → score 0-10
                            ↓
                    Сортируем → берём top-K (обычно 5)
                            ↓
                    Генерация ответа Qwen3-14B

Подключение:
    reranker = Reranker(mlx_url="http://127.0.0.1:8080")
    reranked = await reranker.rerank(query, chunks, top_k=5)

Интеграция в qdrant_adapter.py:
    chunks = await adapter.retrieve(query, top_k=20)          # грубо
    chunks = await reranker.rerank(query, chunks, top_k=5)    # точно

Зависимости: только httpx (уже есть в проекте)
"""

import asyncio
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Optional

from backend.http_client_policy import trust_env_for_url

logger = logging.getLogger("les.reranker")

# ─────────────────────────────────────────
# ПРОМПТ ДЛЯ CROSS-ENCODER
# ─────────────────────────────────────────

RERANK_PROMPT = """Оцени релевантность фрагмента документа для ответа на вопрос.

Вопрос: {query}

Фрагмент [{idx}]:
{chunk_text}

Оцени по шкале 0-10:
- 10: Фрагмент напрямую и полностью отвечает на вопрос
- 7-9: Фрагмент содержит важную релевантную информацию
- 4-6: Фрагмент частично связан с вопросом
- 1-3: Фрагмент слабо связан, косвенное отношение
- 0: Фрагмент не связан с вопросом

Отвечай ТОЛЬКО числом от 0 до 10. Без пояснений."""

RERANK_BATCH_PROMPT = """Оцени релевантность каждого фрагмента для ответа на вопрос.
Отвечай ТОЛЬКО JSON-массивом чисел (индекс → оценка 0-10).

Вопрос: {query}

Фрагменты:
{chunks_text}

Формат ответа: [8, 3, 9, 1, 6, ...]
Ровно {n} чисел в массиве."""


# ─────────────────────────────────────────
# DATACLASS
# ─────────────────────────────────────────

@dataclass
class RankedChunk:
    text: str
    score: float          # оценка реранкера 0-10
    original_score: float # исходный score из Qdrant (косинусное сходство)
    metadata: dict
    rank: int             # итоговое место после реранкинга


# ─────────────────────────────────────────
# РЕРАНКЕР
# ─────────────────────────────────────────

class Reranker:
    """
    Cross-encoder реранкер через Qwen3-4B на MLX Host.

    Два режима:
    - batch: один запрос с N фрагментами, LLM возвращает N оценок (быстрее)
    - sequential: N отдельных запросов (надёжнее, медленнее)

    При большом числе чанков (>10) batch может путаться → используем sequential.
    """

    def __init__(
        self,
        mlx_url: str = "http://127.0.0.1:8080",
        model: str = "",
        mode: str = "sequential",    # "batch" или "sequential"
        timeout: float = 30.0,
        max_chunk_len: int = 800,    # обрезаем длинные чанки для скорости
    ):
        self.mlx_url = mlx_url.rstrip("/")
        self.model = (
            model
            or os.getenv("RERANK_MODEL", "").strip()
            or os.getenv("OLLAMA_MODEL", "").strip()
            or os.getenv("LLM_MODEL", "").strip()
            or "mlx-community/Qwen3-4B-4bit"
        )
        self.mode = mode
        self.timeout = timeout
        self.max_chunk_len = max_chunk_len

    async def rerank(
        self,
        query: str,
        chunks: list,   # list[dict] с полями "text", "metadata", "score" (опц.)
        top_k: int = 5,
    ) -> list:
        """
        Переранжирует чанки по релевантности к запросу.
        Возвращает list[RankedChunk] длиной top_k.

        chunks ожидается в формате:
          [{"text": str, "metadata": dict, "score": float}, ...]
        """
        if not chunks:
            return []

        if len(chunks) == 1:
            return [
                RankedChunk(
                    text=c.get("text", ""),
                    score=10.0,
                    original_score=c.get("score", 0.0),
                    metadata=c.get("metadata", {}),
                    rank=i + 1,
                )
                for i, c in enumerate(chunks)
            ]

        logger.info(f"[RERANKER] Режим={self.mode}, чанков={len(chunks)}, top_k={top_k}")

        if self.mode == "batch" and len(chunks) <= 10:
            scores = await self._score_batch(query, chunks)
        else:
            scores = await self._score_sequential(query, chunks)

        # Сортируем по score (убывание)
        scored = list(zip(scores, chunks))
        scored.sort(key=lambda x: x[0], reverse=True)

        result = []
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1):
            result.append(RankedChunk(
                text=chunk.get("text", ""),
                score=score,
                original_score=chunk.get("score", 0.0),
                metadata=chunk.get("metadata", {}),
                rank=rank,
            ))

        logger.info(
            f"[RERANKER] Топ-{top_k} scores: {[round(r.score, 1) for r in result]}"
        )
        return result

    def _truncate(self, text: str) -> str:
        if len(text) > self.max_chunk_len:
            return text[:self.max_chunk_len] + "…"
        return text

    async def _call_llm(self, prompt: str) -> str:
        """Вызывает Qwen3-4B через /v1/chat/completions."""
        import httpx
        # /no_think отключает thinking-mode Qwen3 (hard switch).
        # Без него модель генерирует <think>...</think> (~300 токенов),
        # который срезается при max_tokens=50 → пустой ответ → score=0.
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "/no_think\n" + prompt}],
            "max_tokens": 256,
            "temperature": 0.0,
        }
        try:
            async with httpx.AsyncClient(
                trust_env=trust_env_for_url(self.mlx_url),
                timeout=self.timeout,
            ) as client:
                r = await client.post(
                    f"{self.mlx_url}/v1/chat/completions",
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"].strip()
                # Защитный стрип на случай если think-теги всё же прошли
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
                content = re.sub(r"<think>.*",         "", content, flags=re.DOTALL)
                return content.strip() or "0"
        except Exception as e:
            logger.warning(f"[RERANKER] LLM ошибка: {e}")
            return "0"

    async def _score_single(self, query: str, chunk: dict, idx: int) -> float:
        """Оценивает один чанк. Возвращает score 0-10."""
        text = self._truncate(chunk.get("text", ""))
        prompt = RERANK_PROMPT.format(query=query, chunk_text=text, idx=idx)
        response = await self._call_llm(prompt)

        # Парсим число из ответа
        try:
            m = re.search(r"\b(\d+(?:\.\d+)?)\b", response)
            if m:
                score = float(m.group(1))
                return min(max(score, 0.0), 10.0)
        except Exception:
            pass
        return 0.0

    async def _score_sequential(self, query: str, chunks: list) -> list:
        """Оценивает чанки последовательно. Надёжно, но медленнее."""
        scores = []
        # Параллелим по 3 запроса одновременно чтобы не перегружать MLX
        semaphore = asyncio.Semaphore(3)

        async def _rate_limited(chunk, idx):
            async with semaphore:
                return await self._score_single(query, chunk, idx)

        tasks = [_rate_limited(chunk, i) for i, chunk in enumerate(chunks)]
        scores = await asyncio.gather(*tasks)
        return list(scores)

    async def _score_batch(self, query: str, chunks: list) -> list:
        """Оценивает все чанки одним запросом к LLM."""
        chunks_text = "\n\n".join(
            f"[{i}] {self._truncate(c.get('text', ''))}"
            for i, c in enumerate(chunks)
        )
        prompt = RERANK_BATCH_PROMPT.format(
            query=query,
            chunks_text=chunks_text,
            n=len(chunks),
        )
        response = await self._call_llm(prompt)

        # Парсим JSON-массив
        try:
            m = re.search(r"\[[\d\s,\.]+\]", response)
            if m:
                scores = json.loads(m.group(0))
                if len(scores) == len(chunks):
                    return [min(max(float(s), 0.0), 10.0) for s in scores]
        except Exception as e:
            logger.warning(f"[RERANKER] Batch parse error: {e}, fallback sequential")

        # Fallback на sequential
        return await self._score_sequential(query, chunks)


# ─────────────────────────────────────────
# ЭНДПОИНТ ДЛЯ MLX HOST (/api/rerank)
# ─────────────────────────────────────────
# Вставить в mlx_host.py:
#
# @app.post("/api/rerank")
# async def rerank_endpoint(request: Request):
#     body = await request.json()
#     query = body.get("query", "")
#     chunks = body.get("chunks", [])
#     top_k = body.get("top_k", 5)
#
#     reranker = Reranker(mlx_url="http://127.0.0.1:8080")
#     ranked = await reranker.rerank(query, chunks, top_k=top_k)
#     return {
#         "ranked": [
#             {"text": r.text, "score": r.score,
#              "original_score": r.original_score,
#              "rank": r.rank, "metadata": r.metadata}
#             for r in ranked
#         ]
#     }


# ─────────────────────────────────────────
# ПАТЧ ДЛЯ qdrant_adapter.py
# ─────────────────────────────────────────
# В метод retrieve() добавить параметр rerank=True:
#
# async def retrieve_with_rerank(
#     self,
#     query: str,
#     dataset_id: str = None,
#     top_k: int = 5,
#     rerank: bool = True,
#     rerank_pool: int = 20,        # сколько берём из Qdrant до реранкинга
# ) -> list:
#     # 1. Берём широкий пул из Qdrant
#     pool = await self.retrieve(query, dataset_id=dataset_id, top_k=rerank_pool)
#
#     if not rerank or len(pool) <= top_k:
#         return pool[:top_k]
#
#     # 2. Реранкинг
#     from backend.reranker import Reranker
#     reranker = Reranker()
#     ranked = await reranker.rerank(query, pool, top_k=top_k)
#
#     # 3. Возвращаем в формате совместимом с retrieve()
#     return [
#         {"text": r.text, "score": r.score / 10.0,
#          "metadata": r.metadata}
#         for r in ranked
#     ]


# ─────────────────────────────────────────
# ТЕСТ
# ─────────────────────────────────────────
class CrossEncoderReranker:
    """W2.2 (ADR-3): клиент cross-encoder реранка MLX Host /v1/rerank.

    Тот же интерфейс, что у LLM-реранкера (mlx_url/model/mode/timeout +
    .rerank(query, chunks, top_k) → list[RankedChunk]) — подключается в
    retrieval_service без правок вызывающего кода. Score — сырой логит
    cross-encoder (НЕ 0-10); сортировка корректна, абсолютная шкала иная.
    """

    def __init__(
        self,
        mlx_url: str = "http://127.0.0.1:8080",
        model: str = "",          # модель задаётся на стороне mlx_host (RERANK_MODEL)
        mode: str = "batch",      # совместимость сигнатуры; не используется
        timeout: float = 30.0,
        max_chunk_len: int = 1600,
    ):
        self.mlx_url = mlx_url.rstrip("/")
        self.model = model
        self.mode = mode
        self.timeout = timeout
        self.max_chunk_len = max_chunk_len

    async def rerank(self, query: str, chunks: list, top_k: int = 5) -> list:
        import httpx

        if not chunks:
            return []
        if len(chunks) == 1:
            return [
                RankedChunk(
                    text=c.get("text", ""),
                    score=float(c.get("score", 0.0)),
                    original_score=c.get("score", 0.0),
                    metadata=c.get("metadata", {}),
                    rank=i + 1,
                )
                for i, c in enumerate(chunks)
            ]

        documents = [str(c.get("text", ""))[: self.max_chunk_len] for c in chunks]
        async with httpx.AsyncClient(
            trust_env=trust_env_for_url(self.mlx_url),
            timeout=self.timeout,
        ) as client:
            resp = await client.post(
                f"{self.mlx_url}/v1/rerank",
                json={"query": query, "documents": documents, "top_k": top_k},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

        ranked: list[RankedChunk] = []
        for rank, item in enumerate(results[:top_k], start=1):
            idx = int(item.get("index", -1))
            if not 0 <= idx < len(chunks):
                continue
            chunk = chunks[idx]
            ranked.append(RankedChunk(
                text=chunk.get("text", ""),
                score=float(item.get("score", 0.0)),
                original_score=chunk.get("score", 0.0),
                metadata=chunk.get("metadata", {}),
                rank=rank,
            ))
        if not ranked:
            raise RuntimeError("cross-encoder rerank вернул пустой результат")
        logger.info("[RERANK-CE] %s → %s чанков", len(chunks), len(ranked))
        return ranked


def resolve_rerank_device(requested: str | None = None) -> str:
    """Resolve RERANK_DEVICE; fall back to CPU when CUDA was asked but unavailable.

    A CPU-only torch wheel with ``RERANK_DEVICE=cuda`` used to raise inside
    CrossEncoder and collapse smeta shortlists to raw RRF order. Prefer a
    working CE on CPU over a silent retrieval downgrade.
    """
    device = (requested if requested is not None else os.getenv("RERANK_DEVICE", "")).strip()
    if not device:
        return ""
    if not device.casefold().startswith("cuda"):
        return device
    try:
        import torch
    except ImportError:
        logger.warning(
            "[RERANK] RERANK_DEVICE=%s but torch is missing; falling back to cpu",
            device,
        )
        return "cpu"
    if torch.cuda.is_available():
        return device
    logger.warning(
        "[RERANK] RERANK_DEVICE=%s but torch.cuda.is_available() is False "
        "(build=%s); falling back to cpu — install a CUDA torch wheel on Windows",
        device,
        getattr(torch.version, "cuda", None),
    )
    return "cpu"


class SentenceTransformerReranker:
    """Native local cross-encoder for Windows/Linux production.

    Ollama exposes generation and embeddings but not a cross-encoder rerank
    contract. Loading the model lazily inside LES keeps the answer LLM out of
    retrieval decisions while preserving the same async reranker interface.
    """

    _models: dict[tuple[str, str], object] = {}
    _model_lock = threading.Lock()

    def __init__(
        self,
        mlx_url: str = "",
        model: str = "",
        mode: str = "batch",
        timeout: float = 60.0,
        max_chunk_len: int = 1600,
    ):
        del mlx_url, mode, timeout
        self.model = model or os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3").strip()
        self.device = resolve_rerank_device()
        configured_chunk_len = int(
            os.getenv("RERANK_MAX_TEXT_CHARS", str(max_chunk_len))
        )
        self.max_chunk_len = max(128, configured_chunk_len)
        self.batch_size = max(1, int(os.getenv("RERANK_BATCH_SIZE", "8")))

    @classmethod
    def _load_model(cls, model_name: str, device: str):
        key = (model_name, device)
        with cls._model_lock:
            loaded = cls._models.get(key)
            if loaded is not None:
                return loaded
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers reranker is not installed; "
                    "install the windows-reranker extra"
                ) from exc
            kwargs = {"device": device} if device else {}
            loaded = CrossEncoder(model_name, **kwargs)
            cls._models[key] = loaded
            return loaded

    def _score(self, query: str, chunks: list[dict]) -> list[float]:
        model = self._load_model(self.model, self.device)
        pairs = [
            (query, str(chunk.get("text") or "")[: self.max_chunk_len])
            for chunk in chunks
        ]
        raw_scores = model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [float(value) for value in raw_scores]

    async def rerank(self, query: str, chunks: list, top_k: int = 5) -> list[RankedChunk]:
        if not chunks:
            return []
        if len(chunks) == 1:
            chunk = chunks[0]
            return [
                RankedChunk(
                    text=chunk.get("text", ""),
                    score=float(chunk.get("score", 0.0)),
                    original_score=float(chunk.get("score", 0.0)),
                    metadata=chunk.get("metadata", {}),
                    rank=1,
                )
            ]
        scores = await asyncio.to_thread(self._score, query, chunks)
        if len(scores) != len(chunks):
            raise RuntimeError("cross-encoder score count does not match candidate count")
        ordered = sorted(zip(scores, chunks), key=lambda item: item[0], reverse=True)
        return [
            RankedChunk(
                text=chunk.get("text", ""),
                score=float(score_value),
                original_score=float(chunk.get("score", 0.0)),
                metadata=chunk.get("metadata", {}),
                rank=rank,
            )
            for rank, (score_value, chunk) in enumerate(ordered[:top_k], start=1)
        ]


def select_reranker_cls():
    """ADR-3: Windows production default is local sentence-transformers.

    Mac/dev may keep MLX ``cross_encoder`` (/v1/rerank). Explicit
    ``RERANKER_BACKEND`` always wins. ``llm`` remains a migration escape hatch.
    """
    import sys

    configured = os.getenv("RERANKER_BACKEND", "").strip().lower()
    if not configured:
        configured = (
            "sentence_transformers"
            if sys.platform.startswith("win")
            else "cross_encoder"
        )
    if configured == "llm":
        return Reranker
    if configured == "sentence_transformers":
        return SentenceTransformerReranker
    return CrossEncoderReranker


if __name__ == "__main__":
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    TEST_QUERY = "требования к заземлению электрооборудования"
    TEST_CHUNKS = [
        {"text": "Заземление электроустановок должно соответствовать ГОСТ Р 50571. Сопротивление заземляющего устройства не должно превышать 4 Ом.", "score": 0.85},
        {"text": "Монтаж трубопроводов систем отопления выполняется из стальных электросварных труб по ГОСТ 10704.", "score": 0.72},
        {"text": "Все металлические части электрооборудования, нормально не находящиеся под напряжением, должны быть заземлены.", "score": 0.81},
        {"text": "Ведомость рабочих чертежей: лист 1 — план первого этажа, лист 2 — разрез 1-1.", "score": 0.61},
        {"text": "Молниезащита и заземление здания: категория III, тип Б. Заземлитель — горизонтальный, полоса 40×4 мм.", "score": 0.78},
    ]

    async def _test():
        reranker = Reranker(mode="sequential")
        ranked = await reranker.rerank(TEST_QUERY, TEST_CHUNKS, top_k=3)
        print(f"\n[РЕЗУЛЬТАТ РЕРАНКИНГА]")
        print(f"Запрос: {TEST_QUERY}\n")
        for r in ranked:
            print(f"  #{r.rank} score={r.score:.1f} (было {r.original_score:.2f})")
            print(f"     {r.text[:100]}…\n")

    asyncio.run(_test())
