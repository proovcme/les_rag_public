"""Offline and reproducible defaults for the LES unit/integration test process."""

from __future__ import annotations

import os
import sys

import pytest


# Test collection/imports and health/config reads must not download models or
# depend on whether the workstation currently has internet access.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("RAG_TOKENIZER_LOCAL_FILES_ONLY", "true")

_HOST_ENV_ISOLATE = (
    "LES_ETM_LOGIN",
    "LES_ETM_PASSWORD",
    "RAG_UPLOAD_SUFFIXES",
    "RAG_CHAT_TOP_K",
    "RAG_CHAT_RERANK_POOL_K",
    "RAG_CHAT_RERANK_TOP_K",
    "RAG_CHAT_RERANK_CANDIDATE_K",
    "LES_SMETA_NORM_RERANK",
    "RERANKER_ENABLED",
    "LES_LLM_PROVIDER",
    "LES_SMETA_DOCUMENT_PROVIDER",
    "LES_SMETA_WORKFLOW_DECISION_PROVIDER",
)


def _reset_retrieval_import_constants() -> None:
    """Import-time RAG_CHAT_* constants must follow the isolated env, not LES-START."""
    module = sys.modules.get("proxy.services.retrieval_service")
    if module is None:
        return
    module.CHAT_TOP_K = int(os.getenv("RAG_CHAT_TOP_K", "64"))
    module.RERANK_POOL_K = int(os.getenv("RAG_CHAT_RERANK_POOL_K", "128"))
    module.RERANK_TOP_K = int(os.getenv("RAG_CHAT_RERANK_TOP_K", "64"))
    module.RERANK_CANDIDATE_K = int(
        os.getenv("RAG_CHAT_RERANK_CANDIDATE_K", str(module.RERANK_TOP_K))
    )


def _clear_host_env() -> None:
    for key in _HOST_ENV_ISOLATE:
        os.environ.pop(key, None)
    _reset_retrieval_import_constants()


_clear_host_env()


@pytest.fixture(autouse=True)
def _isolate_host_operator_env():
    """Keep LES-START / .env / document-app setdefault from leaking across tests."""
    _clear_host_env()
    yield
    _clear_host_env()
