"""Tool harness API.

These endpoints expose controlled LES tools for GUI/CLI dry-runs. They do not
grant the model autonomous filesystem access.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from proxy.config import META_DB_PATH
from proxy.security import require_admin, require_user
from proxy.services.tool_harness_service import harness, resolve_authoritative_dataset_scope
from proxy.services.tool_registry_service import canonical_tool_registry
from proxy.services.trusted_executor_service import (
    ExecutionRequest,
    SqliteExecutionStore,
    TrustedExecutor,
)

router = APIRouter(prefix="/api/tools", tags=["tools"])
_TRUSTED_EXECUTOR: TrustedExecutor | None = None


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    args: dict[str, Any] = Field(default_factory=dict)
    approval_receipt_id: str | None = Field(default=None, max_length=240)
    idempotency_key: str | None = Field(default=None, max_length=240)
    timeout_seconds: float = Field(default=120, gt=0, le=120)


class ToolShortlistRequest(BaseModel):
    question: str = Field(default="", max_length=4000)
    mode: str = Field(default="", max_length=120)
    limit: int = Field(default=5, ge=1, le=12)


@router.get("/registry")
async def tool_registry(category: str = "", _user=Depends(require_user)):
    return harness().registry(category=category)


@router.post("/shortlist")
async def tool_shortlist(req: ToolShortlistRequest, _user=Depends(require_user)):
    return harness().shortlist(req.question, mode=req.mode, limit=req.limit)


@router.post("/call")
async def tool_call(req: ToolCallRequest, _admin=Depends(require_admin)):
    actor_id = _actor_id(_admin)
    actor_role = str(getattr(_admin, "role", "admin") or "admin")
    envelope = await _executor().execute(
        ExecutionRequest(
            call_id=f"api:{req.tool}:{time.monotonic_ns()}",
            tool_name=req.tool,
            arguments=req.args,
            # This endpoint is admin-only; its broad scope is server-owned and
            # cannot be widened by request JSON. User chat supplies exact scope
            # through its own trusted execution context.
            allowed_dataset_ids=("*",),
            actor_id=actor_id,
            actor_role=actor_role,
            approval_receipt_id=req.approval_receipt_id,
            idempotency_key=req.idempotency_key,
            deadline_monotonic=time.monotonic() + req.timeout_seconds,
        )
    )
    payload = envelope.to_dict()
    nested = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if envelope.status == "ok" and nested.get("schema") == "les_tool_result_v1":
        nested["execution"] = envelope.metadata()
        return nested
    return payload


@router.get("/filesystem/roots")
async def filesystem_roots(_user=Depends(require_user)):
    return await harness().call_async("filesystem_roots", {})


@router.get("/filesystem/list")
async def filesystem_list(
    root: str = Query(default="docs", max_length=80),
    path: str = Query(default="", max_length=2000),
    depth: int = Query(default=1, ge=0, le=4),
    _user=Depends(require_user),
):
    return await harness().call_async(
        "filesystem_list", {"root": root, "path": path, "depth": depth}
    )


def _executor() -> TrustedExecutor:
    global _TRUSTED_EXECUTOR
    if _TRUSTED_EXECUTOR is None:
        _TRUSTED_EXECUTOR = TrustedExecutor(
            canonical_tool_registry(),
            store=SqliteExecutionStore(META_DB_PATH),
            scope_resolver=resolve_authoritative_dataset_scope,
        )
    return _TRUSTED_EXECUTOR


def _actor_id(actor: Any) -> str:
    key_value = str(getattr(actor, "key_value", "") or "")
    if key_value:
        digest = hashlib.sha256(key_value.encode("utf-8")).hexdigest()
        return f"api-key:{digest}"
    source = str(getattr(actor, "source", "") or "trusted")
    holder = str(getattr(actor, "holder", "") or "admin")
    return f"{source}:{holder}"
