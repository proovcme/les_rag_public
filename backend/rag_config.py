"""RAG embedding profile and Qdrant collection configuration."""

from __future__ import annotations

import logging
import os
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


load_dotenv(
    Path(os.getenv("LES_ENV_PATH", str(Path(__file__).resolve().parents[1] / ".env"))).expanduser(),
    override=False,
)


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
        collection="les_rag",
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

RAW_QUERY_EMBEDDING_MODE = "raw-v1"
QWEN_RETRIEVAL_QUERY_EMBEDDING_MODE = "qwen-retrieval-v1"
QWEN_RETRIEVAL_INSTRUCTION = "Given a search query, retrieve relevant passages from the selected corpus"
INDEX_CONTRACT_SCHEMA = "les.rag.index-contract.v3"
DOCUMENT_EMBEDDING_MODE = "raw-v1"
CHUNKER_REVISION = "structure-aware-final-budget-v2"


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


def query_embedding_mode() -> str:
    """Return the explicit query-side embedding contract.

    Documents remain raw.  The Qwen mode follows the upstream asymmetric
    retrieval contract and is deliberately opt-in until a corpus A/B gate proves
    its value.  Unknown modes fail safe to the raw historical behaviour.
    """
    mode = os.getenv("RAG_QUERY_EMBEDDING_MODE", RAW_QUERY_EMBEDDING_MODE).strip().lower()
    if embed_profile_name() == "qwen" and mode == QWEN_RETRIEVAL_QUERY_EMBEDDING_MODE:
        return mode
    return RAW_QUERY_EMBEDDING_MODE


def query_embedding_instruction_id() -> str:
    return query_embedding_mode()


def prepare_query_for_embedding(query: str) -> str:
    clean = str(query or "").strip()
    if query_embedding_mode() == QWEN_RETRIEVAL_QUERY_EMBEDDING_MODE:
        return f"Instruct: {QWEN_RETRIEVAL_INSTRUCTION}\nQuery: {clean}"
    return clean


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

        # Config/health/unit tests must never trigger a network model download.
        # Operators can opt in explicitly for a one-off preparation run.
        local_only = os.getenv("RAG_TOKENIZER_LOCAL_FILES_ONLY", "true").strip().lower() in {
            "1", "true", "yes", "on"
        }
        tokenizer = AutoTokenizer.from_pretrained(
            embedding_model_id(),
            local_files_only=local_only,
        )

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


def index_contract_path() -> Path:
    configured = os.getenv("RAG_INDEX_CONTRACT_PATH", "").strip()
    if configured:
        return Path(configured)
    db_path = Path(rag_meta_db_path())
    collection = re.sub(r"[^a-zA-Z0-9_.-]+", "_", rag_collection_name()).strip("._")
    return db_path.with_name(f"{db_path.name}.{collection}.index-contract.json")


def index_contract_payload() -> dict[str, Any]:
    chunking = chunking_config()
    payload: dict[str, Any] = {
        "schema": INDEX_CONTRACT_SCHEMA,
        "collection": rag_collection_name(),
        "embedding_model": embedding_model_id(),
        "embedding_api_model": embedding_api_model(),
        "embedding_backend": os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower(),
        "vector_size": rag_vector_size(),
        "document_embedding_mode": DOCUMENT_EMBEDDING_MODE,
        "chunk_unit": chunking["unit"],
        "chunk_size": int(chunking["chunk_size"]),
        "chunk_overlap": int(chunking["chunk_overlap"]),
        "chunker_revision": CHUNKER_REVISION,
        "qdrant_schema": "named",
        "dense_vector_name": os.getenv("RAG_DENSE_VECTOR_NAME", "dense").strip() or "dense",
        "sparse_vector_name": os.getenv("RAG_SPARSE_VECTOR_NAME", "bm25_sparse").strip()
        or "bm25_sparse",
        "sparse_tokenizer_revision": os.getenv("RAG_SPARSE_TOKENIZER_REVISION", "les-bm25-v1"),
        "point_embedding_fingerprint": point_embedding_fingerprint(),
        "hierarchy_schema": "les.rag.hierarchy.v1",
        "hierarchy_builder": "deterministic-heading-stack-v1",
        "hierarchy_retrieval": "soft-global-plus-descendant-rrf-v1",
        "navigation_evidence_policy": "navigation_not_evidence",
    }
    if payload["embedding_backend"] == "coreml":
        payload.update(
            {
                "embedding_package": os.getenv("COREML_EMBED_MODEL", ""),
                "embedding_seq_len": embed_seq_len(),
                "embedding_compute_units": os.getenv("COREML_EMBED_COMPUTE_UNITS", ""),
                "embedding_fallback": os.getenv("COREML_EMBED_FALLBACK", ""),
            }
        )
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["fingerprint"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    return payload


def point_embedding_descriptor() -> dict[str, str]:
    """Canonical point-level embedding identity shared by ingestion and manifest."""
    backend = os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower()
    descriptor = {
        "backend": backend,
        "model_id": embedding_model_id(),
        "profile": embed_profile_name(),
        "vector_size": str(rag_vector_size()),
    }
    if backend == "coreml":
        descriptor.update(
            {
                "coreml_model": os.getenv("COREML_EMBED_MODEL", ""),
                "coreml_seq_len": os.getenv("COREML_EMBED_SEQ_LEN", ""),
                "coreml_compute_units": os.getenv("COREML_EMBED_COMPUTE_UNITS", ""),
                "coreml_fallback": os.getenv("COREML_EMBED_FALLBACK", ""),
            }
        )
    return descriptor


def point_embedding_fingerprint(descriptor: dict[str, str] | None = None) -> str:
    data = descriptor or point_embedding_descriptor()
    stable = "\n".join(f"{key}={data.get(key, '')}" for key in sorted(data))
    return hashlib.sha1(stable.encode("utf-8", errors="ignore")).hexdigest()


def read_index_contract() -> dict[str, Any] | None:
    path = index_contract_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def index_contract_status() -> dict[str, Any]:
    expected = index_contract_payload()
    actual = read_index_contract()
    if actual is None:
        return {
            "status": "missing",
            "compatible": False,
            "path": str(index_contract_path()),
            "expected_fingerprint": expected["fingerprint"],
        }
    compatible = all(actual.get(key) == value for key, value in expected.items())
    return {
        "status": "compatible" if compatible else "mismatch",
        "compatible": compatible,
        "path": str(index_contract_path()),
        "expected_fingerprint": expected["fingerprint"],
        "actual_fingerprint": actual.get("fingerprint", ""),
        "actual": actual,
    }


def write_index_contract(*, replace: bool = False) -> Path:
    """Persist the contract for a newly created or explicitly adopted collection."""
    path = index_contract_path()
    if path.exists() and not replace:
        raise FileExistsError(f"index contract already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(index_contract_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def rag_runtime_config() -> dict[str, str | int]:
    chunking = chunking_config()
    contract = index_contract_status()
    return {
        "profile": embed_profile_name(),
        "embedding_model": embedding_model_id(),
        "embedding_api_model": embedding_api_model(),
        "query_embedding_mode": query_embedding_mode(),
        "query_instruction_id": query_embedding_instruction_id(),
        "collection": rag_collection_name(),
        "meta_db": rag_meta_db_path(),
        "vector_size": rag_vector_size(),
        "chunk_size": rag_chunk_size(),
        "chunk_overlap": rag_chunk_overlap(),
        "chunk_unit": chunking["unit"],
        "chunk_size_effective": chunking["chunk_size"],
        "chunk_overlap_effective": chunking["chunk_overlap"],
        "index_contract_status": contract["status"],
        "index_contract_compatible": contract["compatible"],
        "index_contract_fingerprint": contract.get("actual_fingerprint", ""),
    }
