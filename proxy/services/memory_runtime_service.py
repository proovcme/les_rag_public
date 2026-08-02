"""Lifecycle boundary for Memory Core.

An explicit ``LES_MEMORY_MODE=off`` keeps startup on the Null port and does not
open MetaDB.  The root-admin API may still open the store on demand to edit the
next-start configuration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from proxy.memory_core.config import load_memory_config
from proxy.memory_core.contracts import MemoryMode
from proxy.memory_core.store import MemoryStore
from proxy.services.memory_port import configure_memory_port
from proxy.services.memory_rag_adapter import ActiveMemoryPort


logger = logging.getLogger(__name__)
_store: MemoryStore | None = None
_worker_task: asyncio.Task | None = None


def get_memory_store(*, create: bool = False) -> MemoryStore:
    global _store
    if _store is None:
        if not create:
            raise RuntimeError("Memory store is not initialized")
        _store = MemoryStore()
    return _store


async def initialize_memory_runtime(shared_llm_semaphore: Any) -> None:
    global _store, _worker_task
    try:
        _store = MemoryStore()
        config = load_memory_config(_store)
        if config.mode == MemoryMode.OFF:
            configure_memory_port(None)
            logger.info("[MEMORY] disabled")
            return
        configure_memory_port(ActiveMemoryPort(_store, config))
        from proxy.services.memory_worker_service import MemoryWorker

        worker = MemoryWorker(_store, shared_llm_semaphore)
        _worker_task = asyncio.create_task(worker.run(), name="les-memory-worker")
        logger.info("[MEMORY] mode=%s worker started", config.mode.value)
    except Exception:
        configure_memory_port(None)
        logger.exception("[MEMORY] initialization failed open; NullMemoryPort retained")


async def shutdown_memory_runtime() -> None:
    global _worker_task
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
