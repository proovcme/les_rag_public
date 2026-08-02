"""Single, low-priority local extractor for durable Memory jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx

from proxy.memory_core.conflicts import register_fact_conflicts
from proxy.memory_core.contracts import EntryKind, EvidenceRef, MemoryEntry, ValidationStatus
from proxy.memory_core.store import MemoryStore
from proxy.memory_core.validation import initial_assertion_status


logger = logging.getLogger(__name__)
Extractor = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class MemoryWorker:
    def __init__(self, store: MemoryStore, shared_llm_semaphore: Any, extractor: Extractor | None = None):
        self.store = store
        self.shared_llm_semaphore = shared_llm_semaphore
        self.extractor = extractor or self._extract_local

    async def run(self) -> None:
        # Startup warmups and initial interactive work always get the local
        # model slot before background extraction is considered.
        await asyncio.sleep(30.0)
        while True:
            await asyncio.sleep(2.0)
            # Low priority means chat never waits for Memory to release its slot.
            if self.shared_llm_semaphore.locked():
                continue
            await self.run_once()

    async def run_once(self) -> bool:
        if self.shared_llm_semaphore.locked():
            return False
        await self.shared_llm_semaphore.acquire()
        try:
            job = await asyncio.to_thread(self.store.claim_next_job)
            if job is None:
                return False
            try:
                assertions = await self.extractor(job["payload"])
                await asyncio.to_thread(self._persist, int(job["project_id"]), job["payload"], assertions)
                await asyncio.to_thread(self.store.finish_job, job["job_id"])
            except Exception as error:
                logger.warning("[MEMORY] extraction job %s failed: %s", job["job_id"], error)
                await asyncio.to_thread(self.store.retry_job, job["job_id"], str(error))
            return True
        finally:
            self.shared_llm_semaphore.release()

    def _persist(self, project_id: int, payload: dict[str, Any], assertions: list[dict[str, Any]]) -> None:
        refs = [EvidenceRef(**ref) for ref in payload.get("evidence_refs", []) if ref.get("is_evidence")]
        for raw in assertions[:12]:
            subject = str(raw.get("subject") or "").strip()
            predicate = str(raw.get("predicate") or "").strip()
            if not subject or not predicate or raw.get("value") in (None, ""):
                continue
            entry = MemoryEntry(
                entry_id=uuid4().hex,
                project_id=project_id,
                kind=EntryKind.ASSERTION,
                subject=subject,
                predicate=predicate,
                value=raw["value"],
                provenance={
                    "source": "grounded_rag_turn",
                    "question_sha256": hashlib.sha256(str(payload.get("question") or "").encode()).hexdigest(),
                    "confirmation_kind": str(raw.get("confirmation_kind") or "ordinary_text"),
                    **({"computed": raw["computed"]} if isinstance(raw.get("computed"), dict) else {}),
                },
                source_version=str(raw.get("source_version") or ""),
            )
            entry.validation_status = initial_assertion_status(entry, refs)
            self.store.insert_entry(entry, refs)
            if entry.validation_status != ValidationStatus.REJECTED:
                register_fact_conflicts(self.store, entry)
        self.store.refresh_snapshot(project_id)

    async def _extract_local(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        base = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        model = os.getenv("LES_MEMORY_LOCAL_MODEL", os.getenv("OLLAMA_MODEL", "qwen3.5:9b")).strip()
        prompt = (
            "Extract only durable project facts explicitly supported by the evidence-backed answer. "
            "Return strict JSON object {\"assertions\":[{\"subject\":str,\"predicate\":str,"
            "\"value\":any,\"confirmation_kind\":\"ordinary_text\"}]}. "
            "Do not infer, generalize, or confirm a fact. Empty is valid.\n"
            + json.dumps({"question": payload.get("question"), "answer": payload.get("answer")}, ensure_ascii=False)
        )
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            response = await client.post(
                f"{base}/api/chat",
                json={"model": model, "stream": False, "think": False, "format": "json", "messages": [{"role": "user", "content": prompt}]},
            )
            response.raise_for_status()
        content = ((response.json().get("message") or {}).get("content") or "{}")
        parsed = json.loads(content)
        return list(parsed.get("assertions") or []) if isinstance(parsed, dict) else []
