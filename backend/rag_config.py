"""RAG embedding profile and Qdrant collection configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
        chunk_size=1400,
        chunk_overlap=100,
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
