"""
MLX Native Host v3.2 — Л.Е.С.
==============================
FastAPI сервер на порту 8080.
Запуск: uv run python3 mlx_host.py

Движки:
  main_engine  — MLX_MODEL     (RAG, TTL 300с)
  val_engine   — MLX_VAL_MODEL (Т.О.С.К.А. v2, TTL 120с)
  embedder     — EMBEDDING_MODEL / BGE_MODEL (Core ML or sentence-transformers, lazy load)
"""

import asyncio
import gc
import json
import logging
import os
import re
import select
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Union

# Грузим .env из директории проекта — независимо от того, кто запустил процесс
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.mlx_adapter import MLXMemoryManager
from backend.rag_config import embed_profile_name, embedding_model_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] MLX Host: %(message)s",
)
logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


# ── Конфигурация ──────────────────────────────────────────────────────────────
MAIN_MODEL = os.getenv("MLX_MODEL",     "mlx-community/Qwen3-14B-4bit")
VAL_MODEL  = os.getenv("MLX_VAL_MODEL", "mlx-community/Qwen3-4B-4bit")
BGE_MODEL  = embedding_model_id()
BGE_BATCH_SIZE = int(os.getenv("BGE_BATCH_SIZE", "32"))
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower()
COREML_EMBED_MODEL = os.getenv(
    "COREML_EMBED_MODEL",
    "artifacts/coreml/qwen3_embedding_06b_b1_s1024_static.mlpackage",
)
COREML_EMBED_SEQ_LEN = _env_int("COREML_EMBED_SEQ_LEN", 1024)
COREML_EMBED_BATCH_SIZE = _env_int("COREML_EMBED_BATCH_SIZE", 1)
COREML_EMBED_COMPUTE_UNITS = os.getenv("COREML_EMBED_COMPUTE_UNITS", "cpu_and_gpu").strip().lower()
COREML_EMBED_ISOLATE_PROCESS = _env_bool("COREML_EMBED_ISOLATE_PROCESS", True)
COREML_EMBED_WORKER_TIMEOUT_SEC = _env_float("COREML_EMBED_WORKER_TIMEOUT_SEC", 120.0)
COREML_EMBED_MIN_NORM = _env_float("COREML_EMBED_MIN_NORM", 0.5)
COREML_EMBED_MAX_NORM = _env_float("COREML_EMBED_MAX_NORM", 1.5)
COREML_EMBED_MAX_FAILURES = _env_int("COREML_EMBED_MAX_FAILURES", 2)
COREML_EMBED_FAILURE_COOLDOWN_SEC = _env_float("COREML_EMBED_FAILURE_COOLDOWN_SEC", 300.0)
COREML_EMBED_FALLBACK = _env_bool("COREML_EMBED_FALLBACK", True)
COREML_EMBED_LOCAL_FILES_ONLY = _env_bool("COREML_EMBED_LOCAL_FILES_ONLY", True)
VALIDATOR_BACKEND = os.getenv("VALIDATOR_BACKEND", "mlx").strip().lower()
VALIDATOR_MODEL_VERSION = os.getenv("VALIDATOR_MODEL_VERSION", "main")
COREML_VALIDATOR_MODEL = os.getenv("COREML_VALIDATOR_MODEL", "artifacts/coreml/validator_minilm_l6_b1_s512.mlpackage")
COREML_VALIDATOR_TOKENIZER = os.getenv("COREML_VALIDATOR_TOKENIZER", "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli")
COREML_VALIDATOR_VERSION = os.getenv(
    "COREML_VALIDATOR_VERSION",
    f"{COREML_VALIDATOR_TOKENIZER}@{Path(COREML_VALIDATOR_MODEL).name}",
)
COREML_VALIDATOR_SEQ_LEN = _env_int("COREML_VALIDATOR_SEQ_LEN", 512)
COREML_VALIDATOR_ATTENTION_MASK_RANK = _env_int("COREML_VALIDATOR_ATTENTION_MASK_RANK", 4)
COREML_VALIDATOR_COMPUTE_UNITS = os.getenv("COREML_VALIDATOR_COMPUTE_UNITS", "cpu_only").strip().lower()
COREML_VALIDATOR_CONTEXT_MODE = os.getenv("COREML_VALIDATOR_CONTEXT_MODE", "windows").strip().lower()
COREML_VALIDATOR_PAIR_MODE = os.getenv("COREML_VALIDATOR_PAIR_MODE", "answer").strip().lower()
COREML_VALIDATOR_ISOLATE_PROCESS = _env_bool("COREML_VALIDATOR_ISOLATE_PROCESS", True)
COREML_VALIDATOR_WORKER_TIMEOUT_SEC = _env_float("COREML_VALIDATOR_WORKER_TIMEOUT_SEC", 60.0)
COREML_VALIDATOR_MAX_FAILURES = _env_int("COREML_VALIDATOR_MAX_FAILURES", 2)
COREML_VALIDATOR_FAILURE_COOLDOWN_SEC = _env_float("COREML_VALIDATOR_FAILURE_COOLDOWN_SEC", 300.0)
COREML_VALIDATOR_LABELS = [
    label.strip()
    for label in os.getenv("COREML_VALIDATOR_LABELS", "entailment,neutral,contradiction").split(",")
    if label.strip()
]
COREML_VALIDATOR_MIN_CONFIDENCE = _env_float("COREML_VALIDATOR_MIN_CONFIDENCE", 0.0)
COREML_VALIDATOR_ENTAILMENT_THRESHOLD = _env_float("COREML_VALIDATOR_ENTAILMENT_THRESHOLD", 0.8)
COREML_VALIDATOR_CONTRADICTION_THRESHOLD = _env_float("COREML_VALIDATOR_CONTRADICTION_THRESHOLD", 0.6)
COREML_VALIDATOR_DECISION_MARGIN = _env_float("COREML_VALIDATOR_DECISION_MARGIN", 0.05)
COREML_VALIDATOR_LOCAL_FILES_ONLY = _env_bool("COREML_VALIDATOR_LOCAL_FILES_ONLY", True)
COREML_VALIDATOR_FALLBACK = _env_bool("COREML_VALIDATOR_FALLBACK", True)
KEEP_SINGLE_LLM_LOADED = _env_bool("MLX_KEEP_SINGLE_LLM_LOADED", True)
MLX_HOST_BIND = os.getenv("MLX_HOST_BIND", "127.0.0.1")
RAM_WARN_FREE_GB = _env_float("MLX_RAM_WARN_FREE_GB", 8.0)
RAM_KILL_FREE_GB = _env_float("MLX_RAM_KILL_FREE_GB", 6.0)
EMBED_TTL_SEC = _env_int("MLX_EMBED_TTL_SEC", 300)

main_engine = MLXMemoryManager(model_path=MAIN_MODEL, ttl_seconds=300)
val_engine  = MLXMemoryManager(model_path=VAL_MODEL,  ttl_seconds=120)
_llm_policy_lock: asyncio.Lock | None = None
_llm_policy_lock_loop: asyncio.AbstractEventLoop | None = None


# ── Embeddings через sentence-transformers (MPS на Apple Silicon) ─────────────

class SentenceTransformersEmbedder:
    """
    Lazy-load обёртка над SentenceTransformer.
    Загружается при первом запросе, выгружается через force_unload().
    sentence-transformers автоматически использует MPS на M1/M2/M4.
    """

    def __init__(self, model_id: str = BGE_MODEL, ttl_seconds: int = EMBED_TTL_SEC):
        self.backend = "sentence_transformers"
        self.model_id = model_id
        self.ttl_seconds = ttl_seconds
        self._model = None
        self.last_used = 0.0
        self.fallback_active = False

    def _load(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        logger.info(f"[EMBED] Загрузка {self.model_id}...")
        self._model = SentenceTransformer(self.model_id)
        dim = self._model.get_embedding_dimension() if hasattr(self._model, 'get_embedding_dimension') else self._model.get_sentence_embedding_dimension()
        logger.info(f"[EMBED] модель готова. dim={dim}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        self._load()
        vecs = self._model.encode(
            texts,
            normalize_embeddings=True,  # L2-норма встроена
            show_progress_bar=False,
            batch_size=int(os.getenv("BGE_BATCH_SIZE", str(BGE_BATCH_SIZE))),
        )
        self.last_used = time.time()
        return [v.tolist() for v in vecs]

    def force_unload(self):
        if self._model is None:
            return
        self._model = None
        gc.collect()
        logger.info("[EMBED] модель выгружена.")

    def idle_seconds(self) -> float:
        if self._model is None or self.last_used <= 0:
            return 0.0
        return time.time() - self.last_used


class CoreMLEmbedder:
    """Core ML embedding backend for fixed-shape Qwen3 embedding packages."""

    def __init__(
        self,
        model_id: str = BGE_MODEL,
        model_path: str = COREML_EMBED_MODEL,
        *,
        seq_len: int = COREML_EMBED_SEQ_LEN,
        batch_size: int = COREML_EMBED_BATCH_SIZE,
        compute_units: str = COREML_EMBED_COMPUTE_UNITS,
        isolate_process: bool = COREML_EMBED_ISOLATE_PROCESS,
        worker_timeout_sec: float = COREML_EMBED_WORKER_TIMEOUT_SEC,
        max_failures: int = COREML_EMBED_MAX_FAILURES,
        failure_cooldown_sec: float = COREML_EMBED_FAILURE_COOLDOWN_SEC,
        worker_cmd: list[str] | None = None,
        ttl_seconds: int = EMBED_TTL_SEC,
        fallback: SentenceTransformersEmbedder | None = None,
    ):
        self.backend = "coreml"
        self.model_id = model_id
        self.model_path = model_path
        self.seq_len = seq_len
        self.batch_size = max(1, batch_size)
        self.compute_units = compute_units
        self.isolate_process = isolate_process
        self.worker_timeout_sec = max(1.0, float(worker_timeout_sec))
        self.max_failures = max(0, int(max_failures))
        self.failure_cooldown_sec = max(0.0, float(failure_cooldown_sec))
        self.worker_cmd = worker_cmd
        self.ttl_seconds = ttl_seconds
        self.fallback = fallback
        self.fallback_active = False
        self.last_fallback_error = ""
        self.worker_start_count = 0
        self.worker_restart_count = 0
        self.worker_failure_count = 0
        self.worker_exit_count = 0
        self.worker_last_returncode: int | None = None
        self.last_worker_error = ""
        self._model = None
        self._tokenizer = None
        self._worker: subprocess.Popen | None = None
        self._worker_lock = threading.Lock()
        self._worker_exit_observed = False
        self._request_counter = 0
        self._circuit_open_until = 0.0
        self.last_used = 0.0

    def _compute_unit(self):
        import coremltools as ct

        units = {
            "all": ct.ComputeUnit.ALL,
            "cpu_only": ct.ComputeUnit.CPU_ONLY,
            "cpu_and_gpu": ct.ComputeUnit.CPU_AND_GPU,
            "cpu_and_ne": ct.ComputeUnit.CPU_AND_NE,
        }
        if self.compute_units not in units:
            raise ValueError(f"unknown COREML_EMBED_COMPUTE_UNITS={self.compute_units!r}")
        return units[self.compute_units]

    def _load(self):
        if self._model is not None and self._tokenizer is not None:
            return
        import coremltools as ct
        from transformers import AutoTokenizer

        model_path = Path(self.model_path).expanduser()
        if not model_path.exists():
            raise FileNotFoundError(f"Core ML embedding package not found: {model_path}")
        logger.info(
            "[EMBED] Загрузка Core ML %s seq_len=%s batch=%s units=%s...",
            model_path,
            self.seq_len,
            self.batch_size,
            self.compute_units,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id,
            local_files_only=COREML_EMBED_LOCAL_FILES_ONLY,
        )
        self._model = ct.models.MLModel(str(model_path), compute_units=self._compute_unit())
        logger.info("[EMBED] Core ML модель готова. dim=1024")

    def _worker_command(self) -> list[str]:
        if self.worker_cmd is not None:
            return list(self.worker_cmd)
        script = Path(__file__).resolve().parent / "tools" / "coreml_embed_worker.py"
        cmd = [
            sys.executable,
            "-u",
            str(script),
            "--model-id",
            self.model_id,
            "--model-path",
            self.model_path,
            "--seq-len",
            str(self.seq_len),
            "--batch-size",
            str(self.batch_size),
            "--compute-units",
            self.compute_units,
        ]
        if COREML_EMBED_LOCAL_FILES_ONLY:
            cmd.append("--local-files-only")
        return cmd

    def worker_alive(self) -> bool:
        return self._observe_worker_exit() is None and self._worker is not None

    def worker_pid(self) -> int | None:
        if self._observe_worker_exit() is not None or self._worker is None:
            return None
        return self._worker.pid

    def circuit_open(self) -> bool:
        return self._circuit_open_until > time.time()

    def circuit_remaining_sec(self) -> float:
        return max(0.0, self._circuit_open_until - time.time())

    def _maybe_open_circuit(self):
        if self.max_failures <= 0 or self.worker_failure_count < self.max_failures:
            return
        if self.circuit_open():
            return
        self._circuit_open_until = time.time() + self.failure_cooldown_sec
        logger.warning(
            "[EMBED] Core ML embed circuit open for %.0fs after %s failures",
            self.failure_cooldown_sec,
            self.worker_failure_count,
        )

    def _observe_worker_exit(self) -> int | None:
        if self._worker is None:
            return None
        rc = self._worker.poll()
        if rc is None:
            return None
        if not self._worker_exit_observed:
            self._worker_exit_observed = True
            self.worker_exit_count += 1
            self.worker_last_returncode = rc
            self.last_worker_error = f"worker exited rc={rc}"
            if rc != 0:
                self.worker_failure_count += 1
                self._maybe_open_circuit()
            logger.warning("[EMBED] isolated Core ML worker exited rc=%s", rc)
        return rc

    def _start_worker(self):
        if self.worker_alive():
            return
        if self._worker is not None:
            self._close_worker_pipes(self._worker)
            self._worker = None

        env = os.environ.copy()
        env.setdefault("TOKENIZERS_PARALLELISM", "false")
        self.worker_start_count += 1
        if self.worker_start_count > 1:
            self.worker_restart_count += 1
        cmd = self._worker_command()
        logger.info("[EMBED] starting isolated Core ML worker: %s", " ".join(cmd))
        self._worker_exit_observed = False
        self._worker = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(Path(__file__).resolve().parent),
            env=env,
        )

    @staticmethod
    def _close_worker_pipes(proc: subprocess.Popen):
        for pipe in (proc.stdin, proc.stdout):
            if pipe is None:
                continue
            try:
                pipe.close()
            except Exception:
                pass

    def _terminate_worker(self):
        proc = self._worker
        self._worker = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        finally:
            self._close_worker_pipes(proc)

    def _read_worker_line(self) -> str:
        if self._worker is None or self._worker.stdout is None:
            raise RuntimeError("Core ML embed worker stdout is not available")
        fd = self._worker.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], self.worker_timeout_sec)
        if not ready:
            raise TimeoutError(f"Core ML embed worker timed out after {self.worker_timeout_sec:.1f}s")
        line = self._worker.stdout.readline()
        if not line:
            rc = self._worker.poll()
            raise RuntimeError(f"Core ML embed worker exited without response rc={rc}")
        return line

    def _encode_worker(self, texts: List[str]) -> List[List[float]]:
        with self._worker_lock:
            self._start_worker()
            if self._worker is None or self._worker.stdin is None:
                raise RuntimeError("Core ML embed worker stdin is not available")

            self._request_counter += 1
            request_id = str(self._request_counter)
            payload = {"id": request_id, "texts": list(texts)}
            try:
                self._worker.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._worker.stdin.flush()
                line = self._read_worker_line()
                response = json.loads(line)
            except Exception as exc:
                self.worker_failure_count += 1
                self.last_worker_error = str(exc)
                self._terminate_worker()
                raise

            if response.get("id") != request_id:
                self.worker_failure_count += 1
                self.last_worker_error = f"worker response id mismatch: {response.get('id')!r} != {request_id!r}"
                self._terminate_worker()
                raise RuntimeError(self.last_worker_error)
            if response.get("error"):
                self.worker_failure_count += 1
                self.last_worker_error = str(response["error"])
                raise RuntimeError(f"Core ML embed worker error: {response['error']}")

            vectors = response.get("vectors")
            if not isinstance(vectors, list):
                self.worker_failure_count += 1
                self.last_worker_error = "worker response missing vectors"
                raise RuntimeError(self.last_worker_error)
            self.last_worker_error = ""
            self.last_used = time.time()
            return vectors

    @staticmethod
    def _normalize(vecs):
        import numpy as np

        vecs = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    @staticmethod
    def _validate_vectors(texts: List[str], vectors: List[List[float]]):
        import math

        if len(vectors) != len(texts):
            raise ValueError(f"Core ML returned {len(vectors)} vectors for {len(texts)} texts")
        for index, vector in enumerate(vectors):
            if not isinstance(vector, list) or not vector:
                raise ValueError(f"Core ML returned an empty vector at index {index}")
            norm_sq = 0.0
            for value in vector:
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise ValueError(f"Core ML returned a non-finite vector value at index {index}")
                norm_sq += numeric * numeric
            norm = math.sqrt(norm_sq)
            if norm < COREML_EMBED_MIN_NORM or norm > COREML_EMBED_MAX_NORM:
                raise ValueError(
                    f"Core ML returned invalid vector norm at index {index}: "
                    f"{norm:.6f} not in [{COREML_EMBED_MIN_NORM}, {COREML_EMBED_MAX_NORM}]"
                )

    def _encode_coreml(self, texts: List[str]) -> List[List[float]]:
        import numpy as np

        self._load()
        vectors = []
        assert self._model is not None
        assert self._tokenizer is not None
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start:start + self.batch_size])
            real_size = len(batch)
            if real_size < self.batch_size:
                batch.extend([batch[-1]] * (self.batch_size - real_size))
            tokens = self._tokenizer(
                batch,
                padding="max_length",
                truncation=True,
                max_length=self.seq_len,
                return_tensors="np",
            )
            out = self._model.predict({
                "input_ids": tokens["input_ids"].astype(np.int32),
                "attention_mask": tokens["attention_mask"].astype(np.int32),
            })["embeddings"]
            vectors.append(self._normalize(out)[:real_size])
        self.last_used = time.time()
        return [v.tolist() for v in np.concatenate(vectors, axis=0)]

    def encode(self, texts: List[str]) -> List[List[float]]:
        if self.isolate_process and self.circuit_open():
            message = f"Core ML embed circuit open for {self.circuit_remaining_sec():.0f}s"
            if self.fallback is None:
                raise RuntimeError(message)
            self.fallback_active = True
            self.last_fallback_error = message
            vectors = self.fallback.encode(texts)
            self.last_used = time.time()
            return vectors
        try:
            self.fallback_active = False
            self.last_fallback_error = ""
            if self.isolate_process:
                vectors = self._encode_worker(texts)
            else:
                vectors = self._encode_coreml(texts)
            try:
                self._validate_vectors(texts, vectors)
            except Exception as exc:
                if self.isolate_process:
                    self.worker_failure_count += 1
                    self.last_worker_error = str(exc)
                    self._maybe_open_circuit()
                    self._terminate_worker()
                raise
            return vectors
        except Exception as exc:
            self._maybe_open_circuit()
            if self.fallback is None:
                raise
            self.fallback_active = True
            self.last_fallback_error = str(exc)
            logger.error("[EMBED] Core ML failed, fallback to sentence-transformers: %s", exc, exc_info=True)
            vectors = self.fallback.encode(texts)
            self.last_used = time.time()
            return vectors

    def force_unload(self):
        self._terminate_worker()
        had_model = self._model is not None or self._tokenizer is not None
        self._model = None
        self._tokenizer = None
        if self.fallback is not None:
            self.fallback.force_unload()
        if had_model:
            gc.collect()
            logger.info("[EMBED] Core ML модель выгружена.")

    def idle_seconds(self) -> float:
        fallback_loaded = self.fallback is not None and getattr(self.fallback, "_model", None) is not None
        worker_loaded = self.worker_alive()
        if (self._model is None and not worker_loaded and not fallback_loaded) or self.last_used <= 0:
            return 0.0
        return time.time() - self.last_used


def _build_embedder():
    if EMBED_BACKEND in {"coreml", "core_ml"}:
        fallback = SentenceTransformersEmbedder() if COREML_EMBED_FALLBACK else None
        return CoreMLEmbedder(fallback=fallback)
    return SentenceTransformersEmbedder()


embedder = _build_embedder()


def _embedder_loaded() -> bool:
    if getattr(embedder, "_model", None) is not None:
        return True
    if hasattr(embedder, "worker_alive") and embedder.worker_alive():
        return True
    fallback = getattr(embedder, "fallback", None)
    return bool(fallback is not None and getattr(fallback, "_model", None) is not None)


def _embedder_status() -> dict:
    status = {
        "path": BGE_MODEL,
        "profile": embed_profile_name(),
        "backend": getattr(embedder, "backend", "sentence_transformers"),
        "loaded": _embedder_loaded(),
        "batch_size": int(os.getenv("BGE_BATCH_SIZE", str(BGE_BATCH_SIZE))),
    }
    if isinstance(embedder, CoreMLEmbedder):
        status.update({
            "coreml_model": embedder.model_path,
            "coreml_model_exists": Path(embedder.model_path).expanduser().exists(),
            "coreml_model_id": embedder.model_id,
            "coreml_seq_len": embedder.seq_len,
            "coreml_batch_size": embedder.batch_size,
            "coreml_compute_units": embedder.compute_units,
            "coreml_local_files_only": COREML_EMBED_LOCAL_FILES_ONLY,
            "coreml_min_norm": COREML_EMBED_MIN_NORM,
            "coreml_max_norm": COREML_EMBED_MAX_NORM,
            "coreml_max_failures": embedder.max_failures,
            "coreml_failure_cooldown_sec": embedder.failure_cooldown_sec,
            "coreml_circuit_open": embedder.circuit_open(),
            "coreml_circuit_remaining_sec": round(embedder.circuit_remaining_sec(), 3),
            "coreml_isolated_process": embedder.isolate_process,
            "coreml_worker_alive": embedder.worker_alive(),
            "coreml_worker_pid": embedder.worker_pid(),
            "coreml_worker_timeout_sec": embedder.worker_timeout_sec,
            "coreml_worker_start_count": embedder.worker_start_count,
            "coreml_worker_restart_count": embedder.worker_restart_count,
            "coreml_worker_failure_count": embedder.worker_failure_count,
            "coreml_worker_exit_count": embedder.worker_exit_count,
            "coreml_worker_last_returncode": embedder.worker_last_returncode,
            "coreml_worker_last_error": embedder.last_worker_error,
            "fallback_enabled": embedder.fallback is not None,
            "fallback_active": embedder.fallback_active,
            "last_fallback_error": embedder.last_fallback_error if embedder.fallback_active else "",
        })
    return status


def _validator_backend_name() -> str:
    return os.getenv("VALIDATOR_BACKEND", VALIDATOR_BACKEND).strip().lower()


def _coreml_validator_loaded() -> bool:
    if COREML_VALIDATOR_ISOLATE_PROCESS:
        return bool(_coreml_validator_worker is not None and _coreml_validator_worker.worker_alive())
    return bool(_coreml_validator is not None and _coreml_validator._model is not None)


def _validator_status() -> dict:
    backend = _validator_backend_name()
    coreml_model_path = Path(COREML_VALIDATOR_MODEL).expanduser()
    fallback_active = bool(_coreml_validator_fallback_active)
    if backend == "coreml":
        active_model_id = COREML_VALIDATOR_TOKENIZER
        active_model = COREML_VALIDATOR_MODEL
        active_model_version = COREML_VALIDATOR_VERSION
    elif backend == "rules":
        active_model_id = "deterministic_rules"
        active_model = "deterministic_rules"
        active_model_version = "builtin:v1"
    else:
        active_model_id = val_engine.model_path
        active_model = val_engine.model_path
        active_model_version = VALIDATOR_MODEL_VERSION
    worker = _coreml_validator_worker if COREML_VALIDATOR_ISOLATE_PROCESS else None
    worker_alive = worker.worker_alive() if worker is not None else False
    worker_pid = worker.worker_pid() if worker is not None else None
    return {
        "path": val_engine.model_path,
        "model_id": val_engine.model_path,
        "model_version": active_model_version,
        "loaded": val_engine.model is not None,
        "backend": backend,
        "validator_backend": backend,
        "active_model": active_model,
        "active_model_id": active_model_id,
        "active_model_version": active_model_version,
        "fallback_enabled": COREML_VALIDATOR_FALLBACK if backend == "coreml" else False,
        "fallback_active": fallback_active,
        "last_fallback_error": _coreml_validator_last_error if fallback_active else "",
        "rules_deterministic": backend == "rules",
        "coreml_model": COREML_VALIDATOR_MODEL,
        "coreml_model_id": COREML_VALIDATOR_TOKENIZER,
        "coreml_model_version": COREML_VALIDATOR_VERSION,
        "coreml_model_exists": coreml_model_path.exists(),
        "coreml_tokenizer": COREML_VALIDATOR_TOKENIZER,
        "coreml_seq_len": COREML_VALIDATOR_SEQ_LEN,
        "coreml_attention_mask_rank": COREML_VALIDATOR_ATTENTION_MASK_RANK,
        "coreml_compute_units": COREML_VALIDATOR_COMPUTE_UNITS,
        "coreml_context_mode": COREML_VALIDATOR_CONTEXT_MODE,
        "coreml_pair_mode": COREML_VALIDATOR_PAIR_MODE,
        "coreml_labels": COREML_VALIDATOR_LABELS,
        "coreml_min_confidence": COREML_VALIDATOR_MIN_CONFIDENCE,
        "coreml_entailment_threshold": COREML_VALIDATOR_ENTAILMENT_THRESHOLD,
        "coreml_contradiction_threshold": COREML_VALIDATOR_CONTRADICTION_THRESHOLD,
        "coreml_decision_margin": COREML_VALIDATOR_DECISION_MARGIN,
        "coreml_loaded": _coreml_validator_loaded(),
        "coreml_fallback_enabled": COREML_VALIDATOR_FALLBACK,
        "coreml_isolated_process": COREML_VALIDATOR_ISOLATE_PROCESS,
        "coreml_worker_alive": worker_alive,
        "coreml_worker_pid": worker_pid,
        "coreml_worker_timeout_sec": COREML_VALIDATOR_WORKER_TIMEOUT_SEC,
        "coreml_worker_start_count": worker.worker_start_count if worker is not None else 0,
        "coreml_worker_restart_count": worker.worker_restart_count if worker is not None else 0,
        "coreml_worker_failure_count": worker.worker_failure_count if worker is not None else 0,
        "coreml_worker_exit_count": worker.worker_exit_count if worker is not None else 0,
        "coreml_worker_last_returncode": worker.worker_last_returncode if worker is not None else None,
        "coreml_worker_last_error": worker.last_worker_error if worker is not None else "",
        "coreml_max_failures": COREML_VALIDATOR_MAX_FAILURES,
        "coreml_failure_cooldown_sec": COREML_VALIDATOR_FAILURE_COOLDOWN_SEC,
        "coreml_circuit_open": worker.circuit_open() if worker is not None else False,
        "coreml_circuit_remaining_sec": round(worker.circuit_remaining_sec(), 3) if worker is not None else 0.0,
    }


class CoreMLValidator:
    """Core ML NLI/cross-encoder validator classifier."""

    def __init__(
        self,
        model_path: str = COREML_VALIDATOR_MODEL,
        tokenizer_id: str = COREML_VALIDATOR_TOKENIZER,
        *,
        seq_len: int = COREML_VALIDATOR_SEQ_LEN,
        attention_mask_rank: int = COREML_VALIDATOR_ATTENTION_MASK_RANK,
        compute_units: str = COREML_VALIDATOR_COMPUTE_UNITS,
        labels: list[str] | None = None,
        min_confidence: float = COREML_VALIDATOR_MIN_CONFIDENCE,
        context_mode: str = COREML_VALIDATOR_CONTEXT_MODE,
        pair_mode: str = COREML_VALIDATOR_PAIR_MODE,
        entailment_threshold: float = COREML_VALIDATOR_ENTAILMENT_THRESHOLD,
        contradiction_threshold: float = COREML_VALIDATOR_CONTRADICTION_THRESHOLD,
        decision_margin: float = COREML_VALIDATOR_DECISION_MARGIN,
    ):
        self.backend = "coreml"
        self.model_path = model_path
        self.tokenizer_id = tokenizer_id
        self.seq_len = seq_len
        self.attention_mask_rank = attention_mask_rank
        self.compute_units = compute_units
        self.labels = labels or COREML_VALIDATOR_LABELS
        self.min_confidence = max(0.0, float(min_confidence))
        self.context_mode = context_mode.strip().lower()
        self.pair_mode = pair_mode.strip().lower()
        self.entailment_threshold = max(0.0, float(entailment_threshold))
        self.contradiction_threshold = max(0.0, float(contradiction_threshold))
        self.decision_margin = max(0.0, float(decision_margin))
        self._model = None
        self._tokenizer = None

    def _compute_unit(self):
        import coremltools as ct

        units = {
            "all": ct.ComputeUnit.ALL,
            "cpu_only": ct.ComputeUnit.CPU_ONLY,
            "cpu_and_gpu": ct.ComputeUnit.CPU_AND_GPU,
            "cpu_and_ne": ct.ComputeUnit.CPU_AND_NE,
        }
        if self.compute_units not in units:
            raise ValueError(f"unknown COREML_VALIDATOR_COMPUTE_UNITS={self.compute_units!r}")
        return units[self.compute_units]

    def _load(self):
        if self._model is not None and self._tokenizer is not None:
            return
        import coremltools as ct
        from transformers import AutoTokenizer

        model_path = Path(self.model_path).expanduser()
        if not model_path.exists():
            raise FileNotFoundError(f"Core ML validator package not found: {model_path}")
        logger.info(
            "[VALIDATE] Загрузка Core ML validator %s seq_len=%s units=%s...",
            model_path,
            self.seq_len,
            self.compute_units,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.tokenizer_id,
            local_files_only=COREML_VALIDATOR_LOCAL_FILES_ONLY,
        )
        self._model = ct.models.MLModel(str(model_path), compute_units=self._compute_unit())

    @staticmethod
    def _status_for_label(label: str) -> str:
        normalized = label.strip().upper()
        if "ENTAIL" in normalized or normalized in {"VERIFIED", "SUPPORTS"}:
            return "VERIFIED"
        if "CONTRAD" in normalized or normalized in {"HALLUCINATION", "REFUTES"}:
            return "HALLUCINATION"
        return "NO_DATA"

    @staticmethod
    def _first_array(payload):
        import numpy as np

        preferred = ("logits", "scores", "output", "var_0")
        for key in preferred:
            if key in payload:
                return np.asarray(payload[key], dtype=np.float32)
        for value in payload.values():
            arr = np.asarray(value, dtype=np.float32)
            if arr.size:
                return arr
        raise ValueError("Core ML validator returned no numeric outputs")

    def _attention_mask(self, mask):
        import numpy as np

        if self.attention_mask_rank == 4:
            base = np.asarray(mask).astype(bool)
            return (base[:, None, None, :] & base[:, None, :, None]).astype(np.int32)
        return np.asarray(mask).astype(np.int32)

    def _context_windows(self, context: str) -> list[str]:
        context = context or ""
        if self.context_mode == "full":
            return [context]
        if self.context_mode != "windows":
            raise ValueError("COREML_VALIDATOR_CONTEXT_MODE must be one of: full, windows")
        parts = re.split(r"(?=\[Источник\s+\d+\s+\|)", context)
        windows = [part.strip() for part in parts if part.strip()]
        return windows or [context]

    def _hypothesis(self, req: "ValidateRequest") -> str:
        if self.pair_mode == "qa":
            return f"Вопрос: {req.question}\nОтвет: {req.answer}"
        if self.pair_mode == "answer":
            return req.answer or ""
        if self.pair_mode == "claim":
            return f'Ответ на вопрос "{req.question}": {req.answer}'
        raise ValueError("COREML_VALIDATOR_PAIR_MODE must be one of: answer, qa, claim")

    def _predict_window(self, premise: str, hypothesis: str) -> dict:
        import numpy as np

        assert self._model is not None
        assert self._tokenizer is not None
        tokens = self._tokenizer(
            premise,
            hypothesis,
            padding="max_length",
            truncation=True,
            max_length=self.seq_len,
            return_tensors="np",
        )
        inputs = {
            "input_ids": tokens["input_ids"].astype(np.int32),
            "attention_mask": self._attention_mask(tokens["attention_mask"]),
        }
        if "token_type_ids" in tokens:
            inputs["token_type_ids"] = tokens["token_type_ids"].astype(np.int32)
        logits = self._first_array(self._model.predict(inputs)).reshape(-1)
        label_count = min(len(self.labels), logits.shape[0])
        if label_count <= 0:
            raise ValueError("Core ML validator label map is empty")
        logits = logits[:label_count]
        exp = np.exp(logits - np.max(logits))
        probs = exp / np.sum(exp)
        index = int(np.argmax(probs))
        label = self.labels[index]
        scores_by_status = {"VERIFIED": 0.0, "NO_DATA": 0.0, "HALLUCINATION": 0.0}
        for idx, mapped_label in enumerate(self.labels[:label_count]):
            mapped_status = self._status_for_label(mapped_label)
            scores_by_status[mapped_status] = max(scores_by_status[mapped_status], float(probs[idx]))
        return {
            "label": label,
            "status": self._status_for_label(label),
            "score": float(probs[index]),
            "scores_by_status": scores_by_status,
        }

    def validate(self, req: "ValidateRequest") -> dict:
        self._load()
        assert self._model is not None
        assert self._tokenizer is not None

        hypothesis = self._hypothesis(req)
        window_results = [
            self._predict_window(window, hypothesis)
            for window in self._context_windows(req.context or "")
        ]
        max_scores = {"VERIFIED": 0.0, "NO_DATA": 0.0, "HALLUCINATION": 0.0}
        for result in window_results:
            for status_name, score_value in result["scores_by_status"].items():
                max_scores[status_name] = max(max_scores[status_name], score_value)

        entailment_score = max_scores["VERIFIED"]
        contradiction_score = max_scores["HALLUCINATION"]
        if (
            entailment_score >= self.entailment_threshold
            and entailment_score >= contradiction_score + self.decision_margin
        ):
            status = "VERIFIED"
            score = entailment_score
            raw = "WINDOW_ENTAILMENT"
        elif (
            contradiction_score >= self.contradiction_threshold
            and contradiction_score >= entailment_score + self.decision_margin
        ):
            status = "HALLUCINATION"
            score = contradiction_score
            raw = "WINDOW_CONTRADICTION"
        else:
            status = "NO_DATA"
            score = max(max_scores.values())
            raw = "WINDOW_UNCERTAIN"

        confidence_thresholded = False
        if self.min_confidence and score < self.min_confidence:
            status = "NO_DATA"
            confidence_thresholded = True
        return {
            "status": status,
            "raw": raw,
            "backend": "coreml",
            "score": score,
            "labels": self.labels,
            "scores": max_scores,
            "window_count": len(window_results),
            "model": self.model_path,
            "tokenizer": self.tokenizer_id,
            "attention_mask_rank": self.attention_mask_rank,
            "context_mode": self.context_mode,
            "pair_mode": self.pair_mode,
            "min_confidence": self.min_confidence,
            "entailment_threshold": self.entailment_threshold,
            "contradiction_threshold": self.contradiction_threshold,
            "decision_margin": self.decision_margin,
            "confidence_thresholded": confidence_thresholded,
            "unloaded_peer": [],
        }

    def force_unload(self):
        self._model = None
        self._tokenizer = None


class CoreMLValidatorWorker:
    """Crash-contained Core ML validator client."""

    def __init__(
        self,
        *,
        model_path: str = COREML_VALIDATOR_MODEL,
        tokenizer_id: str = COREML_VALIDATOR_TOKENIZER,
        seq_len: int = COREML_VALIDATOR_SEQ_LEN,
        attention_mask_rank: int = COREML_VALIDATOR_ATTENTION_MASK_RANK,
        compute_units: str = COREML_VALIDATOR_COMPUTE_UNITS,
        context_mode: str = COREML_VALIDATOR_CONTEXT_MODE,
        pair_mode: str = COREML_VALIDATOR_PAIR_MODE,
        labels: list[str] | None = None,
        min_confidence: float = COREML_VALIDATOR_MIN_CONFIDENCE,
        entailment_threshold: float = COREML_VALIDATOR_ENTAILMENT_THRESHOLD,
        contradiction_threshold: float = COREML_VALIDATOR_CONTRADICTION_THRESHOLD,
        decision_margin: float = COREML_VALIDATOR_DECISION_MARGIN,
        local_files_only: bool = COREML_VALIDATOR_LOCAL_FILES_ONLY,
        worker_timeout_sec: float = COREML_VALIDATOR_WORKER_TIMEOUT_SEC,
        max_failures: int = COREML_VALIDATOR_MAX_FAILURES,
        failure_cooldown_sec: float = COREML_VALIDATOR_FAILURE_COOLDOWN_SEC,
        worker_cmd: list[str] | None = None,
    ):
        self.backend = "coreml"
        self.model_path = model_path
        self.tokenizer_id = tokenizer_id
        self.seq_len = seq_len
        self.attention_mask_rank = attention_mask_rank
        self.compute_units = compute_units
        self.context_mode = context_mode
        self.pair_mode = pair_mode
        self.labels = labels or COREML_VALIDATOR_LABELS
        self.min_confidence = min_confidence
        self.entailment_threshold = entailment_threshold
        self.contradiction_threshold = contradiction_threshold
        self.decision_margin = decision_margin
        self.local_files_only = local_files_only
        self.worker_timeout_sec = max(1.0, float(worker_timeout_sec))
        self.max_failures = max(0, int(max_failures))
        self.failure_cooldown_sec = max(0.0, float(failure_cooldown_sec))
        self.worker_cmd = worker_cmd
        self.worker_start_count = 0
        self.worker_restart_count = 0
        self.worker_failure_count = 0
        self.worker_exit_count = 0
        self.worker_last_returncode: int | None = None
        self.last_worker_error = ""
        self._worker: subprocess.Popen | None = None
        self._worker_lock = threading.Lock()
        self._worker_exit_observed = False
        self._request_counter = 0
        self._circuit_open_until = 0.0

    def _worker_command(self) -> list[str]:
        if self.worker_cmd is not None:
            return list(self.worker_cmd)
        script = Path(__file__).resolve().parent / "tools" / "coreml_validator_worker.py"
        cmd = [
            sys.executable,
            "-u",
            str(script),
            "--model-path",
            self.model_path,
            "--tokenizer-id",
            self.tokenizer_id,
            "--seq-len",
            str(self.seq_len),
            "--attention-mask-rank",
            str(self.attention_mask_rank),
            "--compute-units",
            self.compute_units,
            "--context-mode",
            self.context_mode,
            "--pair-mode",
            self.pair_mode,
            "--labels",
            ",".join(self.labels),
            "--min-confidence",
            str(self.min_confidence),
            "--entailment-threshold",
            str(self.entailment_threshold),
            "--contradiction-threshold",
            str(self.contradiction_threshold),
            "--decision-margin",
            str(self.decision_margin),
        ]
        if self.local_files_only:
            cmd.append("--local-files-only")
        return cmd

    def worker_alive(self) -> bool:
        return self._observe_worker_exit() is None and self._worker is not None

    def worker_pid(self) -> int | None:
        if self._observe_worker_exit() is not None or self._worker is None:
            return None
        return self._worker.pid

    def circuit_open(self) -> bool:
        return self._circuit_open_until > time.time()

    def circuit_remaining_sec(self) -> float:
        return max(0.0, self._circuit_open_until - time.time())

    def _maybe_open_circuit(self):
        if self.max_failures <= 0 or self.worker_failure_count < self.max_failures:
            return
        if self.circuit_open():
            return
        self._circuit_open_until = time.time() + self.failure_cooldown_sec
        logger.warning(
            "[VALIDATE] Core ML validator circuit open for %.0fs after %s failures",
            self.failure_cooldown_sec,
            self.worker_failure_count,
        )

    def _observe_worker_exit(self) -> int | None:
        if self._worker is None:
            return None
        rc = self._worker.poll()
        if rc is None:
            return None
        if not self._worker_exit_observed:
            self._worker_exit_observed = True
            self.worker_exit_count += 1
            self.worker_last_returncode = rc
            self.last_worker_error = f"worker exited rc={rc}"
            if rc != 0:
                self.worker_failure_count += 1
                self._maybe_open_circuit()
            logger.warning("[VALIDATE] isolated Core ML validator worker exited rc=%s", rc)
        return rc

    @staticmethod
    def _close_worker_pipes(proc: subprocess.Popen):
        for pipe in (proc.stdin, proc.stdout):
            if pipe is None:
                continue
            try:
                pipe.close()
            except Exception:
                pass

    def _terminate_worker(self):
        proc = self._worker
        self._worker = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        finally:
            self._close_worker_pipes(proc)

    def _start_worker(self):
        if self.worker_alive():
            return
        if self._worker is not None:
            self._close_worker_pipes(self._worker)
            self._worker = None
        env = os.environ.copy()
        env.setdefault("TOKENIZERS_PARALLELISM", "false")
        self.worker_start_count += 1
        if self.worker_start_count > 1:
            self.worker_restart_count += 1
        cmd = self._worker_command()
        logger.info("[VALIDATE] starting isolated Core ML validator worker: %s", " ".join(cmd))
        self._worker_exit_observed = False
        self._worker = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(Path(__file__).resolve().parent),
            env=env,
        )

    def _read_worker_line(self) -> str:
        if self._worker is None or self._worker.stdout is None:
            raise RuntimeError("Core ML validator worker stdout is not available")
        fd = self._worker.stdout.fileno()
        ready, _, _ = select.select([fd], [], [], self.worker_timeout_sec)
        if not ready:
            raise TimeoutError(f"Core ML validator worker timed out after {self.worker_timeout_sec:.1f}s")
        line = self._worker.stdout.readline()
        if not line:
            rc = self._worker.poll()
            raise RuntimeError(f"Core ML validator worker exited without response rc={rc}")
        return line

    def validate(self, req: "ValidateRequest") -> dict:
        if self.circuit_open():
            raise RuntimeError(f"Core ML validator circuit open for {self.circuit_remaining_sec():.0f}s")
        with self._worker_lock:
            self._start_worker()
            if self._worker is None or self._worker.stdin is None:
                raise RuntimeError("Core ML validator worker stdin is not available")
            self._request_counter += 1
            request_id = str(self._request_counter)
            payload = {
                "id": request_id,
                "question": req.question,
                "answer": req.answer,
                "context": req.context,
            }
            try:
                self._worker.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._worker.stdin.flush()
                response = json.loads(self._read_worker_line())
            except Exception as exc:
                self.worker_failure_count += 1
                self.last_worker_error = str(exc)
                self._maybe_open_circuit()
                self._terminate_worker()
                raise

            if response.get("id") != request_id:
                self.worker_failure_count += 1
                self.last_worker_error = f"worker response id mismatch: {response.get('id')!r} != {request_id!r}"
                self._maybe_open_circuit()
                self._terminate_worker()
                raise RuntimeError(self.last_worker_error)
            if response.get("error"):
                self.worker_failure_count += 1
                self.last_worker_error = str(response["error"])
                self._maybe_open_circuit()
                raise RuntimeError(f"Core ML validator worker error: {response['error']}")
            result = response.get("result")
            if not isinstance(result, dict):
                self.worker_failure_count += 1
                self.last_worker_error = "worker response missing result"
                self._maybe_open_circuit()
                raise RuntimeError(self.last_worker_error)
            self.last_worker_error = ""
            return result

    def force_unload(self):
        self._terminate_worker()


_coreml_validator: CoreMLValidator | None = None
_coreml_validator_worker: CoreMLValidatorWorker | None = None
_coreml_validator_fallback_active = False
_coreml_validator_last_error = ""


def _coreml_validator_instance() -> CoreMLValidator:
    global _coreml_validator
    if _coreml_validator is None:
        _coreml_validator = CoreMLValidator()
    return _coreml_validator


def _coreml_validator_worker_instance() -> CoreMLValidatorWorker:
    global _coreml_validator_worker
    if _coreml_validator_worker is None:
        _coreml_validator_worker = CoreMLValidatorWorker()
    return _coreml_validator_worker


# ── Lifespan ──────────────────────────────────────────────────────────────────

# Порог свопа при котором выгружаем val-модель (%)
SWAP_WARN_PCT  = 70
# Порог критического давления: выгружаем только собственные модели.
SWAP_KILL_PCT  = 85


async def memory_guard_loop():
    """Мониторит RAM/swap каждые 30с и освобождает только память MLX Host."""
    import psutil
    await asyncio.sleep(30)  # даём системе стабилизироваться при старте
    while True:
        try:
            sw = psutil.swap_memory()
            vm = psutil.virtual_memory()
            ram_free_gb = vm.available / 1e9
            embed_idle = embedder.idle_seconds()
            if _embedder_loaded() and embed_idle >= embedder.ttl_seconds:
                logger.info("[MEM] Embedder idle %.0fs >= %ss — выгружаю", embed_idle, embedder.ttl_seconds)
                embedder.force_unload()

            critical = sw.percent >= SWAP_KILL_PCT or ram_free_gb < RAM_KILL_FREE_GB
            warning = sw.percent >= SWAP_WARN_PCT or ram_free_gb < RAM_WARN_FREE_GB
            if critical:
                logger.warning(
                    "[MEM] pressure critical: ram_free=%.1fGB, swap=%.0f%% — выгружаю idle MLX Host models",
                    ram_free_gb,
                    sw.percent,
                )
                _unload_engine_if_idle(main_engine, "main")
                _unload_engine_if_idle(val_engine, "val")
                embedder.force_unload()
            elif warning:
                logger.warning(
                    "[MEM] pressure warning: ram_free=%.1fGB, swap=%.0f%% — выгружаю idle val-модель",
                    ram_free_gb,
                    sw.percent,
                )
                _unload_engine_if_idle(val_engine, "val")
            else:
                logger.debug("[MEM] ram_free=%.1fGB, swap=%.0f%% — норма", ram_free_gb, sw.percent)
        except Exception as e:
            logger.warning(f"[MEM] memory_guard ошибка: {e}")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"[INIT] main  : {MAIN_MODEL}")
    logger.info(f"[INIT] val   : {VAL_MODEL}")
    logger.info(f"[INIT] val backend: {_validator_backend_name()}")
    logger.info(f"[INIT] embed : {BGE_MODEL} (lazy)")
    main_engine.start()
    val_engine.start()
    asyncio.create_task(memory_guard_loop())
    yield
    logger.info("[SHUTDOWN] Завершение работы.")
    embedder.force_unload()
    if _coreml_validator is not None:
        _coreml_validator.force_unload()
    if _coreml_validator_worker is not None:
        _coreml_validator_worker.force_unload()


app = FastAPI(title="LES MLX Native Host", version="3.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic схемы ────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    model:      str  = MAIN_MODEL
    prompt:     str
    stream:     bool = False
    max_tokens: int  = 2048


class EmbeddingRequest(BaseModel):
    """Ollama-совместимый запрос: принимает prompt или input."""
    input:  Optional[Union[str, List[str]]] = None
    prompt: Optional[Union[str, List[str]]] = None
    model:  str = "bge-m3"

    def get_texts(self) -> List[str]:
        raw = self.input if self.input is not None else self.prompt
        if raw is None:
            return []
        return [raw] if isinstance(raw, str) else list(raw)


class OAIMessage(BaseModel):
    role:    str
    content: Union[str, List]


class OAIChatRequest(BaseModel):
    model:       str            = MAIN_MODEL
    messages:    List[OAIMessage]
    stream:      bool           = False
    temperature: Optional[float] = 0.7
    max_tokens:  Optional[int]   = 2048


class OAIEmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = "bge-m3"


class ValidateRequest(BaseModel):
    question: str
    answer:   str
    context:  str = ""


class SwitchModelRequest(BaseModel):
    model:  str
    target: str = "main"  # "main" | "val"


# ── Хелперы ───────────────────────────────────────────────────────────────────

def _strip_think_tags(text: str) -> str:
    """Убирает блоки <think>…</think> и артефакты токенайзера из ответа Qwen3."""
    import re
    # Полный блок <think>…</think> (жадный, на случай нескольких)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Незакрытый <think> до конца строки
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    # Хвостовые стоп-токены, которые MLX иногда пропускает
    for token in ("<|im_end|>", "<|endoftext|>", "<|im_start|>", "</s>"):
        text = text.replace(token, "")
    return text.strip()


def _get_engine(model_name: str) -> "MLXMemoryManager":
    if model_name == VAL_MODEL:
        return val_engine
    return main_engine


def _get_llm_policy_lock() -> asyncio.Lock:
    global _llm_policy_lock, _llm_policy_lock_loop
    loop = asyncio.get_running_loop()
    if _llm_policy_lock is None or _llm_policy_lock_loop is not loop:
        _llm_policy_lock = asyncio.Lock()
        _llm_policy_lock_loop = loop
    return _llm_policy_lock


def _engine_is_busy(engine: "MLXMemoryManager") -> bool:
    is_busy = getattr(engine, "is_busy", None)
    if callable(is_busy):
        try:
            return bool(is_busy())
        except Exception:
            return False
    return False


def _unload_engine_if_idle(engine: "MLXMemoryManager", label: str) -> bool:
    if getattr(engine, "model", None) is None:
        return False
    if _engine_is_busy(engine):
        logger.warning("[UNLOAD] %s model is busy, unload postponed", label)
        return False
    engine._unload_model()
    return True


def _unload_peer_for(engine: "MLXMemoryManager") -> list[str]:
    if not KEEP_SINGLE_LLM_LOADED:
        return []
    unloaded: list[str] = []
    if engine is main_engine and val_engine.model is not None:
        if _unload_engine_if_idle(val_engine, "val"):
            unloaded.append("val")
    elif engine is val_engine and main_engine.model is not None:
        if _unload_engine_if_idle(main_engine, "main"):
            unloaded.append("main")
    return unloaded


async def _generate_with_llm_policy(
    engine: "MLXMemoryManager",
    *,
    prompt: str,
    max_tokens: int,
) -> tuple[str, list[str]]:
    async with _get_llm_policy_lock():
        unloaded_peer = _unload_peer_for(engine)
        answer = await engine.generate_text(prompt=prompt, max_tokens=max_tokens)
    return _strip_think_tags(answer), unloaded_peer


def _messages_to_prompt(messages: List[OAIMessage], engine: "MLXMemoryManager", enable_thinking: bool = False) -> str:
    """
    Строит промпт через chat_template токенизатора движка.
    Токенизатор загружен в engine.start() — без весов модели, быстро.
    enable_thinking=False по умолчанию — RAG-система не нуждается в цепочке рассуждений.
    """
    msgs = []
    for m in messages:
        if isinstance(m.content, str):
            text = m.content
        elif isinstance(m.content, list):
            text = " ".join(
                p.get("text", "") for p in m.content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text = str(m.content)
        msgs.append({"role": m.role, "content": text})

    return engine.apply_chat_template(msgs, enable_thinking=enable_thinking)


def _oai_response(content: str, model: str, prompt_tokens: int = 0) -> dict:
    completion_tokens = len(content.split())
    return {
        "id":      f"chatcmpl-les-{int(time.time())}",
        "object":  "chat.completion",
        "created": int(time.time()),
        "model":   model,
        "choices": [{
            "index":         0,
            "message":       {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      prompt_tokens + completion_tokens,
        },
    }


# ── Системные эндпоинты ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    import psutil
    sw = psutil.swap_memory()
    vm = psutil.virtual_memory()
    return {
        "status":      "ok",
        "main_model":  {"path": main_engine.model_path, "loaded": main_engine.model is not None},
        "val_model":   _validator_status(),
        "embed_model": _embedder_status(),
        "policy": {
            "keep_single_llm_loaded": KEEP_SINGLE_LLM_LOADED,
        },
        "memory": {
            "ram_free_gb":  round(vm.available / 1e9, 1),
            "swap_used_gb": round(sw.used / 1e9, 1),
            "swap_pct":     round(sw.percent, 1),
        },
    }


@app.post("/api/unload_val")
async def unload_val():
    """Принудительная выгрузка val-модели для освобождения памяти."""
    was_loaded = val_engine.model is not None
    if was_loaded:
        val_engine._unload_model()
    return {"unloaded": was_loaded, "val_model": val_engine.model_path}


@app.post("/api/unload_all")
async def unload_all():
    """Принудительно освобождает все тяжёлые модели между стресс-тестами."""
    state = {
        "main_model": main_engine.model is not None,
        "val_model": val_engine.model is not None,
        "embed_model": _embedder_loaded(),
        "coreml_validator": _coreml_validator_loaded(),
    }
    if state["main_model"]:
        main_engine.force_unload()
    if state["val_model"]:
        val_engine.force_unload()
    if state["embed_model"]:
        embedder.force_unload()
    if state["coreml_validator"] and _coreml_validator is not None:
        _coreml_validator.force_unload()
    if _coreml_validator_worker is not None:
        _coreml_validator_worker.force_unload()
    gc.collect()
    return {"unloaded": state}


@app.get("/api/host_memory")
async def host_memory():
    """Реальная память хоста (не Docker). Используется proxy для memory_guard."""
    import psutil
    sw = psutil.swap_memory()
    vm = psutil.virtual_memory()
    return {
        "ram_total_gb":  round(vm.total    / 1e9, 1),
        "ram_free_gb":   round(vm.available / 1e9, 1),
        "ram_used_pct":  round(vm.percent, 1),
        "swap_total_gb": round(sw.total / 1e9, 1),
        "swap_used_gb":  round(sw.used  / 1e9, 1),
        "swap_pct":      round(sw.percent, 1),
    }


@app.get("/api/ps")
async def api_ps():
    """Ollama-совместимый /api/ps — список загруженных моделей.
    Нужен proxy_server.py и metrics_collector.py для опроса статуса."""
    models = []
    if main_engine.model is not None:
        models.append({
            "name":       main_engine.model_path,
            "model":      main_engine.model_path,
            "size":       0,
            "digest":     "",
            "details":    {"family": "qwen3"},
            "expires_at": "",
        })
    if val_engine.model is not None:
        models.append({
            "name":       val_engine.model_path,
            "model":      val_engine.model_path,
            "size":       0,
            "digest":     "",
            "details":    {"family": "qwen3"},
            "expires_at": "",
        })
    return {"models": models}


@app.post("/api/switch_model")
async def switch_model(req: SwitchModelRequest):
    if req.target == "val":
        val_engine.force_unload()
        val_engine.model_path = req.model
        val_engine.reload_tokenizer()
        logger.info(f"[SWITCH] val → {req.model}")
    else:
        main_engine.force_unload()
        main_engine.model_path = req.model
        main_engine.reload_tokenizer()
        logger.info(f"[SWITCH] main → {req.model}")
    return {"status": "switched", "target": req.target, "model": req.model}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": main_engine.model_path, "object": "model", "created": 0, "owned_by": "mlx-community"},
            {"id": val_engine.model_path,  "object": "model", "created": 0, "owned_by": "mlx-community"},
            {"id": "bge-m3",               "object": "model", "created": 0, "owned_by": "mlx-community"},
        ],
    }


# ── Генерация ─────────────────────────────────────────────────────────────────

@app.post("/api/generate")
async def generate_ollama(req: GenerateRequest):
    """Ollama-совместимый endpoint для обратной совместимости."""
    engine = _get_engine(req.model)
    answer, _ = await _generate_with_llm_policy(engine, prompt=req.prompt, max_tokens=req.max_tokens)
    return {"model": req.model, "response": answer, "eval_count": len(answer.split())}


@app.post("/v1/chat/completions")
async def chat_completions(req: OAIChatRequest):
    """OpenAI-совместимый — основной для прокси и Roo Code."""
    engine = _get_engine(req.model or MAIN_MODEL)
    prompt = _messages_to_prompt(req.messages, engine)
    try:
        answer, _ = await _generate_with_llm_policy(
            engine,
            prompt=prompt,
            max_tokens=req.max_tokens or 2048,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _oai_response(answer, engine.model_path)


# ── Валидация (Т.О.С.К.А. v2) ────────────────────────────────────────────────

def _validation_limits() -> tuple[int, int]:
    context_limit = max(0, _env_int("MLX_VALIDATE_CONTEXT_CHARS", 8000))
    answer_limit = max(0, _env_int("MLX_VALIDATE_ANSWER_CHARS", 1500))
    return context_limit, answer_limit


def _validation_messages(req: ValidateRequest) -> list[dict[str, str]]:
    context_limit, answer_limit = _validation_limits()
    return [{
        "role": "system",
        "content": (
            "Ты — строгий валидатор. Отвечай ТОЛЬКО одним словом без пояснений: "
            "VERIFIED, NO_DATA или HALLUCINATION."
        ),
    }, {
        "role": "user",
        "content": (
            f"Вопрос: {req.question}\n"
            f"Контекст: {req.context[:context_limit] or 'не предоставлен'}\n"
            f"Ответ для проверки: {req.answer[:answer_limit]}\n\n"
            "VERIFIED — ответ подтверждается контекстом И отвечает на заданный вопрос.\n"
            "NO_DATA — контекст не содержит нужных данных для ответа на вопрос.\n"
            "HALLUCINATION — ответ противоречит контексту, содержит выдумки, "
            "или технически верен но НЕ отвечает на заданный вопрос.\n"
            "Одно слово:"
        ),
    }]


def _validation_prompt(req: ValidateRequest) -> str:
    # enable_thinking=False — валидатору не нужен <think> блок, нужен мгновенный ответ.
    return val_engine.apply_chat_template(_validation_messages(req), enable_thinking=False)


def _normalize_validation_status(raw: str) -> str:
    normalized = raw.strip().upper()
    if "VERIFIED" in normalized:
        return "VERIFIED"
    if "NO_DATA" in normalized or "NO DATA" in normalized:
        return "NO_DATA"
    if "HALLUCINATION" in normalized:
        return "HALLUCINATION"
    return "UNKNOWN"


async def _validate_with_mlx(req: ValidateRequest) -> dict:
    prompt = _validation_prompt(req)
    raw, unloaded_peer = await _generate_with_llm_policy(val_engine, prompt=prompt, max_tokens=64)
    raw = raw.upper()
    return {
        "status": _normalize_validation_status(raw),
        "raw": raw,
        "backend": "mlx",
        "unloaded_peer": unloaded_peer,
    }


def _normalize_rule_text(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", text.lower(), flags=re.UNICODE).split())


def _extract_rule_numbers(text: str) -> set[str]:
    return {match.group(0).replace(",", ".") for match in re.finditer(r"\d+(?:[,.]\d+)?", text)}


def _validate_with_rules(req: ValidateRequest) -> dict:
    context = req.context or ""
    answer = req.answer or ""
    if not context.strip():
        status = "NO_DATA"
        raw = "empty_context"
    elif answer.strip() and _normalize_rule_text(answer) in _normalize_rule_text(context):
        status = "VERIFIED"
        raw = "answer_text_found_in_context"
    else:
        answer_numbers = _extract_rule_numbers(answer)
        context_numbers = _extract_rule_numbers(context)
        if answer_numbers and context_numbers and not answer_numbers.issubset(context_numbers):
            status = "HALLUCINATION"
            raw = "answer_numeric_claim_not_in_context"
        else:
            status = "NO_DATA"
            raw = "rules_cannot_verify"
    return {
        "status": status,
        "raw": raw,
        "backend": "rules",
        "unloaded_peer": [],
    }


async def _validate_with_coreml(req: ValidateRequest) -> dict:
    global _coreml_validator_fallback_active, _coreml_validator_last_error
    try:
        if COREML_VALIDATOR_ISOLATE_PROCESS:
            result = _coreml_validator_worker_instance().validate(req)
        else:
            result = _coreml_validator_instance().validate(req)
        _coreml_validator_fallback_active = False
        _coreml_validator_last_error = ""
        return result
    except Exception as exc:
        _coreml_validator_fallback_active = True
        _coreml_validator_last_error = str(exc)
        if not COREML_VALIDATOR_FALLBACK:
            raise
        logger.warning("[VALIDATE] Core ML failed, fallback to MLX: %s", exc, exc_info=True)
        result = await _validate_with_mlx(req)
        result["fallback_from"] = "coreml"
        result["fallback_error"] = str(exc)
        return result


async def _validate_by_backend(req: ValidateRequest) -> dict:
    backend = _validator_backend_name()
    if backend == "mlx":
        return await _validate_with_mlx(req)
    if backend == "coreml":
        return await _validate_with_coreml(req)
    if backend == "rules":
        return _validate_with_rules(req)
    raise ValueError("VALIDATOR_BACKEND must be one of: mlx, coreml, rules")


@app.post("/api/validate")
async def validate_answer(req: ValidateRequest):
    """Проверка ответа. Возвращает VERIFIED / NO_DATA / HALLUCINATION."""
    try:
        result = await _validate_by_backend(req)
        logger.info("[VALIDATE:%s] → %s", result.get("backend", _validator_backend_name()), result.get("status"))
        return result
    except Exception as e:
        logger.warning(f"[VALIDATE] Ошибка: {e}")
        return {"status": "SKIP", "error": str(e), "backend": _validator_backend_name()}


# ── Эмбеддинги ───────────────────────────────────────────────────────────────

@app.post("/api/embeddings")
async def embeddings_ollama(req: EmbeddingRequest):
    """Ollama-формат: принимает prompt или input. Для qdrant_adapter."""
    texts = req.get_texts()
    if not texts:
        raise HTTPException(400, "Укажи input или prompt")
    try:
        vectors = embedder.encode(texts)
    except Exception as e:
        logger.error(f"[EMBED] /api/embeddings error: {e}", exc_info=True)
        raise HTTPException(500, f"Embedding error: {e}")

    if len(texts) == 1:
        return {"model": req.model, "embedding": vectors[0]}
    return {"model": req.model, "data": [{"embedding": v, "index": i} for i, v in enumerate(vectors)]}


@app.post("/v1/embeddings")
async def embeddings_openai(req: OAIEmbeddingRequest):
    """OpenAI-формат: для LlamaIndex / qdrant_adapter."""
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    try:
        vectors = embedder.encode(texts)
    except Exception as e:
        logger.error(f"[EMBED] /v1/embeddings error: {e}", exc_info=True)
        raise HTTPException(500, f"Embedding error: {e}")

    total_tokens = sum(len(t.split()) for t in texts)
    return {
        "object": "list",
        "data":   [{"object": "embedding", "embedding": v, "index": i} for i, v in enumerate(vectors)],
        "model":  req.model,
        "usage":  {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }


if __name__ == "__main__":
    uvicorn.run(app, host=MLX_HOST_BIND, port=8080, log_level="info")
