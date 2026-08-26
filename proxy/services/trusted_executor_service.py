"""Trusted execution boundary for canonical LES tool contracts."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import time
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ToolContract,
)
from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
from proxy.services.structured_extract import validate as validate_json_schema
from proxy.services.tool_trace_policy import validate_tool_result


_APPROVAL_EFFECTS = {
    EffectClass.COMMIT,
    EffectClass.EXTERNAL,
    EffectClass.DESTRUCTIVE,
}
_SHADOW_BLOCKED_EFFECTS = {
    EffectClass.DRAFT,
    EffectClass.COMMIT,
    EffectClass.EXTERNAL,
    EffectClass.DESTRUCTIVE,
}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _public(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _public(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_public(item) for item in value]
    return value


def argument_sha256(arguments: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _public(arguments),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ExecutionRequest:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    allowed_dataset_ids: tuple[str, ...]
    actor_id: str
    actor_role: str
    approval_receipt_id: str | None
    idempotency_key: str | None
    deadline_monotonic: float
    shadow: bool = False


@dataclass(frozen=True)
class ExecutionEnvelope:
    schema: str
    call_id: str
    tool_name: str
    status: str
    code: str
    result: Mapping[str, Any]
    cursor: str | None
    omitted_items: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "code": self.code,
            "result": _public(self.result),
            "cursor": self.cursor,
            "omitted_items": self.omitted_items,
        }

    def metadata(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("result", None)
        return payload


@dataclass(frozen=True)
class ApprovalReceipt:
    receipt_id: str
    status: str
    proposal_revision: str
    tool_name: str
    argument_sha256: str
    actor_id: str
    expires_at_epoch: float


class SqliteExecutionStore:
    """Durable approval and idempotency state; writes are atomic and fail-closed."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tool_approval_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    proposal_revision TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    argument_sha256 TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    expires_at_epoch REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_idempotency_ledger (
                    actor_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    envelope_json TEXT NOT NULL DEFAULT '',
                    updated_at_epoch REAL NOT NULL,
                    PRIMARY KEY (actor_id, tool_name, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS tool_result_cursors (
                    cursor TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    expires_at_epoch REAL NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_approval_uses (
                    receipt_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    bound_at_epoch REAL NOT NULL
                );
                """
            )

    def issue_approval(self, receipt: ApprovalReceipt) -> None:
        """Persist an immutable receipt; callers cannot overwrite an issued approval."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_approval_receipts
                    (receipt_id, status, proposal_revision, tool_name,
                     argument_sha256, actor_id, expires_at_epoch)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.status,
                    receipt.proposal_revision,
                    receipt.tool_name,
                    receipt.argument_sha256,
                    receipt.actor_id,
                    receipt.expires_at_epoch,
                ),
            )

    def approval(self, receipt_id: str) -> ApprovalReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_approval_receipts WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
        return ApprovalReceipt(**dict(row)) if row is not None else None

    def revoke_approval(self, receipt_id: str) -> bool:
        with self._connect() as conn:
            return bool(
                conn.execute(
                    "UPDATE tool_approval_receipts SET status='revoked' WHERE receipt_id=?",
                    (receipt_id,),
                ).rowcount
            )

    def put_cursor(
        self,
        *,
        cursor: str,
        actor_id: str,
        expires_at_epoch: float,
        result: Mapping[str, Any],
    ) -> None:
        encoded = json.dumps(_public(result), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_result_cursors
                    (cursor, actor_id, expires_at_epoch, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (cursor, actor_id, expires_at_epoch, encoded),
            )
            conn.execute(
                "DELETE FROM tool_result_cursors WHERE expires_at_epoch <= ?",
                (time.time(),),
            )

    def resolve_cursor(self, cursor: str, *, actor_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT result_json FROM tool_result_cursors
                WHERE cursor=? AND actor_id=? AND expires_at_epoch>?
                """,
                (cursor, actor_id, time.time()),
            ).fetchone()
        return json.loads(str(row["result_json"])) if row is not None else None

    def claim(
        self,
        *,
        actor_id: str,
        tool_name: str,
        idempotency_key: str,
        fingerprint: str,
        approval_receipt_id: str,
    ) -> tuple[str, ExecutionEnvelope | None]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            approval_use = conn.execute(
                """
                SELECT actor_id, tool_name, idempotency_key, fingerprint
                FROM tool_approval_uses WHERE receipt_id=?
                """,
                (approval_receipt_id,),
            ).fetchone()
            operation_identity = (actor_id, tool_name, idempotency_key, fingerprint)
            if approval_use is None:
                conn.execute(
                    """
                    INSERT INTO tool_approval_uses
                        (receipt_id, actor_id, tool_name, idempotency_key,
                         fingerprint, bound_at_epoch)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (approval_receipt_id, *operation_identity, time.time()),
                )
            elif tuple(str(approval_use[key]) for key in approval_use.keys()) != operation_identity:
                return "approval_used", None
            row = conn.execute(
                """
                SELECT fingerprint, state, envelope_json
                FROM tool_idempotency_ledger
                WHERE actor_id=? AND tool_name=? AND idempotency_key=?
                """,
                (actor_id, tool_name, idempotency_key),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO tool_idempotency_ledger
                        (actor_id, tool_name, idempotency_key, fingerprint, state,
                         envelope_json, updated_at_epoch)
                    VALUES (?, ?, ?, ?, 'in_progress', '', ?)
                    """,
                    (actor_id, tool_name, idempotency_key, fingerprint, time.time()),
                )
                return "claimed", None
            if str(row["fingerprint"]) != fingerprint:
                return "conflict", None
            if str(row["state"]) == "completed" and str(row["envelope_json"]):
                return "completed", _envelope_from_payload(json.loads(row["envelope_json"]))
            return str(row["state"]), None

    def complete(
        self,
        *,
        actor_id: str,
        tool_name: str,
        idempotency_key: str,
        fingerprint: str,
        envelope: ExecutionEnvelope,
    ) -> None:
        self._set_state(
            actor_id=actor_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            state="completed",
            envelope_json=json.dumps(envelope.to_dict(), ensure_ascii=False, sort_keys=True),
        )

    def mark_ambiguous(
        self,
        *,
        actor_id: str,
        tool_name: str,
        idempotency_key: str,
        fingerprint: str,
    ) -> None:
        self._set_state(
            actor_id=actor_id,
            tool_name=tool_name,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            state="ambiguous",
            envelope_json="",
        )

    def _set_state(self, *, state: str, envelope_json: str, **identity: str) -> None:
        with self._connect() as conn:
            changed = conn.execute(
                """
                UPDATE tool_idempotency_ledger
                SET state=?, envelope_json=?, updated_at_epoch=?
                WHERE actor_id=? AND tool_name=? AND idempotency_key=? AND fingerprint=?
                """,
                (
                    state,
                    envelope_json,
                    time.time(),
                    identity["actor_id"],
                    identity["tool_name"],
                    identity["idempotency_key"],
                    identity["fingerprint"],
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("idempotency ledger claim was lost")


def _envelope_from_payload(payload: Mapping[str, Any]) -> ExecutionEnvelope:
    return ExecutionEnvelope(
        schema=str(payload["schema"]),
        call_id=str(payload["call_id"]),
        tool_name=str(payload["tool_name"]),
        status=str(payload["status"]),
        code=str(payload["code"]),
        result=_freeze(payload.get("result") or {}),
        cursor=str(payload["cursor"]) if payload.get("cursor") else None,
        omitted_items=int(payload.get("omitted_items") or 0),
    )


class TrustedExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        store: SqliteExecutionStore | None = None,
        cursor_ttl_seconds: int = 300,
        cursor_capacity: int = 128,
        scope_resolver: Callable[[ToolContract, Mapping[str, Any]], tuple[str, ...]] | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self._idempotency: dict[tuple[str, str], tuple[str, ExecutionEnvelope]] = {}
        self._cursor_results: OrderedDict[
            str, tuple[str, float, dict[str, Any]]
        ] = OrderedDict()
        self._cursor_ttl_seconds = cursor_ttl_seconds
        self._cursor_capacity = cursor_capacity
        self._scope_resolver = scope_resolver

    async def execute(self, request: ExecutionRequest) -> ExecutionEnvelope:
        registration = self.registry.get(request.tool_name)
        if registration is None:
            return self._envelope(request, "rejected", "TOOL_NOT_REGISTERED")
        contract = registration.contract
        if not request.call_id.strip() or not request.actor_id.strip():
            return self._envelope(request, "rejected", "TOOL_REQUEST_INVALID")
        if not isinstance(request.arguments, Mapping):
            return self._envelope(request, "rejected", "TOOL_SCHEMA_INVALID")
        schema_error = self._schema_error(contract, request.arguments)
        if schema_error:
            return self._envelope(request, "rejected", schema_error)
        if self._scope_escapes(contract, request.arguments, request.allowed_dataset_ids):
            return self._envelope(request, "rejected", "TOOL_SCOPE_VIOLATION")
        if request.deadline_monotonic <= time.monotonic():
            return self._envelope(request, "timeout", "TOOL_DEADLINE_EXCEEDED")

        try:
            fingerprint = f"{request.tool_name}:{argument_sha256(request.arguments)}"
        except (TypeError, ValueError):
            return self._envelope(request, "rejected", "TOOL_ARGUMENTS_NOT_JSON")
        if request.shadow and contract.effect in _SHADOW_BLOCKED_EFFECTS:
            return self._envelope(
                request,
                "shadow",
                "TOOL_WOULD_EXECUTE",
                {"effect": contract.effect.value, "persisted": False},
            )
        if contract.effect in _APPROVAL_EFFECTS and request.actor_role != "admin":
            return self._envelope(
                request,
                "rejected",
                "TOOL_AUTHORIZATION_REQUIRED",
            )
        if contract.effect in _APPROVAL_EFFECTS or contract.approval_required:
            try:
                approval_matches = self._approval_matches(
                    contract, request, fingerprint.split(":", 1)[1]
                )
            except (sqlite3.Error, RuntimeError):
                return self._envelope(request, "error", "TOOL_EXECUTION_STATE_ERROR")
            if not approval_matches:
                return self._envelope(request, "rejected", "TOOL_APPROVAL_REQUIRED")

        try:
            idempotency_error, replay, durable_claimed = self._idempotency_preflight(
                contract, request, fingerprint
            )
        except (sqlite3.Error, RuntimeError, ValueError, KeyError):
            return self._envelope(request, "error", "TOOL_EXECUTION_STATE_ERROR")
        if idempotency_error:
            return self._envelope(request, "rejected", idempotency_error)
        if replay is not None:
            return replay

        timeout = min(
            float(contract.timeout_seconds),
            max(0.0, request.deadline_monotonic - time.monotonic()),
        )
        try:
            raw = await asyncio.wait_for(
                self._invoke(registration, dict(request.arguments)),
                timeout=timeout,
            )
        except TimeoutError:
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(request, "timeout", "TOOL_DEADLINE_EXCEEDED")
        except Exception as exc:  # noqa: BLE001 - boundary converts handler failures
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(
                request,
                "error",
                "TOOL_HANDLER_ERROR",
                {"error_type": type(exc).__name__},
            )
        if not isinstance(raw, Mapping):
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(request, "error", "TOOL_RESULT_INVALID")
        public_raw = _public(raw)
        if str(public_raw.get("schema") or "") != contract.result_schema:
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(request, "error", "TOOL_RESULT_SCHEMA_MISMATCH")
        if contract.result_schema == "les_tool_result_v1" and not self._valid_tool_result(
            public_raw
        ):
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(request, "error", "TOOL_RESULT_INVALID")
        if str(public_raw.get("tool") or "") != contract.name:
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(request, "error", "TOOL_RESULT_INVALID")

        try:
            result = self._budget_result(contract, request, public_raw)
        except (TypeError, ValueError, sqlite3.Error, RuntimeError):
            self._mark_ambiguous(request, fingerprint, durable_claimed)
            return self._envelope(request, "error", "TOOL_RESULT_INVALID")
        if request.idempotency_key and result.status in {"ok", "overflow"}:
            if durable_claimed and self.store is not None:
                try:
                    self.store.complete(
                        actor_id=request.actor_id,
                        tool_name=request.tool_name,
                        idempotency_key=request.idempotency_key,
                        fingerprint=fingerprint,
                        envelope=result,
                    )
                except (sqlite3.Error, RuntimeError, TypeError, ValueError):
                    self._mark_ambiguous(request, fingerprint, durable_claimed)
                    return self._envelope(
                        request, "error", "TOOL_EXECUTION_STATE_ERROR"
                    )
            else:
                self._idempotency[(request.actor_id, request.idempotency_key)] = (
                    fingerprint,
                    result,
                )
        return result

    def resolve_cursor(self, cursor: str, *, actor_id: str) -> dict[str, Any] | None:
        if self.store is not None:
            stored = self.store.resolve_cursor(str(cursor), actor_id=actor_id)
            if stored is not None:
                return stored
        value = self._cursor_results.get(str(cursor))
        if value is None:
            return None
        owner, expires_at, raw = value
        if owner != actor_id or expires_at <= time.monotonic():
            return None
        self._cursor_results.move_to_end(str(cursor))
        return _public(raw)

    async def _invoke(
        self,
        registration: ToolRegistration,
        arguments: dict[str, Any],
    ) -> Any:
        if inspect.iscoroutinefunction(registration.handler):
            return await registration.handler(arguments)
        value = await asyncio.to_thread(registration.handler, arguments)
        if inspect.isawaitable(value):
            return await value
        return value

    def _schema_error(
        self,
        contract: ToolContract,
        arguments: Mapping[str, Any],
    ) -> str | None:
        schema = contract.input_schema
        if schema.get("type") not in (None, "object"):
            return "TOOL_SCHEMA_UNSUPPORTED"
        if validate_json_schema(_public(arguments), _public(schema)):
            return "TOOL_SCHEMA_INVALID"
        return None

    def _valid_tool_result(self, payload: Mapping[str, Any]) -> bool:
        if not validate_tool_result(dict(payload)).get("ok"):
            return False
        required_types = {
            "operation": str,
            "inputs": list,
            "status": str,
            "result": dict,
            "sources": list,
            "missing": list,
            "warnings": list,
            "trace": str,
            "decision_required_from_model": bool,
        }
        if any(not isinstance(payload.get(key), kind) for key, kind in required_types.items()):
            return False
        return str(payload.get("status")) in {"ok", "missing", "blocked", "error"}

    def _scope_escapes(
        self,
        contract: ToolContract,
        arguments: Mapping[str, Any],
        allowed_dataset_ids: tuple[str, ...],
    ) -> bool:
        allowed = {str(item) for item in allowed_dataset_ids if str(item)}
        if "*" in allowed:
            return False
        requested: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    if key == "dataset_id" and item:
                        requested.add(str(item))
                    elif key == "dataset_ids" and isinstance(item, (list, tuple, set)):
                        requested.update(str(entry) for entry in item if str(entry))
                    else:
                        collect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)

        collect(arguments)
        if self._scope_resolver is not None:
            requested.update(
                str(item)
                for item in self._scope_resolver(contract, arguments)
                if str(item)
            )
        if not requested:
            return True
        return bool(requested - allowed)

    def _approval_matches(
        self,
        contract: ToolContract,
        request: ExecutionRequest,
        argument_hash: str,
    ) -> bool:
        if self.store is None or not request.approval_receipt_id:
            return False
        approval = self.store.approval(request.approval_receipt_id)
        if approval is None:
            return False
        proposal_revision = str(request.arguments.get("proposal_revision") or "")
        return bool(
            proposal_revision
            and approval.status == "approved"
            and approval.expires_at_epoch > time.time()
            and approval.proposal_revision == proposal_revision
            and approval.tool_name == contract.name
            and approval.argument_sha256 == argument_hash
            and approval.actor_id == request.actor_id
        )

    def _idempotency_preflight(
        self,
        contract: ToolContract,
        request: ExecutionRequest,
        fingerprint: str,
    ) -> tuple[str | None, ExecutionEnvelope | None, bool]:
        key = str(request.idempotency_key or "").strip()
        if (
            contract.idempotency is IdempotencyPolicy.REQUIRED
            or contract.effect in _APPROVAL_EFFECTS
        ) and not key:
            return "TOOL_IDEMPOTENCY_KEY_REQUIRED", None, False
        if not key:
            return None, None, False
        if contract.effect in _APPROVAL_EFFECTS:
            if self.store is None:
                return "TOOL_DURABLE_IDEMPOTENCY_REQUIRED", None, False
            state, envelope = self.store.claim(
                actor_id=request.actor_id,
                tool_name=request.tool_name,
                idempotency_key=key,
                fingerprint=fingerprint,
                approval_receipt_id=str(request.approval_receipt_id or ""),
            )
            codes = {
                "conflict": "TOOL_IDEMPOTENCY_CONFLICT",
                "in_progress": "TOOL_EXECUTION_IN_PROGRESS",
                "ambiguous": "TOOL_EXECUTION_AMBIGUOUS",
                "approval_used": "TOOL_APPROVAL_ALREADY_USED",
            }
            if state == "completed":
                if (
                    envelope is not None
                    and envelope.cursor
                    and self.store.resolve_cursor(
                        envelope.cursor, actor_id=request.actor_id
                    )
                    is None
                ):
                    return "TOOL_RESULT_REFERENCE_EXPIRED", None, False
                return None, envelope, False
            if state != "claimed":
                return codes.get(state, "TOOL_IDEMPOTENCY_STATE_INVALID"), None, False
            return None, None, True
        previous = self._idempotency.get((request.actor_id, key))
        if previous is None:
            return None, None, False
        previous_fingerprint, envelope = previous
        if previous_fingerprint != fingerprint:
            return "TOOL_IDEMPOTENCY_CONFLICT", None, False
        return None, envelope, False

    def _mark_ambiguous(
        self,
        request: ExecutionRequest,
        fingerprint: str,
        durable_claimed: bool,
    ) -> None:
        if durable_claimed and self.store is not None and request.idempotency_key:
            try:
                self.store.mark_ambiguous(
                    actor_id=request.actor_id,
                    tool_name=request.tool_name,
                    idempotency_key=request.idempotency_key,
                    fingerprint=fingerprint,
                )
            except (sqlite3.Error, RuntimeError):
                # The claim remains in_progress and therefore still fails closed.
                pass

    def _budget_result(
        self,
        contract: ToolContract,
        request: ExecutionRequest,
        raw: dict[str, Any],
    ) -> ExecutionEnvelope:
        encoded = json.dumps(
            raw,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        item_count = self._item_count(raw)
        budget = contract.result_budget
        if len(encoded) <= budget.max_chars and item_count <= budget.max_items:
            return self._envelope(request, "ok", "TOOL_OK", raw)
        cursor = f"tool-result:{request.call_id}:{uuid4().hex}"
        if self.store is not None:
            self.store.put_cursor(
                cursor=cursor,
                actor_id=request.actor_id,
                expires_at_epoch=time.time() + self._cursor_ttl_seconds,
                result=raw,
            )
        else:
            self._cursor_results[cursor] = (
                request.actor_id,
                time.monotonic() + self._cursor_ttl_seconds,
                raw,
            )
            self._cursor_results.move_to_end(cursor)
            while len(self._cursor_results) > self._cursor_capacity:
                self._cursor_results.popitem(last=False)
        omitted_items = max(0, item_count - budget.max_items)
        return self._envelope(
            request,
            "overflow",
            "TOOL_RESULT_BUDGET_EXCEEDED",
            {
                "schema": contract.result_schema,
                "reference": cursor,
                "whole_result_stored": True,
            },
            cursor=cursor,
            omitted_items=omitted_items,
        )

    def _item_count(self, value: Any) -> int:
        if isinstance(value, Mapping):
            return sum(self._item_count(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return len(value) + sum(self._item_count(item) for item in value)
        return 0

    def _envelope(
        self,
        request: ExecutionRequest,
        status: str,
        code: str,
        result: Mapping[str, Any] | None = None,
        *,
        cursor: str | None = None,
        omitted_items: int = 0,
    ) -> ExecutionEnvelope:
        return ExecutionEnvelope(
            schema="les_tool_execution_v1",
            call_id=request.call_id,
            tool_name=request.tool_name,
            status=status,
            code=code,
            result=_freeze(result or {}),
            cursor=cursor,
            omitted_items=omitted_items,
        )
