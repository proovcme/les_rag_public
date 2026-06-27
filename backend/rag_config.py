"""RAG embedding profile and Qdrant collection configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


@dataclass(frozen=True)
class EmbeddingProfile:
    name: str
    model: str
    api_model: str
    collection: str
    vector_size: int
    chunk_size: int
    chunk_overlap: int


EMBEDDING_PROFILES: dict[str, EmbeddingProfile] = {
    "legacy": EmbeddingProfile(
        name="legacy",
        model="BAAI/bge-m3",
        api_model="bge-m3",
        collection="les_rag",
        vector_size=1024,
        chunk_size=900,
        chunk_overlap=80,
    ),
    "quality": EmbeddingProfile(
        name="quality",
        model="BAAI/bge-m3",
        api_model="bge-m3",
        collection="les_rag_bge_m3",
        vector_size=1024,
        chunk_size=900,
        chunk_overlap=80,
    ),
    "qwen": EmbeddingProfile(
        name="qwen",
        model="Qwen/Qwen3-Embedding-0.6B",
        api_model="qwen3-embedding-0.6b",
        collection="les_rag_qwen3_06b",
        vector_size=1024,
        chunk_size=1550,
        chunk_overlap=70,
    ),
    "fast": EmbeddingProfile(
        name="fast",
        model="intfloat/multilingual-e5-small",
        api_model="multilingual-e5-small",
        collection="les_rag_fast",
        vector_size=384,
        chunk_size=1200,
        chunk_overlap=80,
    ),
}


def embed_profile_name() -> str:
    value = os.getenv("LES_EMBED_PROFILE", "legacy").strip().lower()
    return value if value in EMBEDDING_PROFILES else "legacy"


def embed_profile() -> EmbeddingProfile:
    return EMBEDDING_PROFILES[embed_profile_name()]


def embedding_model_id() -> str:
    if os.getenv("EMBEDDING_MODEL"):
        return os.environ["EMBEDDING_MODEL"]
    profile = embed_profile()
    if profile.name != "legacy":
        return profile.model
    return os.getenv("BGE_MODEL") or profile.model


def embedding_api_model() -> str:
    profile = embed_profile()
    if profile.name != "legacy":
        api_model = os.getenv("EMBED_MODEL", "")
        return api_model if api_model and api_model != EMBEDDING_PROFILES["legacy"].api_model else profile.api_model
    return os.getenv("EMBED_MODEL") or profile.api_model


def rag_collection_name() -> str:
    return os.getenv("RAG_COLLECTION_NAME") or embed_profile().collection


def rag_meta_db_path() -> str:
    if os.getenv("RAG_META_DB_PATH"):
        return os.environ["RAG_META_DB_PATH"]
    profile = embed_profile()
    if profile.name == "legacy":
        return "./data/les_meta.db"
    return f"./data/les_meta_{profile.name}.db"


def rag_vector_size() -> int:
    return int(os.getenv("RAG_VECTOR_SIZE", str(embed_profile().vector_size)))


def rag_chunk_size() -> int:
    return int(os.getenv("RAG_CHUNK_SIZE", str(embed_profile().chunk_size)))


def rag_chunk_overlap() -> int:
    return int(os.getenv("RAG_CHUNK_OVERLAP", str(embed_profile().chunk_overlap)))


# ── W2.1 (ADR-7): чанкинг в токенах эмбеддера ────────────────────────────────
# Размер чанка обязан помещаться в seq_len эмбеддера — иначе хвосты молча
# отбрасываются при эмбеддинге. Дефолт — токены; RAG_CHUNK_UNIT=chars вернёт
# старое поведение (символы) без реиндекса.

_token_len_fn_cache: object = None


def rag_chunk_unit() -> str:
    value = os.getenv("RAG_CHUNK_UNIT", "tokens").strip().lower()
    return value if value in ("tokens", "chars") else "tokens"


def rag_chunk_tokens() -> int:
    # 430+50 overlap = 480 — ровно в бюджет seq_len=512 минус запас на спецтокены.
    return int(os.getenv("RAG_CHUNK_TOKENS", "430"))


def rag_chunk_overlap_tokens() -> int:
    return int(os.getenv("RAG_CHUNK_OVERLAP_TOKENS", "50"))


def embed_seq_len() -> int:
    return int(os.getenv("COREML_EMBED_SEQ_LEN", "512"))


def token_length_fn():
    """Счётчик токенов токенизатором модели эмбеддингов (лениво, кэшируется).

    None — если transformers/токенизатор недоступны: вызывающий код обязан
    откатиться на символьный режим с громким предупреждением.
    """
    global _token_len_fn_cache
    if _token_len_fn_cache is not None:
        return _token_len_fn_cache if callable(_token_len_fn_cache) else None
    try:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(embedding_model_id())

        def _length(text: str) -> int:
            return len(tokenizer.encode(text, add_special_tokens=False))

        _token_len_fn_cache = _length
        return _length
    except Exception as err:  # noqa: BLE001 — любой сбой = откат на chars
        logging.getLogger(__name__).warning(
            "[CHUNK] токенизатор %s недоступен (%s) — чанкинг в символах",
            embedding_model_id(), err,
        )
        _token_len_fn_cache = False
        return None


def chunking_config() -> dict:
    """Итоговая конфигурация чанкера: unit/size/overlap/len_fn + страховка ADR-7."""
    if rag_chunk_unit() == "tokens":
        len_fn = token_length_fn()
        if len_fn is not None:
            size = rag_chunk_tokens()
            overlap = rag_chunk_overlap_tokens()
            budget = embed_seq_len() - 32  # запас на спецтокены/инструкцию модели
            if size + overlap > budget:
                logging.getLogger(__name__).critical(
                    "[CHUNK] chunk_tokens+overlap=%s выходит за seq_len=%s — клампим до %s (ADR-7)",
                    size + overlap, embed_seq_len(), budget,
                )
                size = max(64, budget - overlap)
            return {"unit": "tokens", "chunk_size": size, "chunk_overlap": overlap, "len_fn": len_fn}
    return {"unit": "chars", "chunk_size": rag_chunk_size(), "chunk_overlap": rag_chunk_overlap(), "len_fn": None}


def rag_runtime_config() -> dict[str, str | int]:
    chunking = chunking_config()
    return {
        "profile": embed_profile_name(),
        "embedding_model": embedding_model_id(),
        "embedding_api_model": embedding_api_model(),
        "collection": rag_collection_name(),
        "meta_db": rag_meta_db_path(),
        "vector_size": rag_vector_size(),
        "chunk_size": rag_chunk_size(),
        "chunk_overlap": rag_chunk_overlap(),
        "chunk_unit": chunking["unit"],
        "chunk_size_effective": chunking["chunk_size"],
        "chunk_overlap_effective": chunking["chunk_overlap"],
    }
