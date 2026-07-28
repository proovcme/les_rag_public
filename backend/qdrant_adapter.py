"""
qdrant_adapter.py — RAG бэкенд: SQLite метабаза + Qdrant векторная база.

Исправлено по сравнению с оригиналом:
  1. embed_model.get_text_embedding → прямой httpx к MLX /v1/embeddings (нет зависимости от llama-index OpenAIEmbedding)
  2. retrieve → тоже прямой httpx (не блокирует event loop)
  3. _sync_parse батч эмбеддингов по 32 чанка вместо по одному — в 10-30x быстрее
  4. pending_names матчинг по полному rel-пути, не только file.name (дубли в разных папках)
  5. MarkdownNodeParser создаётся один раз, не на каждый файл
  6. Пустые чанки (< 20 символов) фильтруются до эмбеддинга
  7. retrieve: get_query_embedding синхронный в asyncio → заменён на async httpx
  8. _ensure_collection: race condition при параллельных startup вызовах → asyncio.Lock
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

import httpx
import qdrant_client
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import Document, TextNode
from qdrant_client import models

from .converter import convert_to_markdown_for_indexing, normalize_pdf_text
from .document_router import DocumentRoute, route_document
from .interface import Chunk, DatasetInfo, EmbeddingContractError, RAGBackend
from .mail_profile import build_mail_vector_profile, deterministic_mail_node_id
from .parquet_writer import TableNormalizer
from proxy.services.dataset_memory_service import chunk_payload_typing, current_dataset_revision_id
from .rag_config import (
    chunking_config,
    index_contract_status,
    rag_chunk_overlap,
    rag_chunk_size,
    rag_collection_name,
    rag_meta_db_path,
    rag_vector_size,
    prepare_query_for_embedding,
    point_embedding_descriptor,
    point_embedding_fingerprint,
    write_index_contract,
)

logger = logging.getLogger(__name__)


RAW_CAD_BIM_SUFFIXES = {".dwg", ".dxf", ".rvt", ".rfa", ".ifc", ".ifczip", ".nwc"}
PDF_PAGE_NODE_SUFFIXES = {".pdf", ".p7m"}


def _pdf_page_nodes_enabled(file_path: Path, route: DocumentRoute | None = None) -> bool:
    if file_path.suffix.lower() not in PDF_PAGE_NODE_SUFFIXES:
        return False
    if os.getenv("RAG_PDF_PAGE_NODES_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    return True


def _pdf_page_passport_enabled(file_path: Path) -> bool:
    return (
        file_path.suffix.lower() == ".pdf"
        and os.getenv("RAG_PDF_PAGE_PASSPORT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    )


def _pdf_page_node_max_chars() -> int:
    try:
        return max(800, int(os.getenv("RAG_PDF_PAGE_NODE_MAX_CHARS", "1800")))
    except ValueError:
        return 1800


def _pdf_page_node_overlap_chars() -> int:
    try:
        return max(0, int(os.getenv("RAG_PDF_PAGE_NODE_OVERLAP_CHARS", "150")))
    except ValueError:
        return 150


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UnsupportedIndexingSourceError(RuntimeError):
    """Raised when intake accepted a source that needs a typed converter first."""


def _is_raw_cad_bim_source(file_path: Path, route: DocumentRoute | None) -> bool:
    suffix = file_path.suffix.lower()
    return suffix in RAW_CAD_BIM_SUFFIXES and (
        route is None
        or route.content_type == "cad_bim"
        or route.pipeline == "json_graph_projection"
        or route.doc_type == "CAD_BIM"
    )


def _raw_cad_bim_error(file_path: Path) -> str:
    suffix = file_path.suffix.lower() or "raw"
    return (
        f"raw CAD/BIM source unsupported by text RAG indexing ({suffix}); "
        "export/import it as canonical CAD/BIM JSON/JSONL projection before indexing"
    )


class StructureAwareSplitter:
    """Structure-aware chunking for SP and GOST documents.
    Preserves numbered clauses (e.g. 5.2.1) as single indivisible blocks.
    Fits chunks within a target character length, and implements sentence-bounded overlap.
    """
    def __init__(self, chunk_size: int, chunk_overlap: int, len_fn=None):
        # W2.1 (ADR-7): len_fn — счётчик размера (токены эмбеддера); None = символы.
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._len = len_fn or len
        # Жёсткая нарезка патологически длинных предложений — всегда в символах:
        # при токенном режиме берём ~3 символа на токен (русский текст).
        self._hard_slice_chars = chunk_size if len_fn is None else chunk_size * 3
        self.fallback = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        
        # Regex to detect lines that start a new numbered section or markdown header
        self.boundary_pattern = re.compile(
            r"^(?:#{1,6}\s+|"
            r"(?:Пункт|Раздел|Статья|п\.|§)\s*\d+(?:\.\d+)+|"
            r"\d+(?:\.\d+)+(?:\s+|\.|$))",
            re.IGNORECASE
        )

    def _split_into_atomic_blocks(self, text: str) -> list[str]:
        lines = text.split("\n")
        blocks = []
        current_block_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_block_lines:
                    current_block_lines.append(line)
                continue
                
            if self.boundary_pattern.match(stripped):
                if current_block_lines:
                    blocks.append("\n".join(current_block_lines).strip())
                    current_block_lines = []
            
            current_block_lines.append(line)
            
        if current_block_lines:
            blocks.append("\n".join(current_block_lines).strip())
            
        return [b for b in blocks if b]

    def _get_sentence_overlap(self, text_prev: str, max_overlap: int) -> str:
        if not text_prev or max_overlap <= 0:
            return ""
        sentences = re.split(r'(?<=[.!?])\s+', text_prev)
        overlap_sentences = []
        current_len = 0
        for s in reversed(sentences):
            s = s.strip()
            if not s:
                continue
            if current_len + self._len(s) + 1 <= max_overlap:
                overlap_sentences.append(s)
                current_len += self._len(s) + 1
            else:
                if not overlap_sentences:
                    return s[-max_overlap * (1 if self._len is len else 3):]
                break
        if not overlap_sentences:
            return ""
        return " ".join(reversed(overlap_sentences)) + " "

    def _split_large_block(self, text: str, max_chars: int, overlap_chars: int) -> list[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_len = 0
        
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            s_len = self._len(s)

            if s_len > max_chars:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_len = 0
                hard_max = self._hard_slice_chars
                hard_overlap = min(overlap_chars * (1 if self._len is len else 3), hard_max // 4)
                raw_len = len(s)
                i = 0
                while i < raw_len:
                    chunks.append(s[i:i + hard_max])
                    i += hard_max - hard_overlap
                    if i + hard_overlap >= raw_len:
                        if i < raw_len:
                            chunks.append(s[i:])
                        break
            else:
                separator_len = 1 if current_chunk else 0
                if current_len + separator_len + s_len <= max_chars:
                    current_chunk.append(s)
                    current_len += separator_len + s_len
                else:
                    chunks.append(" ".join(current_chunk))
                    overlap_prefix = self._get_sentence_overlap(chunks[-1], overlap_chars)
                    current_chunk = []
                    current_len = 0
                    if overlap_prefix:
                        current_chunk.append(overlap_prefix.strip())
                        current_len = self._len(overlap_prefix.strip())

                    separator_len = 1 if current_chunk else 0
                    current_chunk.append(s)
                    current_len += separator_len + s_len
                    
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    def get_nodes_from_documents(self, documents: list) -> list:
        all_nodes = []
        for doc in documents:
            text = doc.text
            metadata = doc.metadata or {}
            doc_id = doc.node_id if hasattr(doc, "node_id") else doc.id_
            
            atomic_blocks = self._split_into_atomic_blocks(text)
            
            chunks = []
            current_chunk_blocks = []
            current_chunk_len = 0
            
            for block in atomic_blocks:
                block_len = self._len(block)
                
                if block_len > self.chunk_size:
                    if current_chunk_blocks:
                        chunks.append("\n\n".join(current_chunk_blocks))
                        current_chunk_blocks = []
                        current_chunk_len = 0
                    
                    sub_chunks = self._split_large_block(block, self.chunk_size, self.chunk_overlap)
                    chunks.extend(sub_chunks)
                else:
                    separator_len = 2 if current_chunk_blocks else 0
                    if current_chunk_len + separator_len + block_len <= self.chunk_size:
                        current_chunk_blocks.append(block)
                        current_chunk_len += separator_len + block_len
                    else:
                        chunks.append("\n\n".join(current_chunk_blocks))
                        overlap_prefix = self._get_sentence_overlap(chunks[-1], self.chunk_overlap)
                        
                        current_chunk_blocks = []
                        current_chunk_len = 0
                        if overlap_prefix:
                            current_chunk_blocks.append(overlap_prefix.strip())
                            current_chunk_len = self._len(overlap_prefix.strip())
                            
                        separator_len = 2 if current_chunk_blocks else 0
                        current_chunk_blocks.append(block)
                        current_chunk_len += separator_len + block_len
            
            if current_chunk_blocks:
                chunks.append("\n\n".join(current_chunk_blocks))
                
            for idx, chunk_text in enumerate(chunks):
                node = TextNode(
                    text=chunk_text,
                    id_=f"{doc_id}_chunk_{idx}",
                    metadata=metadata
                )
                all_nodes.append(node)
                
        return all_nodes

EMBED_BATCH  = int(os.getenv("RAG_EMBED_BATCH", "16"))      # чанков за один запрос к MLX embeddings
EMBED_TIMEOUT = float(os.getenv("RAG_EMBED_TIMEOUT_SEC", "300"))
MIN_CHUNK    = int(os.getenv("RAG_MIN_CHUNK_CHARS", "100"))  # W2.5: <100 симв — шум («Приложение», «А»), не индексируем
FINAL_MIN_CHUNK = int(os.getenv("RAG_FINAL_MIN_CHUNK_CHARS", "20"))
UPSERT_BATCH = int(os.getenv("RAG_UPSERT_BATCH", "100"))    # точек за один upsert в Qdrant
TABLE_ROW_INDEX_MAX_CHUNKS = int(os.getenv("RAG_TABLE_ROW_INDEX_MAX_CHUNKS", "600"))
VERIFY_POINTS_EVERY = max(1, int(os.getenv("RAG_VERIFY_POINTS_EVERY", "1")))  # P0: exact-count каждый файл by default
# W1.4: конвейер — конвертация следующего файла параллельно с эмбеддингом текущего,
# per-file таймаут конвертации (зависший файл помечается ERROR, индексация продолжается).
PARSE_PREFETCH = os.getenv("RAG_PARSE_PREFETCH", "true").lower() == "true"
PARSE_FILE_TIMEOUT = float(os.getenv("RAG_PARSE_FILE_TIMEOUT_SEC", "1800"))
CHUNK_HASH_CACHE = os.getenv("RAG_CHUNK_HASH_CACHE", "true").lower() in {"1", "true", "yes", "on"}
RAG_CHUNK_SIZE = rag_chunk_size()
RAG_CHUNK_OVERLAP = rag_chunk_overlap()
ALLOW_UNBOUNDED_PARSE = "ALLOW_UNBOUNDED_PARSE"
_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _embedding_cache_descriptor() -> dict[str, str]:
    return point_embedding_descriptor()


def _embedding_cache_fingerprint(descriptor: dict[str, str] | None = None) -> str:
    return point_embedding_fingerprint(descriptor)


def _qdrant_schema_mode() -> str:
    return "named"


def _dense_vector_name() -> str:
    return os.getenv("RAG_DENSE_VECTOR_NAME", "dense").strip() or "dense"


def _sparse_vector_name() -> str:
    from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME

    return os.getenv("RAG_SPARSE_VECTOR_NAME", SPARSE_VECTOR_NAME).strip() or SPARSE_VECTOR_NAME


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _named_collection_layout(info: Any, *, vector_size: int) -> tuple[bool, int]:
    """Return named dense+sparse compatibility and point count for a collection."""
    config = _field(info, "config", {})
    params = _field(config, "params", {})
    vectors = _field(params, "vectors", {})
    sparse_vectors = _field(params, "sparse_vectors", {})
    points_count = int(_field(info, "points_count", 0) or 0)
    if not isinstance(vectors, Mapping) or not isinstance(sparse_vectors, Mapping):
        return False, points_count
    dense = vectors.get(_dense_vector_name())
    dense_size = int(_field(dense, "size", 0) or 0) if dense is not None else 0
    compatible = dense_size == vector_size and _sparse_vector_name() in sparse_vectors
    return compatible, points_count


def _can_adopt_missing_contract(*, points_count: int, matching_fingerprint_count: int) -> bool:
    """A missing sidecar is safe to recreate only from a provably canonical collection."""
    return points_count == 0 or matching_fingerprint_count == points_count


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.{2,160})$")
_NUM_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,4})[.\s]+([А-ЯЁA-Z].{1,150})$")
_DATA_URI_RE = re.compile(
    r"data:[^\s;,]{1,120}(?:;[^\s,]{1,80})*;base64,[A-Za-z0-9+/=\s]{128,}",
    re.IGNORECASE,
)
_BASE64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{256,}={0,2}(?![A-Za-z0-9+/=])")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_embedding_text(text: str) -> tuple[str, dict[str, Any]]:
    """Remove transport/binary payloads before they can become evidence.

    The gate is deliberately format-agnostic and runs after every converter, so
    mixed text+base64 chunks cannot bypass a parser-specific check.
    """
    raw = str(text or "")
    data_uri_count = len(_DATA_URI_RE.findall(raw))
    clean = _DATA_URI_RE.sub(" [binary attachment removed] ", raw)
    base64_count = len(_BASE64_RUN_RE.findall(clean))
    clean = _BASE64_RUN_RE.sub(" [binary payload removed] ", clean)
    control_count = len(_CONTROL_CHARS_RE.findall(clean))
    clean = _CONTROL_CHARS_RE.sub(" ", clean)
    clean = re.sub(r"[ \t]{3,}", "  ", clean)
    clean = re.sub(r"\n{4,}", "\n\n\n", clean).strip()
    return clean, {
        "data_uri_removed": data_uri_count,
        "base64_runs_removed": base64_count,
        "control_chars_removed": control_count,
        "sanitized": bool(data_uri_count or base64_count or control_count),
    }


def _largest_budget_prefix(text: str, *, budget: int, len_fn) -> int:
    """Largest non-empty character prefix whose real token length fits budget."""
    low, high = 1, len(text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        if len_fn(text[:mid]) <= budget:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    if best <= 0:
        return 1
    # Prefer a semantic boundary without throwing away more than 20% of budget.
    floor = max(1, int(best * 0.8))
    candidates = [text.rfind("\n", floor, best), text.rfind(" ", floor, best)]
    boundary = max(candidates)
    return boundary if boundary >= floor else best


def _split_to_embedding_budget(text: str, *, budget: int, len_fn) -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return []
    if len_fn(clean) <= budget:
        return [clean]
    parts: list[str] = []
    remaining = clean
    while remaining:
        if len_fn(remaining) <= budget:
            parts.append(remaining.strip())
            break
        cut = _largest_budget_prefix(remaining, budget=budget, len_fn=len_fn)
        part = remaining[:cut].strip()
        if part:
            parts.append(part)
        remaining = remaining[cut:].strip()
    return [part for part in parts if part]


def _section_heading_info(text: str) -> tuple[str, int]:
    """W2.5: (заголовок, уровень). Уровень: # → 1..6; «5.2.1 Текст» → глубина номера; 0 — нет."""
    for line in text.splitlines()[:6]:
        line = line.strip()
        if not line:
            continue
        md = _MD_HEADING_RE.match(line)
        if md:
            return md.group(2).strip(), len(md.group(1))
        num = _NUM_HEADING_RE.match(line)
        if num:
            return f"{num.group(1)} {num.group(2).strip()}", num.group(1).count(".") + 1
    return "", 0


def _section_heading(text: str) -> str:
    heading, _ = _section_heading_info(text)
    if heading:
        return heading
    # Старое поведение как fallback: первая осмысленная строка.
    for line in text.splitlines():
        line = line.strip(" #\t")
        if 4 <= len(line) <= 160:
            return line
    return ""


def _compact_text(text: str, limit: int = 1200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _apply_context_metadata_to_nodes(file_nodes: list[dict], dataset_id: str, file_key: str) -> None:
    if not file_nodes:
        return

    grouped: dict[str, list[int]] = {}
    try:
        window_size = max(1, int(os.getenv("RAG_PARENT_WINDOW_CHUNKS", "4")))
    except ValueError:
        window_size = 4
    last_heading = ""
    last_level = 0
    dataset_revision = current_dataset_revision_id(dataset_id)
    for chunk_ord, file_node in enumerate(file_nodes):
        payload = file_node.setdefault("payload", {})
        payload.setdefault("dataset_id", dataset_id)
        payload.setdefault("file_name", file_key)
        if dataset_revision:
            payload.setdefault("dataset_revision", dataset_revision)
        try:
            payload.update(chunk_payload_typing(file_key, payload, payload))
        except Exception:
            pass
        text = str(file_node.get("text") or "")
        payload.setdefault("chunk_ord", chunk_ord)
        payload.setdefault("child_ord", chunk_ord)
        payload.setdefault("content_hash", _content_hash(text))
        # W2.5: настоящий заголовок (markdown/нумерованный) с уровнем; чанки-продолжения
        # наследуют последний найденный заголовок раздела.
        heading, level = _section_heading_info(text)
        if heading:
            last_heading, last_level = heading, level
            payload.setdefault("section_heading", heading)
            payload.setdefault("heading_level", level)
        elif last_heading:
            payload.setdefault("section_heading", last_heading)
            payload.setdefault("heading_level", last_level)
            payload.setdefault("heading_inherited", True)
        else:
            payload.setdefault("section_heading", _section_heading(text))

        source_page = payload.get("source_page") or payload.get("page") or payload.get("page_number")
        table_index = payload.get("table_index")
        if source_page is not None:
            group_key = f"page:{source_page}:table:{table_index or ''}"
            context_kind = "table_page" if payload.get("type") == "table_row" else "pdf_page"
        else:
            group_key = f"window:{chunk_ord // window_size}"
            context_kind = "markdown_window"
        grouped.setdefault(group_key, []).append(chunk_ord)
        payload.setdefault("context_kind", context_kind)

    for parent_ord, (group_key, indexes) in enumerate(grouped.items()):
        parent_id = _content_hash(f"{dataset_id}:{file_key}:{group_key}")[:24]
        heading = ""
        for idx in indexes:
            candidate = str(file_nodes[idx].get("payload", {}).get("section_heading") or "")
            if candidate:
                heading = candidate
                break
        for idx in indexes:
            payload = file_nodes[idx].setdefault("payload", {})
            payload.setdefault("parent_id", parent_id)
            payload.setdefault("parent_ord", parent_ord)
            payload.setdefault("parent_heading", heading)

    for idx, file_node in enumerate(file_nodes):
        payload = file_node.setdefault("payload", {})
        parent_id = payload.get("parent_id")
        if idx > 0 and file_nodes[idx - 1].get("payload", {}).get("parent_id") == parent_id:
            payload.setdefault("context_before", _compact_text(str(file_nodes[idx - 1].get("text") or "")))
        if idx + 1 < len(file_nodes) and file_nodes[idx + 1].get("payload", {}).get("parent_id") == parent_id:
            payload.setdefault("context_after", _compact_text(str(file_nodes[idx + 1].get("text") or "")))
# ── Прямой клиент эмбеддингов (httpx, без llama-index) ───────────────────────

class EmbedClient:
    """
    Тонкий клиент к /v1/embeddings MLX Host.
    Работает асинхронно и синхронно (для _sync_parse в threadpool).
    """
    def __init__(
        self,
        base_url: str,
        model: str = "bge-m3",
        *,
        backend: str | None = None,
    ):
        self.url   = f"{base_url.rstrip('/')}/v1/embeddings"
        self.model = model
        self.backend = (
            str(backend).strip().lower()
            if backend is not None
            else os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower()
        )

    @staticmethod
    def _normalise_model_id(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

    def _vectors_from_response(self, payload: dict[str, Any]) -> List[List[float]]:
        """Validate the model that actually produced a response before using it.

        The OpenAI ``model`` request field is descriptive for the local MLX host:
        it does not select a model.  A host must therefore report the active
        ``embedding_model`` explicitly.  Missing or incompatible metadata is a
        safety failure, not a reason to score Qwen and BGE vectors together.
        """
        reported_embedding_model = str(payload.get("embedding_model") or "").strip()
        reported_openai_model = str(payload.get("model") or "").strip()
        # Ollama's OpenAI-compatible endpoint selects the requested model and
        # reports it in the standard ``model`` field.  LES-owned MLX/CoreML
        # hosts must keep reporting the stronger explicit contract fields.
        ollama_contract = self.backend == "ollama" and bool(reported_openai_model)
        actual_model = reported_embedding_model or (reported_openai_model if ollama_contract else "")
        actual_backend = str(payload.get("embedding_backend") or "").strip().lower()
        if not actual_backend and ollama_contract:
            actual_backend = "ollama"
        expected = self._normalise_model_id(self.model)
        actual = self._normalise_model_id(actual_model)
        if not actual_model:
            raise EmbeddingContractError(
                f"embedding contract not reported by {self.url}; expected={self.model}"
            )
        if not expected or not actual or (expected not in actual and actual not in expected):
            raise EmbeddingContractError(
                f"embedding contract mismatch: expected={self.model}, actual={actual_model}"
            )
        expected_backend = self.backend
        if not actual_backend:
            raise EmbeddingContractError(
                f"embedding backend not reported by {self.url}; expected={expected_backend}"
            )
        if actual_backend != expected_backend:
            raise EmbeddingContractError(
                "embedding backend mismatch: "
                f"expected={expected_backend}, actual={actual_backend}"
            )
        data = payload.get("data") or []
        data.sort(key=lambda x: x["index"])
        return [d["embedding"] for d in data]

    @staticmethod
    def _response_detail(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("detail") or payload.get("message")
            if detail:
                return " ".join(str(detail).split())[:500]
        return " ".join(str(getattr(response, "text", "") or "").split())[:500]

    def _encode_sync_resilient(self, texts: List[str]) -> List[List[float]]:
        import httpx as _httpx

        try:
            attempts = max(1, int(os.getenv("RAG_EMBED_RETRY_ATTEMPTS", "3")))
        except ValueError:
            attempts = 3
        try:
            delay = max(0.0, float(os.getenv("RAG_EMBED_RETRY_DELAY_SEC", "0.35")))
        except ValueError:
            delay = 0.35

        response = None
        request_error: Exception | None = None
        retryable = {400, 408, 409, 425, 429, 500, 502, 503, 504}
        for attempt in range(1, attempts + 1):
            try:
                response = _httpx.post(
                    self.url,
                    json={"model": self.model, "input": texts},
                    timeout=EMBED_TIMEOUT,
                )
                if response.status_code < 400:
                    return self._vectors_from_response(response.json())
                request_error = None
                if response.status_code not in retryable:
                    break
            except _httpx.RequestError as error:
                request_error = error
                response = None
            if attempt < attempts:
                time.sleep(delay * attempt)

        # Ollama can reject one batch transiently while the same inputs work in
        # smaller groups.  Split only after bounded retries; a bad item is then
        # isolated without discarding already valid document chunks.
        if len(texts) > 1 and (response is None or response.status_code in retryable):
            middle = max(1, len(texts) // 2)
            return self._encode_sync_resilient(texts[:middle]) + self._encode_sync_resilient(texts[middle:])

        text_hash = hashlib.sha256((texts[0] if texts else "").encode("utf-8", errors="ignore")).hexdigest()[:12]
        if response is not None:
            detail = self._response_detail(response) or "сервер не сообщил причину"
            raise RuntimeError(
                "Сервис поискового представления отклонил фрагмент "
                f"после {attempts} попыток: HTTP {response.status_code}; {detail}; "
                f"fragment={text_hash}"
            )
        raise RuntimeError(
            "Сервис поискового представления недоступен "
            f"после {attempts} попыток: {request_error}; fragment={text_hash}"
        )

    def encode_sync(self, texts: List[str]) -> List[List[float]]:
        """Синхронный parse-клиент с bounded retry и изоляцией плохого фрагмента."""
        if not texts:
            return []
        return self._encode_sync_resilient(texts)

    async def encode_async(self, texts: List[str], *, query: bool = False) -> List[List[float]]:
        """Асинхронный вариант для retrieve; query contract never touches documents."""
        payload_texts = [prepare_query_for_embedding(text) for text in texts] if query else texts
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                self.url,
                json={"model": self.model, "input": payload_texts},
            )
            r.raise_for_status()
            return self._vectors_from_response(r.json())


# ── SQLite метабаза ───────────────────────────────────────────────────────────

class MetaDB:
    def __init__(self, db_path: str | None = None):
        db_path = db_path or rag_meta_db_path()
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id          TEXT PRIMARY KEY,
                    name        TEXT,
                    status      TEXT,
                    chunk_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id          TEXT PRIMARY KEY,
                    dataset_id  TEXT,
                    file_name   TEXT,
                    status      TEXT,
                    file_hash   TEXT,
                    file_mtime  REAL,
                    file_size   INTEGER,
                    chunk_count INTEGER DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_dataset ON documents(dataset_id)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS structured_rules (
                    id          TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    file_key    TEXT NOT NULL,
                    chunk_id    TEXT NOT NULL,
                    subject     TEXT NOT NULL,
                    parameter   TEXT NOT NULL,
                    operator    TEXT NOT NULL,
                    value       REAL NOT NULL,
                    unit        TEXT NOT NULL,
                    condition   TEXT,
                    char_start  INTEGER NOT NULL,
                    char_end    INTEGER NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rules_doc ON structured_rules(document_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rules_file ON structured_rules(file_key)"
            )
            # Миграция существующих БД
            for col, typedef in [
                ("file_hash",   "TEXT"),
                ("file_mtime",  "REAL"),
                ("file_size",   "INTEGER"),
                ("chunk_count", "INTEGER DEFAULT 0"),
                ("domain",      "TEXT DEFAULT ''"),
                ("route_dataset", "TEXT DEFAULT ''"),
                ("doc_type",    "TEXT DEFAULT ''"),
                ("content_type", "TEXT DEFAULT ''"),
                ("complexity",   "TEXT DEFAULT ''"),
                ("pipeline",     "TEXT DEFAULT ''"),
                ("last_error",   "TEXT DEFAULT ''"),
                ("stage",        "TEXT DEFAULT ''"),  # W1.4: текущая стадия конвейера (CONVERT/EMBED/UPSERT)
                ("source_path",  "TEXT DEFAULT ''"),  # внешний in-place источник (абсолютный путь, без копии в storage)
            ]:
                try:
                    conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {typedef}")
                except Exception:
                    pass
            try:
                conn.execute("ALTER TABLE datasets ADD COLUMN chunk_count INTEGER DEFAULT 0")
            except Exception:
                pass
            # W3.3 (ADR-9): чувствительность данных датасета для маршрутизации
            # локал/облако. Дефолт P0 (local-only) — fail-closed: немаркированный
            # датасет в облако не уходит, пока оператор явно не пометит P1/P2.
            try:
                conn.execute("ALTER TABLE datasets ADD COLUMN sensitivity TEXT DEFAULT 'P0'")
            except Exception:
                pass
            # Пользовательская группа датасета — организация списка в САМОВАРе
            # (навигация, на поиск не влияет). Пусто = без группы.
            try:
                conn.execute("ALTER TABLE datasets ADD COLUMN group_name TEXT DEFAULT ''")
            except Exception:
                pass
            # Module-owned knowledge is a separate entity, not a project upload.
            # The registry is deterministic, so legacy service datasets migrate
            # on startup without touching documents or vectors.
            try:
                conn.execute("ALTER TABLE datasets ADD COLUMN dataset_scope TEXT DEFAULT 'user'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE datasets ADD COLUMN module_id TEXT DEFAULT ''")
            except Exception:
                pass
            conn.execute(
                "UPDATE datasets SET dataset_scope='system', module_id='smeta' "
                "WHERE name='SMETA_SERVICE_Index' OR name='GESN_NORMS_2022_PDF' "
                "OR name LIKE 'SMETA_RU_NORM_%'"
            )

    def ensure_system_datasets(self) -> list[str]:
        """Provision module-owned datasets only from the real runtime bootstrap.

        Constructing an isolated MetaDB must remain free of product-data side
        effects; tests, tools and import probes legitimately use temporary DBs.
        """
        from proxy.services.system_dataset_service import ensure_system_datasets

        with self._get_conn() as conn:
            return ensure_system_datasets(conn)

    def create_dataset(self, name: str) -> str:
        from proxy.services.system_dataset_service import dataset_identity, system_dataset_spec

        spec = system_dataset_spec(name)
        dataset_scope, module_id = dataset_identity(name)
        with self._get_conn() as conn:
            if spec:
                existing = conn.execute("SELECT id FROM datasets WHERE name=? LIMIT 1", (name,)).fetchone()
                if existing:
                    return str(existing[0])
            ds_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO datasets (id, name, status, dataset_scope, module_id) "
                "VALUES (?, ?, 'IDLE', ?, ?)",
                (ds_id, name, dataset_scope, module_id),
            )
        return ds_id

    def update_dataset_status(self, dataset_id: str, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE datasets SET status=? WHERE id=?", (status, dataset_id)
            )

    def recover_interrupted_parsing(self) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE datasets SET status='IDLE' WHERE status='PARSING'")
            return int(cur.rowcount or 0)

    def list_datasets(self) -> List[DatasetInfo]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT d.id, d.name, d.status, d.chunk_count,
                       COALESCE(d.sensitivity, 'P0') AS sensitivity,
                       COALESCE(d.group_name, '') AS group_name,
                       COALESCE(d.dataset_scope, 'user') AS dataset_scope,
                       COALESCE(d.module_id, '') AS module_id,
                       COUNT(doc.id) AS total_files,
                       SUM(CASE WHEN doc.status='INDEXED' THEN 1 ELSE 0 END) AS indexed_files,
                       SUM(CASE WHEN doc.status='PENDING' THEN 1 ELSE 0 END) AS pending_files,
                       SUM(CASE WHEN doc.status='ERROR' THEN 1 ELSE 0 END) AS error_files,
                       SUM(CASE WHEN doc.status='MISSING' THEN 1 ELSE 0 END) AS missing_files
                FROM datasets d
                LEFT JOIN documents doc ON d.id = doc.dataset_id
                GROUP BY d.id
            """).fetchall()
        return [
            DatasetInfo(
                id=r["id"], name=r["name"], status=r["status"],
                doc_count=r["total_files"] or 0,
                chunk_count=r["chunk_count"] or 0,
                sensitivity=r["sensitivity"] or "P0",
                group_name=r["group_name"] or "",
                files=r["total_files"] or 0,
                indexed_files=r["indexed_files"] or 0,
                pending_files=r["pending_files"] or 0,
                error_files=r["error_files"] or 0,
                missing_files=r["missing_files"] or 0,
                dataset_scope=r["dataset_scope"] or "user",
                module_id=r["module_id"] or "",
            )
            for r in rows
        ]

    def set_dataset_sensitivity(self, dataset_id: str, sensitivity: str) -> None:
        """W3.3 (ADR-9): пометить чувствительность датасета (P0/P1/P2)."""
        level = str(sensitivity or "").strip().upper()
        if level not in ("P0", "P1", "P2"):
            raise ValueError(f"sensitivity must be P0/P1/P2, got {sensitivity!r}")
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE datasets SET sensitivity=? WHERE id=?", (level, dataset_id)
            )

    def set_dataset_group(self, dataset_id: str, group_name: str) -> None:
        """Пользовательская группа датасета (организация в САМОВАРе). Пусто = без группы."""
        grp = str(group_name or "").strip()[:60]
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE datasets SET group_name=? WHERE id=?", (grp, dataset_id)
            )

    def add_document(
        self, dataset_id: str, file_name: str,
        file_mtime: float = 0.0, file_size: int = 0,
        source_path: str = "",
    ) -> tuple:
        """Возвращает (doc_id, is_new, needs_reindex).

        source_path != "" — внешний in-place источник (абсолютный путь). Документ
        не копируется в storage, а читается из source_path при парсинге.
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, file_mtime, file_size FROM documents "
                "WHERE dataset_id=? AND file_name=?",
                (dataset_id, file_name),
            ).fetchone()
            if existing:
                doc_id  = existing["id"]
                changed = (
                    abs((existing["file_mtime"] or 0) - file_mtime) > 1.0
                    or (existing["file_size"] or 0) != file_size
                )
                if changed:
                    conn.execute(
                        "UPDATE documents SET status='PENDING', file_mtime=?, file_size=?, source_path=? WHERE id=?",
                        (file_mtime, file_size, source_path, doc_id),
                    )
                    return doc_id, False, True
                # Содержимое не изменилось, но абсолютный источник мог переехать — обновим.
                if source_path:
                    conn.execute(
                        "UPDATE documents SET source_path=? WHERE id=?",
                        (source_path, doc_id),
                    )
                return doc_id, False, False
            doc_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size, source_path) "
                "VALUES (?, ?, ?, 'PENDING', ?, ?, ?)",
                (doc_id, dataset_id, file_name, file_mtime, file_size, source_path),
            )
            return doc_id, True, True

    def update_document_status(
        self,
        dataset_id: str,
        file_name: str,
        status: str,
        chunk_count: int = 0,
        route: DocumentRoute | None = None,
        last_error: str = "",
    ):
        with self._get_conn() as conn:
            fields = ["status=?", "chunk_count=?", "last_error=?", "stage=''"]
            values: list[Any] = [status, chunk_count, last_error[:2000]]
            if route is not None:
                fields.extend([
                    "domain=?",
                    "route_dataset=?",
                    "doc_type=?",
                    "content_type=?",
                    "complexity=?",
                    "pipeline=?",
                ])
                values.extend([
                    route.domain,
                    route.dataset_name,
                    route.doc_type,
                    route.content_type,
                    route.complexity,
                    route.pipeline,
                ])
            values.extend([dataset_id, file_name])
            cur = conn.execute(
                f"UPDATE documents SET {', '.join(fields)} "
                "WHERE dataset_id=? AND file_name=?",
                values,
            )
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"document status update affected {cur.rowcount} rows "
                    f"for dataset_id={dataset_id}, file_name={file_name}"
                )

    def mark_document_error(self, dataset_id: str, document_id: str, error: str) -> None:
        """Mark one uploaded document as failed by its stable public id."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE documents SET status='ERROR', chunk_count=0, last_error=?, stage='' "
                "WHERE dataset_id=? AND id=?",
                (str(error)[:2000], dataset_id, document_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"document error update affected {cur.rowcount} rows "
                    f"for dataset_id={dataset_id}, document_id={document_id}"
                )

    def requeue_error_documents(self, dataset_id: str) -> int:
        """«Ремонт» датасета: ERROR-документы → PENDING (очистка last_error/stage/chunk_count),
        чтобы перепарсить их БЕЗ удаления датасета/индекса. Возвращает число сброшенных."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE documents SET status='PENDING', last_error='', stage='', chunk_count=0 "
                "WHERE dataset_id=? AND status='ERROR'",
                (dataset_id,),
            )
            return cur.rowcount

    def requeue_corrupt_pdf_text_documents(self, dataset_id: str) -> list[str]:
        """Find already indexed PDF text damaged by UTF-8/Latin-1 mojibake and requeue its source.

        Detection is based on the same conservative normalizer used by new PDF
        ingestion.  A document is touched only when at least two chunks are
        repairable and at least a quarter of its indexed chunks are affected.
        """
        with self._get_conn() as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lexical_chunks'"
            ).fetchone()
            if not table:
                return []
            rows = conn.execute(
                "SELECT doc_name, text FROM lexical_chunks WHERE dataset_id=? ORDER BY doc_name, id",
                (dataset_id,),
            ).fetchall()
            totals: dict[str, int] = {}
            damaged: dict[str, int] = {}
            for row in rows:
                name = str(row["doc_name"] or "")
                if not name.lower().endswith((".pdf", ".p7m")):
                    continue
                text = str(row["text"] or "")
                totals[name] = totals.get(name, 0) + 1
                if normalize_pdf_text(text) != text:
                    damaged[name] = damaged.get(name, 0) + 1
            names = sorted(
                name for name, count in damaged.items()
                if count >= 2 and count * 4 >= totals.get(name, 0)
            )
            if not names:
                return []
            placeholders = ",".join("?" for _ in names)
            conn.execute(
                f"UPDATE documents SET status='PENDING', last_error='', stage='', chunk_count=0 "
                f"WHERE dataset_id=? AND file_name IN ({placeholders})",
                (dataset_id, *names),
            )
            return names

    def update_document_stage(self, dataset_id: str, file_name: str, stage: str) -> None:
        """W1.4: текущая стадия конвейера файла (CONVERT/EMBED/UPSERT) — для прогресса/диагностики."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET stage=? WHERE dataset_id=? AND file_name=?",
                (stage, dataset_id, file_name),
            )

    def dataset_parse_progress(self, dataset_id: str) -> dict[str, Any]:
        """Small read-only snapshot for the operator job poller."""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='INDEXED' THEN 1 ELSE 0 END) AS indexed,
                    SUM(CASE WHEN status='PENDING' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status='ERROR' THEN 1 ELSE 0 END) AS errors
                FROM documents WHERE dataset_id=?
                """,
                (dataset_id,),
            ).fetchone()
            active = conn.execute(
                """
                SELECT file_name, stage
                FROM documents
                WHERE dataset_id=? AND status='PENDING' AND COALESCE(stage, '')<>''
                ORDER BY file_name
                LIMIT 1
                """,
                (dataset_id,),
            ).fetchone()
        return {
            "total": int(counts["total"] or 0),
            "indexed": int(counts["indexed"] or 0),
            "pending": int(counts["pending"] or 0),
            "errors": int(counts["errors"] or 0),
            "file_name": str(active["file_name"] or "") if active else "",
            "stage": str(active["stage"] or "") if active else "",
        }

    def update_document_route(self, dataset_id: str, file_name: str, route: DocumentRoute):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET domain=?, route_dataset=?, doc_type=?, content_type=?, complexity=?, pipeline=? "
                "WHERE dataset_id=? AND file_name=?",
                (
                    route.domain,
                    route.dataset_name,
                    route.doc_type,
                    route.content_type,
                    route.complexity,
                    route.pipeline,
                    dataset_id,
                    file_name,
                ),
            )

    def update_dataset_chunk_count(self, dataset_id: str):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(chunk_count),0) as total FROM documents "
                "WHERE dataset_id=? AND status='INDEXED'",
                (dataset_id,),
            ).fetchone()
            conn.execute(
                "UPDATE datasets SET chunk_count=? WHERE id=?",
                (row["total"] if row else 0, dataset_id),
            )

    def get_pending_files(self, dataset_id: str, limit: int | None = None) -> List[str]:
        sql = (
            "SELECT file_name FROM documents WHERE dataset_id=? AND status='PENDING' "
            "ORDER BY "
            "CASE WHEN complexity='needs_ocr' OR pipeline='markdown_needs_ocr' THEN 1 ELSE 0 END, "
            "COALESCE(NULLIF(file_size, 0), 9223372036854775807), file_name"
        )
        params: list[Any] = [dataset_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [r["file_name"] for r in rows]

    def indexed_files_with_counts(self, dataset_id: str) -> List[tuple[str, int]]:
        """INDEXED-документы датасета с их chunk_count — для сверки с Qdrant (reconcile)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT file_name, COALESCE(chunk_count, 0) AS cc FROM documents "
                "WHERE dataset_id=? AND status='INDEXED'",
                (dataset_id,),
            ).fetchall()
        return [(r["file_name"], int(r["cc"])) for r in rows]

    def dataset_integrity_rows(self, dataset_id: str) -> list[dict[str, Any]]:
        """Source and index metadata used by the explicit dataset integrity audit."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, file_name, status, COALESCE(file_hash, '') AS file_hash, "
                "COALESCE(file_mtime, 0) AS file_mtime, COALESCE(file_size, 0) AS file_size, "
                "COALESCE(chunk_count, 0) AS chunk_count, COALESCE(source_path, '') AS source_path "
                "FROM documents WHERE dataset_id=? ORDER BY file_name",
                (dataset_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_document_source_fingerprint(
        self,
        dataset_id: str,
        file_name: str,
        *,
        file_hash: str,
        file_mtime: float,
        file_size: int,
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET file_hash=?, file_mtime=?, file_size=? "
                "WHERE dataset_id=? AND file_name=?",
                (file_hash, file_mtime, file_size, dataset_id, file_name),
            )

    def lexical_integrity_projection(self, dataset_id: str) -> dict[str, Any]:
        """Return exact lexical/FTS point ids by file without invoking retrieval."""
        with self._get_conn() as conn:
            lexical_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='lexical_chunks'"
            ).fetchone()
            fts_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='lexical_chunks_fts'"
            ).fetchone()
            if not lexical_exists:
                return {"available": False, "fts_available": bool(fts_exists), "files": {}, "fts_ids": set()}
            rows = conn.execute(
                "SELECT doc_name, point_id FROM lexical_chunks "
                "WHERE collection=? AND dataset_id=?",
                (rag_collection_name(), dataset_id),
            ).fetchall()
            files: dict[str, set[str]] = {}
            for row in rows:
                files.setdefault(str(row["doc_name"] or ""), set()).add(str(row["point_id"] or ""))
            fts_ids: set[int] = set()
            if fts_exists:
                fts_ids = {
                    int(row["id"])
                    for row in conn.execute(
                        "SELECT c.id FROM lexical_chunks c "
                        "JOIN lexical_chunks_fts f ON f.rowid=c.id "
                        "WHERE c.collection=? AND c.dataset_id=?",
                        (rag_collection_name(), dataset_id),
                    ).fetchall()
                }
            lexical_ids = {
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM lexical_chunks WHERE collection=? AND dataset_id=?",
                    (rag_collection_name(), dataset_id),
                ).fetchall()
            }
        return {
            "available": True,
            "fts_available": bool(fts_exists),
            "files": files,
            "lexical_ids": lexical_ids,
            "fts_ids": fts_ids,
        }

    def rebuild_lexical_fts(self) -> None:
        from proxy.services.lexical_index_service import LexicalIndex

        with LexicalIndex(self.db_path).connect() as conn:
            conn.execute("INSERT INTO lexical_chunks_fts(lexical_chunks_fts) VALUES('rebuild')")

    def set_documents_pending(self, dataset_id: str, file_names: set[str]) -> int:
        if not file_names:
            return 0
        names = sorted(file_names)
        placeholders = ",".join("?" for _ in names)
        with self._get_conn() as conn:
            cur = conn.execute(
                f"UPDATE documents SET status='PENDING', last_error='', stage='', chunk_count=0 "
                f"WHERE dataset_id=? AND file_name IN ({placeholders})",
                (dataset_id, *names),
            )
            return int(cur.rowcount)

    def set_documents_missing(self, dataset_id: str, file_names: set[str]) -> int:
        if not file_names:
            return 0
        names = sorted(file_names)
        placeholders = ",".join("?" for _ in names)
        with self._get_conn() as conn:
            cur = conn.execute(
                f"UPDATE documents SET status='MISSING', last_error='Исходный файл не найден', "
                f"stage='', chunk_count=0 WHERE dataset_id=? AND file_name IN ({placeholders})",
                (dataset_id, *names),
            )
            return int(cur.rowcount)

    def get_pending_files_with_paths(
        self, dataset_id: str, limit: int | None = None
    ) -> List[tuple]:
        """Как get_pending_files, но (file_name, source_path).

        source_path != "" — внешний in-place источник; _sync_parse читает его по
        абсолютному пути вместо storage/datasets/{id}/{file_name}.
        """
        sql = (
            "SELECT file_name, COALESCE(source_path, '') AS source_path FROM documents "
            "WHERE dataset_id=? AND status='PENDING' "
            "ORDER BY "
            "CASE WHEN complexity='needs_ocr' OR pipeline='markdown_needs_ocr' THEN 1 ELSE 0 END, "
            "COALESCE(NULLIF(file_size, 0), 9223372036854775807), file_name"
        )
        params: list[Any] = [dataset_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(r["file_name"], r["source_path"]) for r in rows]

    def health_snapshot(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            dataset_rows = conn.execute("""
                SELECT d.id, d.name, d.status, d.chunk_count,
                       COALESCE(d.dataset_scope, 'user') AS dataset_scope,
                       COALESCE(d.module_id, '') AS module_id,
                       COUNT(doc.id) AS total_files,
                       SUM(CASE WHEN doc.status='INDEXED' THEN 1 ELSE 0 END) AS indexed_files,
                       SUM(CASE WHEN doc.status='PENDING' THEN 1 ELSE 0 END) AS pending_files,
                       SUM(CASE WHEN doc.status='ERROR' THEN 1 ELSE 0 END) AS error_files,
                       SUM(CASE WHEN doc.status='MISSING' THEN 1 ELSE 0 END) AS missing_files,
                       COALESCE(SUM(CASE WHEN doc.status='INDEXED' THEN doc.chunk_count ELSE 0 END), 0) AS indexed_chunks
                FROM datasets d
                LEFT JOIN documents doc ON d.id = doc.dataset_id
                GROUP BY d.id
                ORDER BY d.name
            """).fetchall()
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS files, COALESCE(SUM(chunk_count),0) AS chunks "
                "FROM documents GROUP BY status"
            ).fetchall()
            route_rows = conn.execute("""
                SELECT COALESCE(NULLIF(domain, ''), 'UNCLASSIFIED') AS domain,
                       COUNT(*) AS files,
                       COALESCE(SUM(chunk_count),0) AS chunks
                FROM documents
                GROUP BY COALESCE(NULLIF(domain, ''), 'UNCLASSIFIED')
                ORDER BY files DESC
            """).fetchall()
            doc_type_rows = conn.execute("""
                SELECT COALESCE(NULLIF(doc_type, ''), 'UNCLASSIFIED') AS doc_type,
                       COUNT(*) AS files,
                       COALESCE(SUM(chunk_count),0) AS chunks
                FROM documents
                GROUP BY COALESCE(NULLIF(doc_type, ''), 'UNCLASSIFIED')
                ORDER BY files DESC
            """).fetchall()

        datasets = [
            {
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "files": row["total_files"] or 0,
                "indexed_files": row["indexed_files"] or 0,
                "pending_files": row["pending_files"] or 0,
                "error_files": row["error_files"] or 0,
                "missing_files": row["missing_files"] or 0,
                "chunks": row["indexed_chunks"] or 0,
                "dataset_scope": row["dataset_scope"] or "user",
                "module_id": row["module_id"] or "",
            }
            for row in dataset_rows
        ]
        totals = {
            "datasets": len(datasets),
            "files": sum(item["files"] for item in datasets),
            "indexed_files": sum(item["indexed_files"] for item in datasets),
            "pending_files": sum(item["pending_files"] for item in datasets),
            "error_files": sum(item["error_files"] for item in datasets),
            "missing_files": sum(item["missing_files"] for item in datasets),
            "chunks": sum(item["chunks"] for item in datasets),
        }
        return {
            "status": self._rag_status(totals, datasets),
            "totals": totals,
            "by_status": {
                row["status"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in status_rows
            },
            "by_domain": {
                row["domain"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in route_rows
            },
            "by_doc_type": {
                row["doc_type"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in doc_type_rows
            },
            "datasets": datasets,
        }

    def _rag_status(self, totals: Dict[str, int], datasets: list[dict]) -> str:
        if totals["files"] == 0:
            return "empty"
        if totals["indexed_files"] == 0:
            return "not_indexed"
        if totals["pending_files"] or totals["error_files"] or totals.get("missing_files", 0):
            return "degraded"
        if any(dataset["status"] not in ("COMPLETED", "IDLE") for dataset in datasets):
            return "degraded"
        return "ready"

    def insert_structured_rules(self, rules: List[Dict[str, Any]]) -> None:
        if not rules:
            return
        with self._get_conn() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO structured_rules (
                    id, document_id, file_key, chunk_id, subject, parameter, operator, value, unit, condition, char_start, char_end
                ) VALUES (
                    :id, :document_id, :file_key, :chunk_id, :subject, :parameter, :operator, :value, :unit, :condition, :char_start, :char_end
                )
            """, rules)

    def get_structured_rules(self, document_id: Optional[str] = None, file_key: Optional[str] = None) -> List[sqlite3.Row]:
        query = "SELECT * FROM structured_rules WHERE 1=1"
        params = []
        if document_id:
            query += " AND document_id = ?"
            params.append(document_id)
        if file_key:
            query += " AND file_key = ?"
            params.append(file_key)
        
        with self._get_conn() as conn:
            return conn.execute(query, params).fetchall()

    def clear_structured_rules(self, file_key: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM structured_rules WHERE file_key = ?", (file_key,))


# ── Основной адаптер ──────────────────────────────────────────────────────────

class QdrantLlamaIndexAdapter(RAGBackend):
    def __init__(
        self,
        qdrant_url:       str,
        mlx_url:       str,
        embed_model_name: str,
        content_dir:      str = "./storage/datasets",
    ):
        self.content_dir     = Path(content_dir)
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.db              = MetaDB()
        self.db.ensure_system_datasets()
        recovered = self.db.recover_interrupted_parsing()
        if recovered:
            logger.info("[INIT] Recovered %s interrupted parsing dataset(s)", recovered)
        # check_compatibility=False: пропустить версии-чек клиент↔сервер. Иначе на Windows он
        # вис («Failed to obtain server version») и держал /api/health/ретрив десятками секунд,
        # когда Qdrant недоступен (#2). Skip → операции фейлятся быстро, версия не блокирует старт.
        self.aclient         = qdrant_client.AsyncQdrantClient(
            url=qdrant_url, timeout=60.0, check_compatibility=False)
        self.qdrant_url      = qdrant_url
        self.embed           = EmbedClient(mlx_url, model=embed_model_name.replace(":latest", ""))
        # Отдельный эмбеддер для ПАРСА (опц.): EMBED_URL_PARSE → парс-эмбеддинги уходят на
        # ВТОРОЙ инстанс, не голодая чат-эмбеддинг на основном :8080 во время индексации.
        # Дефолт = основной URL (ноль изменений, пока env не задан). Активация: поднять второй
        # MLX-эмбеддер на альт-порту + EMBED_URL_PARSE=http://127.0.0.1:<порт>.
        _parse_url = os.getenv("EMBED_URL_PARSE", "").strip() or mlx_url
        self.embed_parse     = EmbedClient(_parse_url, model=embed_model_name.replace(":latest", ""))
        if _parse_url != mlx_url:
            logger.info("[INIT] парс-эмбеддер на отдельном инстансе: %s", _parse_url)
        self.collection_name = rag_collection_name()
        self.vector_size     = rag_vector_size()
        self._collection_ready = False
        self._collection_lock  = asyncio.Lock()

    # ── Служебные ─────────────────────────────────────────────────────────────

    async def _ensure_collection(self):
        if self._collection_ready:
            return
        async with self._collection_lock:
            if self._collection_ready:
                return
            created = False
            collection_info = None
            try:
                collection_info = await self.aclient.get_collection(self.collection_name)
            except Exception:
                logger.info(f"[INIT] Создаём коллекцию {self.collection_name}")
            if collection_info is not None and _qdrant_schema_mode() == "named":
                compatible, points_count = _named_collection_layout(
                    collection_info,
                    vector_size=self.vector_size,
                )
                if not compatible:
                    if points_count:
                        raise EmbeddingContractError(
                            f"collection {self.collection_name} has {points_count} points in an "
                            "incompatible vector schema; explicit migration is required"
                        )
                    logger.warning(
                        "[INIT] Пересоздаём пустую legacy-коллекцию %s как named dense+sparse",
                        self.collection_name,
                    )
                    await self.aclient.delete_collection(self.collection_name)
                    collection_info = None
                elif index_contract_status().get("status") == "missing":
                    # A packaged/clean Windows baseline may already contain the
                    # canonical named collection while its small sidecar file is
                    # absent. Adopt it only when the collection is empty or every
                    # existing point proves the current embedding identity.
                    matching_count = 0
                    if points_count:
                        expected_fingerprint = point_embedding_fingerprint()
                        matching = await self.aclient.count(
                            collection_name=self.collection_name,
                            count_filter=models.Filter(
                                must=[
                                    models.FieldCondition(
                                        key="embedding_fingerprint",
                                        match=models.MatchValue(value=expected_fingerprint),
                                    )
                                ]
                            ),
                            exact=True,
                        )
                        matching_count = int(matching.count or 0)
                    adopt = _can_adopt_missing_contract(
                        points_count=points_count,
                        matching_fingerprint_count=matching_count,
                    )
                    if adopt:
                        write_index_contract(replace=False)
                        logger.info(
                            "[INIT] Adopted compatible named collection %s (%s points) into index contract",
                            self.collection_name,
                            points_count,
                        )
            if collection_info is None:
                if _qdrant_schema_mode() == "named":
                    await self.aclient.create_collection(
                        collection_name=self.collection_name,
                        vectors_config={
                            _dense_vector_name(): models.VectorParams(
                                size=self.vector_size,
                                distance=models.Distance.COSINE,
                            )
                        },
                        sparse_vectors_config={
                            _sparse_vector_name(): models.SparseVectorParams(
                                modifier=models.Modifier.IDF,
                            )
                        },
                    )
                else:
                    await self.aclient.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=models.VectorParams(
                            size=self.vector_size, distance=models.Distance.COSINE
                        ),
                    )
                created = True
            if created or (
                collection_info is not None
                and _named_collection_layout(collection_info, vector_size=self.vector_size)[1] == 0
            ):
                try:
                    write_index_contract(replace=False)
                except FileExistsError:
                    # A pre-existing sidecar is validated below; never overwrite it
                    # implicitly during startup.
                    pass
            # Payload-индексы под фильтрованный поиск (retrieve фильтрует по dataset_id и
            # file_name). БЕЗ индекса query_points с фильтром проверяет фильтр по ВСЕМ точкам
            # (~1.6с на 179k) — с индексом ~30мс. create_payload_index идемпотентен (повторный
            # вызов — no-op/обновление). Best-effort: сбой не должен блокировать старт.
            for _field in (
                "dataset_id",
                "file_name",
                "embedding_fingerprint",
                "mail_account_id",
                "mail_thread_key",
                "mail_registry_message_id",
            ):
                try:
                    await self.aclient.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=_field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        # Qdrant may serialize collection mutations immediately
                        # after a clean collection was created.  Waiting for
                        # every payload index made FastAPI startup look dead for
                        # minutes even though the operation was safely queued.
                        wait=False,
                    )
                except Exception as _idx_err:  # noqa: BLE001
                    logger.warning("[INIT] payload-индекс %s: %s", _field, _idx_err)
            self._collection_ready = True

    @staticmethod
    def _assert_dense_index_contract() -> None:
        status = index_contract_status()
        if not status.get("compatible"):
            raise EmbeddingContractError(
                "index contract "
                f"{status.get('status')}: expected={status.get('expected_fingerprint', '')} "
                f"actual={status.get('actual_fingerprint', '') or 'none'}"
            )

    async def health(self) -> bool:
        try:
            await self._ensure_collection()
            return True
        except Exception:
            return False

    async def health_snapshot(self) -> Dict[str, Any]:
        ok = await self.health()
        snapshot = self.db.health_snapshot()
        snapshot["qdrant"] = {"ok": ok, "collection": self.collection_name}
        contract = index_contract_status()
        snapshot["index_contract"] = contract
        snapshot["dense_available"] = bool(ok and contract.get("compatible"))
        if ok and not contract.get("compatible"):
            snapshot["status"] = "degraded"
        if ok:
            try:
                collection = await self.aclient.get_collection(self.collection_name)
                points = collection.points_count or 0
                snapshot["qdrant"]["points"] = points
                expected_chunks = snapshot.get("totals", {}).get("chunks") or 0
                snapshot["qdrant"]["points_match_sqlite_chunks"] = points == expected_chunks
                if points != expected_chunks:
                    snapshot["qdrant"]["mismatch"] = {
                        "sqlite_chunks": expected_chunks,
                        "qdrant_points": points,
                    }
                    snapshot["status"] = "degraded"
            except Exception as error:
                snapshot["qdrant"].update({"ok": False, "error": str(error)})
        return snapshot

    # ── RAGBackend interface ───────────────────────────────────────────────────

    async def list_datasets(self) -> List[DatasetInfo]:
        return self.db.list_datasets()

    async def create_dataset(self, name: str) -> str:
        return self.db.create_dataset(name)

    async def set_dataset_sensitivity(self, dataset_id: str, sensitivity: str) -> None:
        self.db.set_dataset_sensitivity(dataset_id, sensitivity)

    async def set_dataset_group(self, dataset_id: str, group_name: str) -> None:
        self.db.set_dataset_group(dataset_id, group_name)

    async def upload_file(self, dataset_id: str, file_path: Path, relative_path: Optional[str] = None) -> str:
        dest_dir  = self.content_dir / dataset_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        rel_name = relative_path or file_path.name
        rel_path = Path(rel_name)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"unsafe relative path: {rel_name}")
        dest_file = dest_dir / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        stat  = file_path.stat() if file_path.exists() else None
        mtime = stat.st_mtime if stat else 0.0
        size  = stat.st_size  if stat else 0

        if file_path.exists() and file_path != dest_file:
            await asyncio.to_thread(shutil.copy2, file_path, dest_file)

        doc_id, _, needs_reindex = self.db.add_document(
            dataset_id, rel_path.as_posix(), file_mtime=mtime, file_size=size
        )
        try:
            route_source = dest_file if dest_file.exists() else file_path
            route = route_document(route_source)
            if needs_reindex:
                self.db.update_document_status(dataset_id, rel_path.as_posix(), "PENDING", 0, route=route)
            else:
                self.db.update_document_route(dataset_id, rel_path.as_posix(), route)
        except Exception as error:
            logger.warning("[DOC_ROUTE] upload classification skipped for %s: %s", rel_path.as_posix(), error)
        return doc_id

    async def mark_document_error(self, dataset_id: str, document_id: str, error: str) -> None:
        await asyncio.to_thread(self.db.mark_document_error, dataset_id, document_id, error)

    async def register_external_file(self, dataset_id: str, source_path: Path, file_name: str) -> str:
        """Регистрирует внешний файл как источник БЕЗ копии в storage.

        Документ остаётся в своей папке; в storage/datasets/{id} попадают только
        производные (Parquet/_parquet). file_name — ключ дока (rel-путь под корнем),
        source_path — абсолютный путь, по которому _sync_parse прочитает файл.
        """
        rel = Path(file_name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"unsafe file_name: {file_name}")
        # Каталог датасета нужен для производных (Parquet) и для прохода _sync_parse.
        (self.content_dir / dataset_id).mkdir(parents=True, exist_ok=True)

        src = Path(source_path)
        stat = src.stat() if src.exists() else None
        mtime = stat.st_mtime if stat else 0.0
        size = stat.st_size if stat else 0

        doc_id, _, needs_reindex = self.db.add_document(
            dataset_id, rel.as_posix(), file_mtime=mtime, file_size=size, source_path=str(src),
        )
        try:
            route = route_document(src)
            if needs_reindex:
                self.db.update_document_status(dataset_id, rel.as_posix(), "PENDING", 0, route=route)
            else:
                self.db.update_document_route(dataset_id, rel.as_posix(), route)
        except Exception as error:
            logger.warning("[EXT_DOC] classification skipped for %s: %s", rel.as_posix(), error)
        return doc_id

    async def parse_dataset(self, dataset_id: str, limit: int | None = None) -> Dict[str, Any]:
        if limit is None and os.getenv(ALLOW_UNBOUNDED_PARSE, "").lower() not in ("1", "true", "yes"):
            return {
                "status": "rejected",
                "error": (
                    "unbounded parse is disabled; use parse_dataset(..., limit=N) "
                    f"or set {ALLOW_UNBOUNDED_PARSE}=1 explicitly"
                ),
            }
        await self._ensure_collection()
        self._assert_dense_index_contract()
        self.db.update_dataset_status(dataset_id, "PARSING")
        res = await asyncio.to_thread(self._sync_parse, dataset_id, limit)
        status = "COMPLETED" if res.get("status") == "completed" else "ERROR"
        if res.get("errors", 0) > 0:
            status = "ERROR"
        if res.get("remaining_pending", 0) > 0 and status == "COMPLETED":
            status = "IDLE" if limit is not None else "PARSING"
        self.db.update_dataset_status(dataset_id, status)
        return res

    def _sync_parse(self, dataset_id: str, limit: int | None = None) -> Dict[str, Any]:
        """
        Синхронный парсинг в threadpool.
        Батч-эмбеддинги: 32 чанка за запрос вместо по одному.
        """
        import time as _t
        t0 = _t.time()
        timings = {
            "delete_sec": 0.0,
            "route_sec": 0.0,
            "convert_sec": 0.0,
            "chunk_sec": 0.0,
            "embed_sec": 0.0,
            "upsert_sec": 0.0,
            "count_sec": 0.0,
            "cache_sec": 0.0,
            "db_sec": 0.0,
        }

        def _add_timing(key: str, started: float) -> None:
            timings[key] = timings.get(key, 0.0) + (_t.time() - started)

        data_dir = self.content_dir / dataset_id
        if not data_dir.exists():
            return {"status": "error", "msg": "dir missing"}

        md_parser = MarkdownNodeParser()
        # W2.1 (ADR-7): чанкинг в токенах эмбеддера (RAG_CHUNK_UNIT=chars вернёт символы).
        _chunking = chunking_config()
        splitter = StructureAwareSplitter(
            chunk_size=_chunking["chunk_size"],
            chunk_overlap=_chunking["chunk_overlap"],
            len_fn=_chunking["len_fn"],
        )
        logger.info(
            "[CHUNK] unit=%s size=%s overlap=%s",
            _chunking["unit"], _chunking["chunk_size"], _chunking["chunk_overlap"],
        )

        try:
            # source_path != "" → внешний in-place источник (читается по абсолютному
            # пути, без копии в storage). get_pending_files_with_paths опционален —
            # старые/стабовые БД дают только имена (всё внутреннее).
            get_pairs = getattr(self.db, "get_pending_files_with_paths", None)
            if get_pairs is not None:
                pending_pairs = list(get_pairs(dataset_id, limit=limit))
            else:
                pending_pairs = [(name, "") for name in self.db.get_pending_files(dataset_id, limit=limit)]
            pending_names = {name for name, _ in pending_pairs}
            external_sources = {name: src for name, src in pending_pairs if src}
            all_files     = [
                f for f in data_dir.rglob("*")
                if f.is_file() and "_parquet" not in f.relative_to(data_dir).parts
            ]

            if not pending_names:
                return {
                    "status": "completed",
                    "chunks": 0,
                    "files_parsed": 0,
                    "files_skipped": len(all_files),
                    "remaining_pending": 0,
                    "errors": 0,
                    "elapsed_sec": 0,
                }

            sync_qdrant = qdrant_client.QdrantClient(
                url=self.qdrant_url,
                timeout=60.0,
                check_compatibility=False,  # #2: версии-чек вис на Windows при недоступном Qdrant
            )

            # Внутренние (скопированные в storage) файлы: матчинг по относительному
            # пути и по имени файла для совместимости со старыми записями БД (f.name).
            internal_pending = pending_names - set(external_sources)
            exact_pending_names = {
                str(f.relative_to(data_dir))
                for f in all_files
                if str(f.relative_to(data_dir)) in internal_pending
            }
            legacy_pending_names = internal_pending - exact_pending_names
            # Единый список к индексации: (путь, file_key, db_file_key). file_key — ключ
            # в Qdrant/правилах/контексте; db_file_key — ключ строки documents.file_name.
            files_to_parse: list[tuple[Path, str, str]] = []
            for f in all_files:
                rel = f.relative_to(data_dir).as_posix()
                if rel in internal_pending:
                    files_to_parse.append((f, rel, rel))
                elif f.name in legacy_pending_names:
                    files_to_parse.append((f, rel, f.name))
            internal_count = len(files_to_parse)
            # Внешние источники — по абсолютному пути; file_key == db_file_key == имя дока.
            for name, src in external_sources.items():
                files_to_parse.append((Path(src), name, name))

            total     = len(files_to_parse)
            total_all = len(all_files)
            logger.info(
                f"[PARSE] {total}/{total_all} файлов к индексации (внешних in-place: {len(external_sources)})"
            )

            if total == 0:
                return {"status": "completed", "chunks": 0, "skipped": total_all}

            total_chunks = 0
            errors       = 0
            embedding_cache_hits = 0
            embedded_chunks = 0
            embedding_descriptor = _embedding_cache_descriptor()
            embedding_fingerprint = _embedding_cache_fingerprint(embedding_descriptor)

            # W1.4: конвейер — пока текущий файл эмбеддится/апсертится, следующий конвертируется
            # в фоновом потоке. OCR-файлы конвертируются в основном потоке (VLM не гоняем
            # параллельно с эмбеддером).
            convert_pool = (
                ThreadPoolExecutor(max_workers=1, thread_name_prefix="les-convert")
                if PARSE_PREFETCH and total > 1
                else None
            )
            _set_stage = getattr(self.db, "update_document_stage", None)

            def _stage(db_key: str, stage: str) -> None:
                if _set_stage is None:
                    return
                try:
                    _set_stage(dataset_id, db_key, stage)
                except Exception:
                    pass

            def _delete_file_lexical(file_key: str) -> None:
                delete_lexical = getattr(self, "_sync_delete_file_lexical", None)
                if delete_lexical is not None:
                    delete_lexical(dataset_id, file_key)

            def _upsert_file_lexical(points: list[Any]) -> None:
                upsert_lexical = getattr(self, "_sync_upsert_file_lexical", None)
                if upsert_lexical is not None:
                    upsert_lexical(points)

            def _submit_convert(index: int):
                f, fk, _dbk = files_to_parse[index]
                local_timings: dict = {}
                future = convert_pool.submit(
                    QdrantLlamaIndexAdapter._convert_file, self, f, data_dir, fk, dataset_id,
                    md_parser, splitter, local_timings, False,
                )
                return future, local_timings

            next_convert = _submit_convert(0) if convert_pool else None

            for i, (file_path, file_key, db_file_key) in enumerate(files_to_parse, 1):
                if i % 50 == 0 or i == total:
                    logger.info(f"[PARSE] {i}/{total} ({_t.time()-t0:.0f}с)")
                try:
                    _stage(db_file_key, "CONVERT")
                    if next_convert is not None:
                        future, local_timings = next_convert
                        try:
                            route, file_nodes = future.result(timeout=PARSE_FILE_TIMEOUT)
                        except FuturesTimeoutError:
                            # Зависший конвертер бросаем вместе с пулом; индексация продолжается.
                            convert_pool.shutdown(wait=False, cancel_futures=True)
                            convert_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="les-convert")
                            raise RuntimeError(
                                f"convert timeout: >{PARSE_FILE_TIMEOUT:.0f}s (поток конвертации брошен)"
                            )
                        finally:
                            for key, val in local_timings.items():
                                timings[key] = timings.get(key, 0.0) + val
                            next_convert = _submit_convert(i) if i < total else None
                        if file_nodes is None:
                            # OCR-конвейер: конвертируем синхронно в основном потоке.
                            route, file_nodes = QdrantLlamaIndexAdapter._convert_file(
                                self, file_path, data_dir, file_key, dataset_id,
                                md_parser, splitter, timings, True,
                            )
                    else:
                        route, file_nodes = QdrantLlamaIndexAdapter._convert_file(
                            self, file_path, data_dir, file_key, dataset_id,
                            md_parser, splitter, timings, True,
                        )

                    # One final invariant for every parser and node type. Parser-
                    # specific chunkers may improve boundaries, but none may bypass
                    # the actual embedding tokenizer budget or content sanitation.
                    phase_start = _t.time()
                    file_nodes = QdrantLlamaIndexAdapter._finalize_embedding_nodes(
                        file_nodes or [],
                        chunking=_chunking,
                    )
                    _add_timing("chunk_sec", phase_start)

                    # Native RRF is a corpus-wide invariant: a named-schema
                    # point is never allowed to enter the collection without
                    # its sparse companion.  Validate before deleting the old
                    # file points, so an invalid replacement cannot erase a
                    # previously usable document.
                    if _qdrant_schema_mode() == "named":
                        from backend.inference.bm25_sparse import encode_bm25

                        searchable_nodes = []
                        for node in file_nodes:
                            sparse_vec = encode_bm25(str(node["text"]))
                            if not sparse_vec:
                                logger.warning(
                                    "Skipping non-searchable node with empty sparse vector: file=%s doc_id=%s",
                                    file_key,
                                    node.get("doc_id", ""),
                                )
                                continue
                            node["_rrf_sparse_vector"] = sparse_vec
                            searchable_nodes.append(node)
                        file_nodes = searchable_nodes

                    phase_start = _t.time()
                    existing_vectors = (
                        self._sync_existing_file_vectors_by_hash(
                            sync_qdrant,
                            dataset_id,
                            file_key,
                            embedding_fingerprint,
                        )
                        if CHUNK_HASH_CACHE and hasattr(self, "_sync_existing_file_vectors_by_hash")
                        else {}
                    )
                    _add_timing("cache_sec", phase_start)

                    # W1.4: старые точки удаляем ПОСЛЕ успешной конвертации — сбой
                    # конвертации больше не оставляет файл без старого индекса.
                    phase_start = _t.time()
                    self._sync_delete_file_points(sync_qdrant, dataset_id, file_key)
                    _delete_file_lexical(file_key)
                    _add_timing("delete_sec", phase_start)

                    if not file_nodes:
                        phase_start = _t.time()
                        self.db.update_document_status(dataset_id, db_file_key, "INDEXED", 0, route=route)
                        _add_timing("db_sec", phase_start)
                        continue

                    _apply_context_metadata_to_nodes(file_nodes, dataset_id, file_key)

                    # Стираем старые правила для этого файла перед переиндексацией
                    self.db.clear_structured_rules(file_key)

                    # Извлекаем структурированные правила для нормативных и сложных документов
                    if route and route.doc_type in ("NORMATIVE", "SPEC"):
                        try:
                            from .rules_extractor import StructuredRulesExtractor
                            extractor = StructuredRulesExtractor()
                            extracted_rules = []
                            for node in file_nodes:
                                chunk_rules = extractor.extract_rules(
                                    text=node["text"],
                                    document_id=dataset_id,
                                    file_key=file_key,
                                    chunk_id=node["doc_id"]
                                )
                                if chunk_rules:
                                    extracted_rules.extend(chunk_rules)

                            if extracted_rules:
                                self.db.insert_structured_rules(extracted_rules)
                                logger.info(f"[OCR_RULES] Извлечено структурированных правил из {file_key}: {len(extracted_rules)}")
                        except Exception as rule_err:
                            logger.error(f"[OCR_RULES] Ошибка извлечения структурированных правил для {file_key}: {rule_err}", exc_info=True)

                    _stage(db_file_key, "EMBED")
                    # Батч-эмбеддинги по EMBED_BATCH чанков. Upsert начинаем только
                    # после успешного embedding всех чанков файла, чтобы не оставлять
                    # частичный индекс при сбое середины документа.
                    points = []
                    for batch_start in range(0, len(file_nodes), EMBED_BATCH):
                        batch = file_nodes[batch_start:batch_start + EMBED_BATCH]
                        batch_vectors: list[list[float] | None] = [None] * len(batch)
                        miss_indexes: list[int] = []
                        miss_texts: list[str] = []
                        for local_idx, node in enumerate(batch):
                            payload = node.get("payload") or {}
                            content_hash = str(payload.get("content_hash") or _content_hash(str(node["text"])))
                            cached_vector = existing_vectors.get(content_hash)
                            if cached_vector is not None:
                                batch_vectors[local_idx] = cached_vector
                                embedding_cache_hits += 1
                            else:
                                miss_indexes.append(local_idx)
                                miss_texts.append(str(node["text"]))

                        if miss_texts:
                            phase_start = _t.time()
                            # Парс-эмбеддер (EMBED_URL_PARSE); дефолт/тесты-моки → основной self.embed.
                            _parse_embed = getattr(self, "embed_parse", None) or self.embed
                            vectors = _parse_embed.encode_sync(miss_texts)
                            _add_timing("embed_sec", phase_start)
                            if len(vectors) != len(miss_texts):
                                raise RuntimeError(
                                    f"embedding count mismatch: got {len(vectors)}, expected {len(miss_texts)}"
                                )
                            embedded_chunks += len(vectors)
                            for local_idx, vec in zip(miss_indexes, vectors):
                                batch_vectors[local_idx] = vec

                        for node, vec in zip(batch, batch_vectors):
                            if vec is None:
                                raise RuntimeError("missing embedding vector after cache/embed merge")
                            payload = dict(node.get("payload") or {})
                            payload.update({
                                "text":       node["text"],
                                "dataset_id": dataset_id,
                                "doc_id":     node.get("doc_id") or str(uuid.uuid4()),
                                "file_name":  file_key,
                                "embedding_fingerprint": embedding_fingerprint,
                                "embedding_backend": embedding_descriptor.get("backend", ""),
                                "embedding_model_id": embedding_descriptor.get("model_id", ""),
                                "embedding_profile": embedding_descriptor.get("profile", ""),
                                "embedding_coreml_model": embedding_descriptor.get("coreml_model", ""),
                                "embedding_coreml_seq_len": embedding_descriptor.get("coreml_seq_len", ""),
                                "embedding_coreml_compute_units": embedding_descriptor.get("coreml_compute_units", ""),
                                "embedding_coreml_fallback": embedding_descriptor.get("coreml_fallback", ""),
                            })
                            point_vector: Any = vec
                            if _qdrant_schema_mode() == "named":
                                sparse_vec = node.pop("_rrf_sparse_vector", None)
                                if not sparse_vec:
                                    raise RuntimeError("missing prevalidated sparse vector")
                                point_vector = {
                                    _dense_vector_name(): vec,
                                    _sparse_vector_name(): models.SparseVector(
                                        indices=list(sparse_vec.keys()),
                                        values=list(sparse_vec.values()),
                                    ),
                                }
                            points.append(models.PointStruct(
                                id=str(uuid.uuid4()),
                                vector=point_vector,
                                payload=payload,
                            ))

                    _stage(db_file_key, "UPSERT")
                    # Upsert батчами после успешного embedding всего файла.
                    for point_start in range(0, len(points), UPSERT_BATCH):
                        phase_start = _t.time()
                        sync_qdrant.upsert(
                            collection_name=self.collection_name,
                            points=points[point_start:point_start + UPSERT_BATCH],
                        )
                        _add_timing("upsert_sec", phase_start)
                    _upsert_file_lexical(points)

                    file_chunk_count = len(file_nodes)
                    # W1.2: exact-count в Qdrant — дорогая проверка; выборочно (каждый N-й файл
                    # и последний), а не после каждого. Upsert-ошибки и так поднимают исключение.
                    if i % VERIFY_POINTS_EVERY == 0 or i == total:
                        phase_start = _t.time()
                        indexed_points = self._sync_count_file_points(sync_qdrant, dataset_id, file_key)
                        _add_timing("count_sec", phase_start)
                        if indexed_points != file_chunk_count:
                            raise RuntimeError(
                                f"qdrant point count mismatch: got {indexed_points}, expected {file_chunk_count}"
                            )
                    total_chunks    += file_chunk_count
                    phase_start = _t.time()
                    self.db.update_document_status(
                        dataset_id, db_file_key, "INDEXED", file_chunk_count, route=route
                    )
                    try:
                        set_fingerprint = getattr(self.db, "set_document_source_fingerprint", None)
                        if callable(set_fingerprint):
                            stat = file_path.stat()
                            set_fingerprint(
                                dataset_id,
                                db_file_key,
                                file_hash=_sha256_file(file_path),
                                file_mtime=stat.st_mtime,
                                file_size=stat.st_size,
                            )
                    except OSError as fingerprint_error:
                        logger.warning(
                            "[INTEGRITY] source fingerprint skipped %s: %s",
                            db_file_key,
                            fingerprint_error,
                        )
                    _add_timing("db_sec", phase_start)

                except UnsupportedIndexingSourceError as file_err:
                    logger.info("[PARSE] SKIPPED %s: %s", file_key, file_err)
                    phase_start = _t.time()
                    self.db.update_document_status(
                        dataset_id, db_file_key, "SKIPPED", 0, last_error=str(file_err)
                    )
                    _add_timing("db_sec", phase_start)

                except Exception as file_err:
                    logger.error(f"[PARSE] ERROR {file_key}: {file_err}", exc_info=True)
                    try:
                        self._sync_delete_file_points(sync_qdrant, dataset_id, file_key)
                        _delete_file_lexical(file_key)
                    except Exception as cleanup_err:
                        logger.error("[PARSE] cleanup failed %s: %s", file_key, cleanup_err)
                    phase_start = _t.time()
                    self.db.update_document_status(
                        dataset_id, db_file_key, "ERROR", 0, last_error=str(file_err)
                    )
                    _add_timing("db_sec", phase_start)
                    errors += 1

            if convert_pool is not None:
                convert_pool.shutdown(wait=False, cancel_futures=True)

            phase_start = _t.time()
            self.db.update_dataset_chunk_count(dataset_id)
            remaining_pending = len(self.db.get_pending_files(dataset_id))
            _add_timing("db_sec", phase_start)
            elapsed = _t.time() - t0
            timings = {key: round(value, 3) for key, value in timings.items()}
            logger.info(
                f"[PARSE] DONE: {total} файлов, {total_chunks} чанков, "
                f"{errors} ошибок за {elapsed:.0f}с, осталось pending={remaining_pending}, "
                f"timings={timings}"
            )
            return {
                "status":       "completed",
                "chunks":       total_chunks,
                "files_parsed": total,
                "files_skipped": max(0, total_all - internal_count),
                "remaining_pending": remaining_pending,
                "errors":       errors,
                "embedding_cache_hits": embedding_cache_hits,
                "embedded_chunks": embedded_chunks,
                "elapsed_sec":  round(elapsed, 1),
                "timings":      timings,
            }

        except Exception as e:
            logger.error(f"[PARSE] FATAL: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    def _convert_file(
        self,
        file_path: Path,
        data_dir: Path,
        file_key: str,
        dataset_id: str,
        md_parser,
        splitter,
        timings: dict,
        allow_ocr: bool = True,
    ):
        """W1.4: стадия конвертации (route + nodes), вынесена для префетча в фоне.

        allow_ocr=False (префетч): OCR-файлы не конвертируем в фоне — возвращаем
        (route, None), основной поток выполнит конвертацию синхронно.
        """
        import time as _t

        def _add_timing(key: str, started: float) -> None:
            timings[key] = timings.get(key, 0.0) + (_t.time() - started)

        phase_start = _t.time()
        route = route_document(file_path)
        _add_timing("route_sec", phase_start)
        logger.info(
            "[DOC_ROUTE] %s domain=%s dataset=%s type=%s content=%s complexity=%s pipeline=%s",
            file_key,
            route.domain,
            route.dataset_name,
            route.doc_type,
            route.content_type,
            route.complexity,
            route.pipeline,
        )

        if _is_raw_cad_bim_source(file_path, route):
            raise UnsupportedIndexingSourceError(_raw_cad_bim_error(file_path))

        if route.pipeline == "markdown_needs_ocr" and not allow_ocr:
            return route, None

        if route.doc_type == "EMAIL":
            file_nodes = self._sync_mail_nodes(
                file_path, data_dir, file_key, dataset_id, splitter, route, timings
            )
        elif route.pipeline == "parquet":
            try:
                file_nodes = self._sync_table_nodes(file_path, data_dir, file_key, dataset_id, route, timings)
            except Exception as table_err:
                logger.warning(
                    "[PARQUET] fallback to markdown for %s: %s",
                    file_key,
                    table_err,
                )
                file_nodes = self._sync_markdown_nodes(
                    file_path, file_key, dataset_id, md_parser, splitter, route, timings
                )
        elif route.pipeline in ("markdown_pdf_tables", "markdown_needs_ocr"):
            file_nodes = self._sync_markdown_nodes(
                file_path, file_key, dataset_id, md_parser, splitter, route, timings
            )
            if (
                route.pipeline == "markdown_pdf_tables"
                and os.getenv("PDF_TABLE_EXTRACTION_ENABLED", "false").lower() == "true"
            ):
                try:
                    file_nodes.extend(self._sync_table_nodes(file_path, data_dir, file_key, dataset_id, route, timings))
                except Exception as table_err:
                    logger.warning(
                        "[PDF_TABLE] table extraction skipped for %s: %s",
                        file_key,
                        table_err,
                    )
        else:
            file_nodes = self._sync_markdown_nodes(
                file_path, file_key, dataset_id, md_parser, splitter, route, timings
            )
            if QdrantLlamaIndexAdapter._docx_table_extraction_enabled(file_path, route):
                try:
                    file_nodes.extend(self._sync_table_nodes(file_path, data_dir, file_key, dataset_id, route, timings))
                except Exception as table_err:
                    logger.warning(
                        "[DOCX_TABLE] table extraction skipped for %s: %s",
                        file_key,
                        table_err,
                    )
        return route, file_nodes

    def _file_filter(self, dataset_id: str, file_key: str) -> models.Filter:
        return models.Filter(must=[
            models.FieldCondition(
                key="file_name",
                match=models.MatchValue(value=file_key),
            ),
            models.FieldCondition(
                key="dataset_id",
                match=models.MatchValue(value=dataset_id),
            ),
        ])

    def _sync_delete_file_points(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
    ) -> None:
        sync_qdrant.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=self._file_filter(dataset_id, file_key)
            ),
            wait=True,
        )

    def _sync_delete_file_lexical(self, dataset_id: str, file_key: str) -> None:
        try:
            from proxy.services.lexical_index_service import LexicalIndex

            deleted = LexicalIndex().delete_file(
                self.collection_name,
                dataset_id=dataset_id,
                doc_name=file_key,
            )
            if deleted:
                logger.debug("[LEXICAL] удалены старые FTS-чанки %s/%s: %s", dataset_id, file_key, deleted)
        except Exception as error:  # noqa: BLE001
            logger.warning("[LEXICAL] cleanup skipped %s/%s: %s", dataset_id, file_key, error)

    @staticmethod
    def _lexical_rows_from_points(points: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            text = str(payload.get("text") or "")
            point_id = str(getattr(point, "id", "") or "")
            if not text.strip() or not point_id:
                continue
            rows.append({
                "point_id": point_id,
                "dataset_id": payload.get("dataset_id"),
                "doc_id": payload.get("doc_id"),
                "doc_name": payload.get("file_name") or payload.get("doc_name"),
                "text": text,
                "content_hash": payload.get("content_hash"),
                "chunk_ord": payload.get("chunk_ord"),
                "section_heading": payload.get("section_heading"),
                "parent_id": payload.get("parent_id"),
                "parent_ord": payload.get("parent_ord"),
                "child_ord": payload.get("child_ord"),
                "parent_heading": payload.get("parent_heading"),
                "context_before": payload.get("context_before"),
                "context_after": payload.get("context_after"),
                "context_kind": payload.get("context_kind"),
            })
        return rows

    def _sync_upsert_file_lexical(self, points: list[Any]) -> None:
        rows = self._lexical_rows_from_points(points)
        if not rows:
            return
        try:
            from proxy.services.lexical_index_service import LexicalIndex

            indexed = LexicalIndex().upsert_chunks(self.collection_name, rows)
            logger.debug("[LEXICAL] upsert FTS chunks collection=%s count=%s", self.collection_name, indexed)
        except Exception as error:  # noqa: BLE001
            logger.warning("[LEXICAL] upsert skipped collection=%s: %s", self.collection_name, error)

    def _sync_count_file_points(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
    ) -> int:
        result = sync_qdrant.count(
            collection_name=self.collection_name,
            count_filter=self._file_filter(dataset_id, file_key),
            exact=True,
        )
        return int(result.count)

    def reconcile_dataset(self, dataset_id: str) -> dict:
        """РЕКОНСАЙЛ MetaDB↔Qdrant: для каждого INDEXED-документа сверяет chunk_count (SQLite) с числом
        точек в Qdrant. Несовпавшие → PENDING (переиндексируются и встанут на место). Лечит рассинхрон
        от сбоя cleanup/краша/ручных операций. Дорогая (count на файл) — это разовая операция-ремонт."""
        sync_qdrant = qdrant_client.QdrantClient(
            url=self.qdrant_url, timeout=60.0, check_compatibility=False,
        )
        files = self.db.indexed_files_with_counts(dataset_id)
        checked = 0
        mismatched: list[dict] = []
        requeued_files: set[str] = set()
        for file_name, sqlite_cc in files:
            checked += 1
            try:
                qpoints = self._sync_count_file_points(sync_qdrant, dataset_id, file_name)
            except Exception as error:  # noqa: BLE001
                logger.warning("[RECONCILE] count failed %s: %s", file_name, error)
                continue
            dense_mismatch = qpoints != sqlite_cc
            if dense_mismatch:
                mismatched.append({"file": file_name, "sqlite": sqlite_cc, "qdrant": qpoints})
            if dense_mismatch:
                self.db.update_document_status(dataset_id, file_name, "PENDING", 0)
                requeued_files.add(file_name)
        if mismatched:
            self.db.update_dataset_chunk_count(dataset_id)
        logger.info("[RECONCILE] dataset=%s checked=%s mismatched=%s (→PENDING)",
                    dataset_id, checked, len(mismatched))
        return {"dataset_id": dataset_id, "checked": checked,
                "mismatched": len(mismatched), "requeued": len(requeued_files),
                "details": mismatched[:50]}

    def _sync_dataset_point_projection(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
    ) -> dict[str, dict[str, Any]]:
        projection: dict[str, dict[str, Any]] = {}
        offset = None
        dataset_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="dataset_id",
                    match=models.MatchValue(value=dataset_id),
                )
            ]
        )
        while True:
            points, offset = sync_qdrant.scroll(
                collection_name=self.collection_name,
                scroll_filter=dataset_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = getattr(point, "payload", None) or {}
                file_name = str(payload.get("file_name") or payload.get("doc_name") or "")
                row = projection.setdefault(file_name, {"ids": set(), "pages": set()})
                row["ids"].add(str(getattr(point, "id", "") or ""))
                if payload.get("type") == "pdf_page_text" and payload.get("page") is not None:
                    try:
                        row["pages"].add(int(payload["page"]))
                    except (TypeError, ValueError):
                        pass
            if offset is None:
                break
        return projection

    @staticmethod
    def _expected_pdf_text_pages(path: Path) -> set[int]:
        if path.suffix.lower() not in PDF_PAGE_NODE_SUFFIXES:
            return set()
        try:
            import fitz

            with fitz.open(path) as document:
                return {
                    page_no
                    for page_no, page in enumerate(document, start=1)
                    if len((page.get_text("text") or "").strip()) >= MIN_CHUNK
                }
        except Exception as error:  # noqa: BLE001
            logger.warning("[INTEGRITY] PDF page inventory failed %s: %s", path, error)
            return set()

    def _sync_count_file_vector_points(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
        vector_name: str,
    ) -> int:
        file_filter = self._file_filter(dataset_id, file_key)
        file_filter.must.append(models.HasVectorCondition(has_vector=vector_name))
        result = sync_qdrant.count(
            collection_name=self.collection_name,
            count_filter=file_filter,
            exact=True,
        )
        return int(result.count)

    def audit_dataset_integrity(self, dataset_id: str, *, repair: bool = False) -> dict[str, Any]:
        """Verify one dataset across source, MetaDB, Qdrant dense/sparse, lexical and FTS.

        Repair is conservative: only damaged documents are requeued; missing sources are marked
        MISSING, FTS is rebuilt from its content table, and points with no registered document are
        removed.  The parse job itself is started by the API layer so the operator sees one job.
        """
        sync_qdrant = qdrant_client.QdrantClient(
            url=self.qdrant_url,
            timeout=60.0,
            check_compatibility=False,
        )
        rows = self.db.dataset_integrity_rows(dataset_id)
        registry = {str(row["file_name"]): row for row in rows}
        try:
            qdrant_files = self._sync_dataset_point_projection(sync_qdrant, dataset_id)
        except Exception as error:  # noqa: BLE001
            return {
                "schema": "les.dataset_integrity.v1",
                "dataset_id": dataset_id,
                "state": "blocked",
                "label": "Векторная база недоступна",
                "checked_files": len(rows),
                "indexed_files": 0,
                "clean_files": 0,
                "damaged_files": 0,
                "missing_files": 0,
                "contract_ok": False,
                "fts_ok": False,
                "orphan_qdrant_files": 0,
                "orphan_lexical_files": 0,
                "repaired": 0,
                "requeued": 0,
                "issues": [{"file": "", "status": "BLOCKED", "problems": [str(error)[:300]]}],
            }
        lexical = self.db.lexical_integrity_projection(dataset_id)
        lexical_files: dict[str, set[str]] = lexical.get("files") or {}
        contract = index_contract_status()
        contract_ok = bool(contract.get("compatible"))

        damaged: set[str] = set()
        missing: set[str] = set()
        issues: list[dict[str, Any]] = []
        clean_files = 0
        indexed_files = 0
        pending_files = 0
        file_checks: list[dict[str, Any]] = []

        for file_name, row in registry.items():
            status = str(row.get("status") or "")
            source = Path(str(row.get("source_path") or "")) if row.get("source_path") else (
                self.content_dir / dataset_id / file_name
            )
            file_issues: list[str] = []
            expected = int(row.get("chunk_count") or 0)
            qdrant_count = dense_count = sparse_count = lexical_count = 0
            expected_page_count = indexed_page_count = 0
            if status == "ERROR":
                file_issues.append("Предыдущая индексация завершилась ошибкой")
                damaged.add(file_name)
            elif status == "PENDING":
                pending_files += 1
                file_issues.append("Ожидает индексации")
            if status != "SKIPPED":
                if not source.is_file():
                    file_issues.append("Исходный файл не найден")
                    missing.add(file_name)
                else:
                    stat = source.stat()
                    expected_size = int(row.get("file_size") or 0)
                    expected_mtime = float(row.get("file_mtime") or 0)
                    if expected_size and stat.st_size != expected_size:
                        file_issues.append("Исходный файл изменился")
                        damaged.add(file_name)
                    elif expected_mtime and abs(stat.st_mtime - expected_mtime) > 1.0:
                        stored_hash = str(row.get("file_hash") or "")
                        if stored_hash and _sha256_file(source) != stored_hash:
                            file_issues.append("Содержимое исходного файла изменилось")
                            damaged.add(file_name)

            if status == "INDEXED":
                indexed_files += 1
                qrow = qdrant_files.get(file_name) or {"ids": set(), "pages": set()}
                qids = set(qrow.get("ids") or set())
                lexical_ids = set(lexical_files.get(file_name) or set())
                dense = self._sync_count_file_vector_points(
                    sync_qdrant, dataset_id, file_name, _dense_vector_name()
                )
                sparse = self._sync_count_file_vector_points(
                    sync_qdrant, dataset_id, file_name, _sparse_vector_name()
                )
                qdrant_count = len(qids)
                dense_count = dense
                sparse_count = sparse
                lexical_count = len(lexical_ids)
                if len(qids) != expected:
                    file_issues.append(f"Векторный индекс: {len(qids)} из {expected}")
                if dense != expected:
                    file_issues.append(f"Смысловой поиск: {dense} из {expected}")
                if sparse != expected:
                    file_issues.append(f"Точный поиск: {sparse} из {expected}")
                if lexical_ids != qids:
                    file_issues.append(f"Текстовый поиск: {len(lexical_ids)} из {len(qids)}")
                if source.is_file() and source.suffix.lower() in PDF_PAGE_NODE_SUFFIXES:
                    expected_pages = self._expected_pdf_text_pages(source)
                    indexed_pages = set(qrow.get("pages") or set())
                    expected_page_count = len(expected_pages)
                    indexed_page_count = len(indexed_pages)
                    if expected_pages and indexed_pages != expected_pages:
                        file_issues.append(
                            f"Страницы PDF: {len(indexed_pages)} из {len(expected_pages)}"
                        )
                if file_issues and file_name not in missing:
                    damaged.add(file_name)

            if file_issues:
                issues.append({"file": file_name, "status": status, "problems": file_issues})
            elif status == "INDEXED":
                clean_files += 1
            file_checks.append(
                {
                    "file": file_name,
                    "status": status,
                    "expected_chunks": expected,
                    "qdrant_chunks": qdrant_count,
                    "dense_chunks": dense_count,
                    "sparse_chunks": sparse_count,
                    "lexical_chunks": lexical_count,
                    "expected_text_pages": expected_page_count,
                    "indexed_text_pages": indexed_page_count,
                    "problems": list(file_issues),
                }
            )

        orphan_qdrant = sorted(set(qdrant_files) - set(registry))
        orphan_lexical = sorted(set(lexical_files) - set(registry))
        fts_ok = bool(lexical.get("fts_available")) and (
            set(lexical.get("lexical_ids") or set()) == set(lexical.get("fts_ids") or set())
        )
        if not contract_ok:
            issues.insert(0, {"file": "", "status": "BLOCKED", "problems": ["Контракт индекса не совпадает"]})
        if orphan_qdrant:
            issues.append({"file": "", "status": "ORPHAN", "problems": [f"Лишние векторные документы: {len(orphan_qdrant)}"]})
        if orphan_lexical:
            issues.append({"file": "", "status": "ORPHAN", "problems": [f"Лишние текстовые документы: {len(orphan_lexical)}"]})
        if not fts_ok:
            issues.append({"file": "", "status": "FTS", "problems": ["Текстовый индекс требует пересборки"]})

        repaired = 0
        if repair and contract_ok:
            for file_name in sorted(missing):
                self._sync_delete_file_points(sync_qdrant, dataset_id, file_name)
                self._sync_delete_file_lexical(dataset_id, file_name)
            self.db.set_documents_missing(dataset_id, missing)
            repaired += self.db.set_documents_pending(dataset_id, damaged - missing)
            for file_name in orphan_qdrant:
                point_ids = list((qdrant_files.get(file_name) or {}).get("ids") or [])
                if point_ids:
                    sync_qdrant.delete(
                        collection_name=self.collection_name,
                        points_selector=models.PointIdsList(points=point_ids),
                        wait=True,
                    )
            for file_name in orphan_lexical:
                self._sync_delete_file_lexical(dataset_id, file_name)
            if not fts_ok and lexical.get("fts_available"):
                self.db.rebuild_lexical_fts()
            self.db.update_dataset_chunk_count(dataset_id)
            repaired += len(missing) + len(orphan_qdrant) + len(orphan_lexical) + (0 if fts_ok else 1)

        state = (
            "blocked"
            if not contract_ok or missing
            else "repairable"
            if damaged or orphan_qdrant or orphan_lexical or not fts_ok
            else "building"
            if pending_files
            else "healthy"
        )
        return {
            "schema": "les.dataset_integrity.v1",
            "dataset_id": dataset_id,
            "state": state,
            "label": {
                "healthy": "Датасет цел",
                "repairable": "Найдены исправимые повреждения",
                "building": "Индексация не завершена",
                "blocked": "Нужно внимание оператора",
            }[state],
            "checked_files": len(rows),
            "indexed_files": indexed_files,
            "pending_files": pending_files,
            "clean_files": clean_files,
            "damaged_files": len(damaged),
            "missing_files": len(missing),
            "contract_ok": contract_ok,
            "fts_ok": fts_ok,
            "orphan_qdrant_files": len(orphan_qdrant),
            "orphan_lexical_files": len(orphan_lexical),
            "repaired": repaired,
            "requeued": len(damaged - missing) if repair and contract_ok else 0,
            "issues": issues[:100],
            "file_checks": file_checks,
        }

    def _sync_existing_file_vectors_by_hash(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
        embedding_fingerprint: str,
    ) -> dict[str, list[float]]:
        vectors: dict[str, list[float]] = {}
        offset = None
        try:
            while True:
                points, offset = sync_qdrant.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=self._file_filter(dataset_id, file_key),
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                for point in points:
                    payload = getattr(point, "payload", None) or {}
                    if str(payload.get("embedding_fingerprint") or "") != embedding_fingerprint:
                        continue
                    text = str(payload.get("text") or "")
                    content_hash = str(payload.get("content_hash") or _content_hash(text))
                    vector = self._extract_point_vector(point)
                    if content_hash and vector is not None:
                        vectors.setdefault(content_hash, vector)
                if offset is None:
                    break
        except Exception as error:
            logger.warning("[PARSE] chunk hash cache unavailable for %s: %s", file_key, error)
        return vectors

    @staticmethod
    def _extract_point_vector(point: Any) -> list[float] | None:
        vector = getattr(point, "vector", None)
        if isinstance(vector, dict):
            vector = (
                vector.get("")
                or vector.get("default")
                or vector.get(_dense_vector_name())
                or next((v for v in vector.values() if isinstance(v, list)), None)
            )
        if isinstance(vector, list) and vector and all(isinstance(item, (int, float)) for item in vector):
            return [float(item) for item in vector]
        return None

    def _apply_context_metadata(self, file_nodes: list[dict], dataset_id: str, file_key: str) -> None:
        _apply_context_metadata_to_nodes(file_nodes, dataset_id, file_key)

    @staticmethod
    def _finalize_embedding_nodes(
        file_nodes: list[dict],
        *,
        chunking: dict[str, Any],
    ) -> list[dict]:
        """Sanitize and enforce the final embedding budget for all node types."""
        len_fn = chunking.get("len_fn") or len
        budget = max(1, int(chunking.get("chunk_size") or 1))
        unit = str(chunking.get("unit") or "chars")
        finalized: list[dict] = []
        for node_index, node in enumerate(file_nodes):
            clean, quality = _sanitize_embedding_text(str(node.get("text") or ""))
            if len(clean) < FINAL_MIN_CHUNK:
                continue
            parts = _split_to_embedding_budget(clean, budget=budget, len_fn=len_fn)
            parent_id = str(node.get("doc_id") or f"node-{node_index}")
            for child_index, part in enumerate(parts):
                if len(part) < FINAL_MIN_CHUNK:
                    continue
                measured = int(len_fn(part))
                if measured > budget:
                    raise RuntimeError(
                        f"embedding budget invariant failed: {measured}>{budget} {unit}"
                    )
                payload = dict(node.get("payload") or {})
                payload.update(
                    {
                        "embedding_chunk_unit": unit,
                        "embedding_chunk_length": measured,
                        "embedding_chunk_budget": budget,
                        "embedding_budget_enforced": True,
                        "content_sanitized": quality["sanitized"],
                        "content_quality": quality,
                        "parent_node_id": payload.get("parent_node_id") or parent_id,
                        "child_ord": child_index,
                    }
                )
                suffix = hashlib.sha1(
                    f"{parent_id}\n{child_index}\n{part}".encode("utf-8", errors="ignore")
                ).hexdigest()[:16]
                finalized.append(
                    {
                        **node,
                        "text": part,
                        "doc_id": f"{parent_id}:budget:{suffix}",
                        "payload": payload,
                    }
                )
        return finalized

    def _sync_markdown_nodes(
        self,
        file_path: Path,
        file_key: str,
        dataset_id: str,
        md_parser: MarkdownNodeParser,
        splitter: SentenceSplitter,
        route: DocumentRoute | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        import time as _t
        phase_start = _t.time()
        md_content = convert_to_markdown_for_indexing(file_path, route=route)
        if timings is not None:
            timings["convert_sec"] = timings.get("convert_sec", 0.0) + (_t.time() - phase_start)
        if not md_content:
            return []

        phase_start = _t.time()
        if _pdf_page_nodes_enabled(file_path, route):
            file_nodes = self._sync_pdf_page_text_nodes(
                file_key,
                dataset_id,
                md_content,
                route,
                file_path=file_path,
            )
            if timings is not None:
                timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
            if file_nodes:
                return file_nodes

        doc = Document(
            text=md_content,
            metadata={"file_name": file_key, "dataset_id": dataset_id},
        )
        nodes = md_parser.get_nodes_from_documents([doc])

        file_nodes = []
        payload_type = "spreadsheet_projection" if file_path.suffix.lower() in {".xlsx", ".xlsm", ".xls", ".csv"} else "markdown"
        for node in nodes:
            node.metadata.update(doc.metadata)
            if len(node.text) > 2000:
                split_nodes = splitter.get_nodes_from_documents([node])
                file_nodes.extend(
                    {
                        "text": split_node.text,
                        "doc_id": split_node.node_id,
                        "payload": self._route_payload(route, {"type": payload_type}),
                    }
                    for split_node in split_nodes
                    if len(split_node.text) >= MIN_CHUNK
                )
            elif len(node.text) >= MIN_CHUNK:
                file_nodes.append({
                    "text": node.text,
                    "doc_id": node.node_id,
                    "payload": self._route_payload(route, {"type": payload_type}),
                })
        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return file_nodes

    def _sync_pdf_page_text_nodes(
        self,
        file_key: str,
        dataset_id: str,
        md_content: str,
        route: DocumentRoute | None = None,
        *,
        file_path: Path | None = None,
    ) -> list[dict]:
        page_blocks = self._split_pdf_page_markdown(md_content)
        if not page_blocks:
            return []
        page_passports: dict[int, dict[str, Any]] = {}
        if file_path is not None and _pdf_page_passport_enabled(file_path):
            try:
                from proxy.services.pdf_contour_service import rag_page_metadata

                page_passports = rag_page_metadata(
                    file_path,
                    [page_no for page_no, _text in page_blocks],
                    file_name=file_key,
                )
            except Exception as error:  # noqa: BLE001 - passport enrichment must not lose searchable text
                logger.warning("[PDF-CONTOUR] page passport failed for %s: %s", file_key, error)
        max_chars = _pdf_page_node_max_chars()
        overlap = min(_pdf_page_node_overlap_chars(), max_chars // 3)
        nodes: list[dict] = []
        for page_no, page_text in page_blocks:
            text = page_text.strip()
            if not text or text == "[no text extracted]":
                continue
            chunks = self._split_pdf_page_text(text, max_chars=max_chars, overlap=overlap)
            part_count = len(chunks)
            passport = page_passports.get(page_no) or {}
            quality = passport.get("recognition_quality") if isinstance(passport.get("recognition_quality"), dict) else {}
            signals = passport.get("signals") if isinstance(passport.get("signals"), dict) else {}
            stamp = passport.get("stamp") if isinstance(passport.get("stamp"), dict) else {}
            fragment_bboxes = [
                {
                    "fragment_id": item.get("fragment_id"),
                    "bbox": item.get("bbox"),
                    "source_ref": item.get("source_ref"),
                }
                for item in (passport.get("evidence_fragments") or [])
                if isinstance(item, dict)
            ][:5]
            route_uses_ocr = str(getattr(route, "pipeline", "") or "") == "markdown_needs_ocr"
            source_layer = "pdf_ocr_text" if route_uses_ocr or passport.get("requires_ocr") else "pdf_text_layer"
            for part_no, chunk_text in enumerate(chunks, start=1):
                # A short PDF page can still be decisive evidence: a cover mark,
                # sheet number, room code or equipment designation.  The generic
                # markdown noise threshold must not discard an entire non-empty
                # page after the page router has already identified it.
                if not chunk_text.strip():
                    continue
                title = f"## Page {page_no}"
                if part_count > 1:
                    title += f" part {part_no}/{part_count}"
                text_for_index = f"{title}\n\n{chunk_text.strip()}"
                payload = {
                    "type": "pdf_page_text",
                    "source_layer": source_layer,
                    "page": page_no,
                    "page_part": part_no,
                    "page_parts": part_count,
                    "source_ref": str(passport.get("source_ref") or f"{file_key}#page={page_no}"),
                }
                if passport:
                    payload.update({
                        "pdf_page_passport_schema": passport.get("schema"),
                        "pdf_page_type": passport.get("page_type"),
                        "pdf_page_type_label": passport.get("page_type_label"),
                        "pdf_routing_confidence": passport.get("routing_confidence"),
                        "pdf_requires_ocr": bool(passport.get("requires_ocr")),
                        "pdf_recognition_quality": quality,
                        "pdf_page_signals": signals,
                        "pdf_stamp_status": stamp.get("status"),
                        "pdf_sheet_number": stamp.get("sheet_number") or "",
                        "pdf_fragment_bboxes": fragment_bboxes,
                    })
                nodes.append({
                    "text": text_for_index,
                    "doc_id": str(uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{dataset_id}:{file_key}:pdf-page:{page_no}:{part_no}",
                    )),
                    "payload": self._route_payload(route, payload),
                })
        return nodes

    @staticmethod
    def _split_pdf_page_markdown(md_content: str) -> list[tuple[int, str]]:
        matches = list(re.finditer(r"(?m)^## (?:Page|Стр\.)\s+(\d+)\s*$", md_content or ""))
        pages: list[tuple[int, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(md_content)
            try:
                page_no = int(match.group(1))
            except ValueError:
                continue
            pages.append((page_no, md_content[start:end].strip()))
        return pages

    @staticmethod
    def _split_pdf_page_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
        value = (text or "").strip()
        if len(value) <= max_chars:
            return [value] if value else []
        chunks: list[str] = []
        start = 0
        while start < len(value):
            end = min(len(value), start + max_chars)
            if end < len(value):
                boundary = max(value.rfind("\n", start, end), value.rfind(". ", start, end))
                if boundary > start + max_chars // 2:
                    end = boundary + (1 if value[boundary] == "\n" else 2)
            chunk = value[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(value):
                break
            start = max(end - overlap, start + 1)
        return chunks

    def _sync_mail_nodes(
        self,
        file_path: Path,
        data_dir: Path,
        file_key: str,
        dataset_id: str,
        splitter: SentenceSplitter,
        route: DocumentRoute | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        import time as _t

        phase_start = _t.time()
        profile = build_mail_vector_profile(file_path, source_dir=data_dir)
        if timings is not None:
            timings["convert_sec"] = timings.get("convert_sec", 0.0) + (_t.time() - phase_start)

        phase_start = _t.time()
        nodes: list[dict] = []
        message_payload = profile.payload()
        registry_payload: dict[str, Any] = {}
        registry = None
        registered = None
        try:
            from proxy.services.mail_registry_service import get_mail_registry

            registry = get_mail_registry()
            registered = registry.find_message_by_relative_path(file_key)
            if registered:
                account = registry.get_account(registered["account_id"], include_secret_state=False)
                if str(account.get("dataset_id") or "") == dataset_id:
                    registry_payload = {
                        "mail_account_id": registered["account_id"],
                        "mail_registry_message_id": registered["id"],
                        "mail_dataset_id": account["dataset_id"],
                        "mail_dataset_name": account["dataset_name"],
                        "mail_source_kind": registered["source_kind"],
                        "mail_source_locator": {
                            "outlook_store_id": registered["outlook_store_id"],
                            "outlook_entry_id": registered["outlook_entry_id"],
                            "native_id": registered["native_id"],
                        },
                        "mail_content_sha256": registered["content_sha256"],
                        "mail_folders": [
                            item["folder_path"]
                            for item in registered["locations"]
                            if item.get("is_current")
                        ],
                    }
        except Exception:
            # Legacy MAIL_Index and standalone parser tests have no registry.
            registry_payload = {}
        message_payload.update(registry_payload)
        message_payload.update({
            "type": "mail_message",
            "mail_node_kind": "message",
        })
        nodes.extend(
            self._split_profile_text_nodes(
                profile.message_embedding_text(include_attachment_text=False),
                dataset_id,
                file_key,
                splitter,
                self._route_payload(route, message_payload),
                "message",
            )
        )

        for attachment in profile.attachments:
            attachment_provenance: dict[str, Any] = {}
            if registry is not None and registered is not None and registry_payload:
                attachment_provenance = registry.register_attachment_provenance(
                    account_id=registered["account_id"],
                    message_id=registered["id"],
                    attachment_id=attachment.attachment_id,
                    attachment_sha256=attachment.sha256,
                )
                if not attachment_provenance.get("canonical", True):
                    # The per-message node above retains this message's attachment
                    # checksum/provenance; identical attachment text is embedded once.
                    continue
            attachment_payload = profile.payload()
            attachment_payload.update(registry_payload)
            attachment_payload.update({
                "type": "mail_attachment",
                "mail_node_kind": "attachment",
                "mail_attachment_id": attachment.attachment_id,
                "mail_attachment_filename": attachment.filename,
                "mail_attachment_content_type": attachment.content_type,
                "mail_attachment_kind": attachment.kind,
                "mail_attachment_sha256": attachment.sha256,
                "mail_attachment_extraction": attachment.extraction,
                "mail_attachment_needs_ocr": attachment.needs_ocr,
                "mail_attachment_needs_vlm": attachment.needs_vlm,
                "mail_attachment_has_text": attachment.has_text,
                "mail_attachment_error": attachment.error,
                "mail_attachment_canonical_message_id": attachment_provenance.get(
                    "canonical_message_id", registered["id"] if registered else ""
                ),
                "mail_attachment_provenance_count": attachment_provenance.get(
                    "provenance_count", 1
                ),
            })
            nodes.extend(
                self._split_profile_text_nodes(
                    attachment.embedding_text(profile),
                    dataset_id,
                    file_key,
                    splitter,
                    self._route_payload(route, attachment_payload),
                    f"attachment:{attachment.attachment_id}",
                )
            )

        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return nodes

    def _split_profile_text_nodes(
        self,
        text: str,
        dataset_id: str,
        file_key: str,
        splitter: SentenceSplitter,
        payload: dict[str, Any],
        node_key: str,
    ) -> list[dict]:
        value = str(text or "").strip()
        if len(value) < MIN_CHUNK:
            return []
        if len(value) <= 2000:
            return [{
                "text": value,
                "doc_id": deterministic_mail_node_id(dataset_id, file_key, node_key),
                "payload": dict(payload),
            }]

        doc = Document(text=value, metadata={"file_name": file_key, "dataset_id": dataset_id})
        split_nodes = splitter.get_nodes_from_documents([doc])
        return [
            {
                "text": split_node.text,
                "doc_id": deterministic_mail_node_id(dataset_id, file_key, f"{node_key}:{idx}"),
                "payload": dict(payload),
            }
            for idx, split_node in enumerate(split_nodes)
            if len(split_node.text) >= MIN_CHUNK
        ]

    def _sync_table_nodes(
        self,
        file_path: Path,
        data_dir: Path,
        file_key: str,
        dataset_id: str,
        route: DocumentRoute | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        import time as _t
        # Производный Parquet кладём в storage по file_key (а не относительно file_path):
        # внешний in-place источник лежит вне data_dir, но дериватив остаётся в storage.
        parquet_dir = data_dir / "_parquet" / Path(file_key).parent
        normalizer = TableNormalizer(parquet_dir=str(parquet_dir), use_llm=False)
        phase_start = _t.time()
        doc_type_override = "TABLE" if route and not route.domain.startswith("TABLE_") else None
        result = asyncio.run(
            normalizer.process(str(file_path), dataset_id=dataset_id, doc_type_override=doc_type_override)
        )
        if timings is not None:
            timings["convert_sec"] = timings.get("convert_sec", 0.0) + (_t.time() - phase_start)
        parquet_path = result.get("parquet_path") or ""
        parquet_rel = ""
        if parquet_path:
            try:
                parquet_rel = Path(parquet_path).relative_to(data_dir).as_posix()
            except ValueError:
                parquet_rel = parquet_path

        phase_start = _t.time()
        chunks = list(result.get("chunks") or [])
        if len(chunks) > TABLE_ROW_INDEX_MAX_CHUNKS:
            return self._table_navigation_projection_nodes(
                file_path=file_path,
                file_key=file_key,
                dataset_id=dataset_id,
                route=route,
                parquet_rel=parquet_rel,
                result=result,
                chunks=chunks,
                timings=timings,
                phase_start=phase_start,
            )

        nodes = []
        for i, chunk in enumerate(chunks):
            text = str(chunk.get("text") or "")
            if len(text) < MIN_CHUNK:
                continue
            payload = dict(chunk.get("metadata") or {})
            payload.update({
                "type": "table_row",
                "parquet_path": parquet_rel,
                "table_row": i,
                "table_kind": self._table_kind(route),
            })
            nodes.append({
                "text": text,
                "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_path}:{i}")),
                "payload": self._route_payload(route, payload),
            })
        if not nodes and result.get("needs_ocr"):
            scanned_pages = result.get("scanned_pages") or []
            text = (
                f"PDF {file_path.name} содержит страницы без текстового слоя; "
                f"нужна OCR/VLM обработка. Страницы: {', '.join(map(str, scanned_pages)) or '?'}"
            )
            payload = {
                "type": "pdf_needs_ocr",
                "needs_ocr": True,
                "scanned_pages": scanned_pages,
                "parquet_path": "",
                "table_kind": self._table_kind(route),
            }
            nodes.append({
                "text": text,
                "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_path}:needs_ocr")),
                "payload": self._route_payload(route, payload),
            })
        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return nodes

    def _table_navigation_projection_nodes(
        self,
        *,
        file_path: Path,
        file_key: str,
        dataset_id: str,
        route: DocumentRoute | None,
        parquet_rel: str,
        result: dict[str, Any],
        chunks: list[dict[str, Any]],
        timings: dict[str, float] | None,
        phase_start: float,
    ) -> list[dict]:
        import time as _t

        rows = int(result.get("rows") or len(chunks))
        names: list[str] = []
        codes: list[str] = []
        units: list[str] = []
        sections: list[str] = []
        for chunk in chunks:
            meta = dict(chunk.get("metadata") or {})
            for target, key in ((names, "name"), (codes, "code"), (units, "unit"), (sections, "section")):
                value = str(meta.get(key) or "").strip()
                if value and value not in target:
                    target.append(value[:160])
                if len(target) >= 20:
                    break

        text = "\n".join(
            part
            for part in [
                f"Табличный файл: {file_key}",
                "Тип: table_navigation_projection",
                f"Строк нормализовано: {rows}",
                f"Листов/таблиц: {result.get('sheets') or ''}",
                f"Parquet: {parquet_rel or '[не создан]'}",
                "Назначение: навигация по таблице и выбор источника; точные строки, фильтры, суммы и группировки читать из parquet/source table reader.",
                "Разделы: " + "; ".join(sections[:20]) if sections else "",
                "Коды/обозначения: " + "; ".join(codes[:20]) if codes else "",
                "Наименования: " + "; ".join(names[:20]) if names else "",
                "Единицы: " + "; ".join(units[:20]) if units else "",
            ]
            if part
        )
        payload = {
            "type": "table_navigation_projection",
            "parquet_path": parquet_rel,
            "table_kind": self._table_kind(route),
            "table_rows": rows,
            "table_sheets": result.get("sheets") or 0,
            "source_file": file_path.name,
        }
        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return [{
            "text": text,
            "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_path}:table_projection")),
            "payload": self._route_payload(route, payload),
        }]

    @staticmethod
    def _docx_table_extraction_enabled(file_path: Path, route: DocumentRoute | None) -> bool:
        if file_path.suffix.lower() != ".docx":
            return False
        if os.getenv("DOCX_TABLE_EXTRACTION_ENABLED", "false").lower() not in ("1", "true", "yes"):
            return False
        if route is None:
            return True
        return route.domain.startswith("NTD_") or route.domain in {"GKRF", "BOOKS"}

    @staticmethod
    def _table_kind(route: DocumentRoute | None) -> str:
        if route is None:
            return "table"
        if route.domain.startswith("TABLE_"):
            return "cost"
        if route.domain.startswith("NTD_") or route.domain in {"GKRF", "BOOKS"}:
            return "normative"
        return "table"

    def _route_payload(self, route: DocumentRoute | None, payload: dict) -> dict:
        if route is None:
            return payload
        merged = dict(payload)
        merged.update(route.metadata)
        return merged

    async def retrieve(
        self,
        query:       str,
        dataset_ids: Optional[List[str]] = None,
        top_k:       int = 5,
        doc_filter:  Optional[List[str]] = None,
    ) -> List[Chunk]:
        await self._ensure_collection()
        self._assert_dense_index_contract()

        # Async эмбеддинг запроса
        vecs = await self.embed.encode_async([query], query=True)
        query_vec = vecs[0]

        # ADR-12 стадия-2: doc_filter сужает поиск до выбранных документов-узлов
        # (file_name), а не по всему датасету. Пусто → прежнее поведение (плоско по датасету).
        must = []
        if dataset_ids:
            must.append(models.FieldCondition(key="dataset_id", match=models.MatchAny(any=dataset_ids)))
        if doc_filter:
            must.append(models.FieldCondition(key="file_name", match=models.MatchAny(any=doc_filter)))
        query_filter = models.Filter(must=must) if must else None

        results = await self.aclient.query_points(
            collection_name=self.collection_name,
            query=query_vec,
            using=_dense_vector_name() if _qdrant_schema_mode() == "named" else None,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

        def _is_binary_garbage(text: str) -> bool:
            """Detect base64-encoded or binary garbage chunks."""
            if not text or len(text) < 40:
                return False
            lines = text.split("\n")
            long_dense_lines = sum(
                1 for line in lines
                if len(line) > 60 and " " not in line and "/" in line + "=" in line
            )
            if long_dense_lines >= 2:
                return True
            # Check if text has no Cyrillic at all and looks like base64
            sample = text[:200].replace("\n", "")
            if len(sample) > 80:
                cyrillic = sum(1 for c in sample if "\u0400" <= c <= "\u04ff")
                spaces = sample.count(" ")
                if cyrillic == 0 and spaces < 3:
                    return True
            return False

        return [
            Chunk(
                content=p.payload.get("text", ""),
                doc_id=p.payload.get("doc_id", ""),
                doc_name=p.payload.get("file_name", "unknown"),
                score=p.score,
                meta=p.payload,
            )
            for p in results.points
            if not _is_binary_garbage(p.payload.get("text", ""))
        ]

    async def retrieve_native_hybrid(
        self,
        query: str,
        dataset_ids: Optional[List[str]] = None,
        top_k: int = 8,
        doc_filter: Optional[List[str]] = None,
    ) -> List[Chunk]:
        """Qdrant-native dense+sparse hybrid over a named-vector collection.

        Requires `RAG_QDRANT_SCHEMA=named` and points containing both dense and
        sparse named vectors. Caller should keep a fallback to the legacy hybrid.
        """
        if _qdrant_schema_mode() != "named":
            raise RuntimeError("qdrant native hybrid requires RAG_QDRANT_SCHEMA=named")
        from backend.inference.bm25_sparse import encode_bm25

        await self._ensure_collection()
        self._assert_dense_index_contract()
        vecs = await self.embed.encode_async([query], query=True)
        dense_vec = vecs[0]
        sparse = encode_bm25(query)
        if not sparse:
            # Do not let the caller label a dense-only query as native RRF.
            # The retrieval service will use its explicit dense+FTS fallback
            # and expose the actual channels in trace.
            raise RuntimeError("native RRF requires a non-empty sparse query")

        must = []
        if dataset_ids:
            must.append(models.FieldCondition(key="dataset_id", match=models.MatchAny(any=dataset_ids)))
        if doc_filter:
            must.append(models.FieldCondition(key="file_name", match=models.MatchAny(any=doc_filter)))
        query_filter = models.Filter(must=must) if must else None
        prefetch_limit = max(top_k * 2, 24)
        results = await self.aclient.query_points(
            collection_name=self.collection_name,
            prefetch=[
                models.Prefetch(
                    query=dense_vec,
                    using=_dense_vector_name(),
                    filter=query_filter,
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=list(sparse.keys()), values=list(sparse.values())),
                    using=_sparse_vector_name(),
                    filter=query_filter,
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        return [
            Chunk(
                content=p.payload.get("text", ""),
                doc_id=p.payload.get("doc_id", ""),
                doc_name=p.payload.get("file_name", "unknown"),
                score=p.score,
                meta=p.payload,
            )
            for p in results.points
            if len(p.payload.get("text", "")) >= 1
        ]

    async def retrieve_table_rows(
        self,
        dataset_ids: Optional[List[str]] = None,
        limit: int = 64,
    ) -> List[Chunk]:
        await self._ensure_collection()

        must = [
            models.FieldCondition(
                key="type",
                match=models.MatchValue(value="table_row"),
            )
        ]
        if dataset_ids:
            must.append(
                models.FieldCondition(
                    key="dataset_id",
                    match=models.MatchAny(any=dataset_ids),
                )
            )

        points, _next_page = await self.aclient.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return [
            Chunk(
                content=point.payload.get("text", ""),
                doc_id=point.payload.get("doc_id", ""),
                doc_name=point.payload.get("file_name", "unknown"),
                score=1.0,
                meta=point.payload,
            )
            for point in points
        ]
