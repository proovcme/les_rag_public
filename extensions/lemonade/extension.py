"""Approved Lemonade engine-management operations behind the shared registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from extensions.lemonade.model_policy import evaluate_flash_attention_policy
from proxy.services.model_connection_contracts import ConnectionLocality
from proxy.services.model_connection_security_service import (
    AddressResolver,
    ConnectionSecurityError,
    ValidatedEndpoint,
    system_resolver,
    validate_connected_peer,
    validate_endpoint,
)


_RECEIPT_SCHEMA = "les.lemonade.flash-attention-dry-run.v1"


class LemonadeEngineExtension:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        address_resolver: AddressResolver = system_resolver,
        peer_verifier: Callable[[httpx.Response, ValidatedEndpoint], None] = validate_connected_peer,
        error_factory: Callable[[str], Exception] = RuntimeError,
    ) -> None:
        self.client = client
        self.address_resolver = address_resolver
        self.peer_verifier = peer_verifier
        self.error_factory = error_factory

    def _error(self, code: str) -> Exception:
        return self.error_factory(code)

    def _endpoint(self, connection: Any) -> ValidatedEndpoint:
        try:
            locality = ConnectionLocality(getattr(connection, "locality", ""))
        except ValueError as exc:
            raise ConnectionSecurityError("LEMONADE_LOOPBACK_REQUIRED") from exc
        if locality is not ConnectionLocality.LOOPBACK:
            raise ConnectionSecurityError("LEMONADE_LOOPBACK_REQUIRED")
        return validate_endpoint(
            getattr(connection, "base_url", ""),
            locality,
            resolver=self.address_resolver,
            allow_private_http=False,
        )

    @staticmethod
    def _options_url(endpoint: ValidatedEndpoint, model_id: str) -> str:
        parsed = urlsplit(endpoint.canonical_base_url)
        origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
        return f"{origin}/v1/models/{quote(model_id, safe='')}/options"

    async def _request_json(
        self,
        endpoint: ValidatedEndpoint,
        url: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        try:
            response = await self.client.request(
                method,
                url,
                json=dict(body) if body is not None else None,
                follow_redirects=False,
            )
            self.peer_verifier(response, endpoint)
            if response.status_code != 200:
                raise self._error("LEMONADE_OPTIONS_UNAVAILABLE")
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise self._error("LEMONADE_OPTIONS_INVALID") from exc
        except ConnectionSecurityError:
            raise
        except httpx.HTTPError as exc:
            raise self._error("LEMONADE_OPTIONS_UNAVAILABLE") from exc
        if not isinstance(payload, Mapping):
            raise self._error("LEMONADE_OPTIONS_INVALID")
        return payload

    @staticmethod
    def _state_fingerprint(options: Mapping[str, Any]) -> str:
        semantic = {
            "recipe": options.get("recipe"),
            "saved": options.get("saved") if isinstance(options.get("saved"), Mapping) else {},
            "effective": (
                options.get("effective")
                if isinstance(options.get("effective"), Mapping)
                else {}
            ),
        }
        raw = json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"

    @staticmethod
    def _receipt(
        *,
        model_id: str,
        options: Mapping[str, Any],
        proposed_change: Mapping[str, Any],
    ) -> dict[str, Any]:
        semantic = {
            "schema": _RECEIPT_SCHEMA,
            "dry_run": True,
            "model": model_id,
            "recipe": "llamacpp",
            "state_fingerprint": LemonadeEngineExtension._state_fingerprint(options),
            "proposed_change": dict(proposed_change),
        }
        raw = json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            **semantic,
            "approval_ref": (
                "approval:lemonade:flash_attention:"
                f"{hashlib.sha256(raw).hexdigest()}"
            ),
        }

    async def _validated_preview(
        self,
        connection: Any,
    ) -> tuple[ValidatedEndpoint, str, Mapping[str, Any], dict[str, Any]]:
        endpoint = self._endpoint(connection)
        model_id = str(getattr(connection, "model_id", "") or "").strip()
        if not model_id:
            raise self._error("LEMONADE_MODEL_REQUIRED")
        url = self._options_url(endpoint, model_id)
        current = await self._request_json(endpoint, url)
        decision = evaluate_flash_attention_policy(current)
        if not decision.eligible:
            raise self._error(f"FLASH_ATTENTION_{decision.reason_code.upper()}")
        proposed = dict(decision.proposed_change)
        preview = await self._request_json(
            endpoint,
            url,
            method="POST",
            body={**proposed, "dry_run": True},
        )
        preview_decision = evaluate_flash_attention_policy(preview)
        if preview_decision.reason_code != "already_enabled":
            raise self._error("LEMONADE_DRY_RUN_INVALID")
        return endpoint, url, current, self._receipt(
            model_id=model_id,
            options=current,
            proposed_change=proposed,
        )

    async def status(self, connection: Any) -> Mapping[str, Any]:
        try:
            endpoint = self._endpoint(connection)
            model_id = str(getattr(connection, "model_id", "") or "").strip()
            if not model_id:
                return {"status": "blocked", "code": "LEMONADE_MODEL_REQUIRED"}
            options = await self._request_json(
                endpoint,
                self._options_url(endpoint, model_id),
            )
            decision = evaluate_flash_attention_policy(options)
        except ConnectionSecurityError as error:
            return {"status": "blocked", "code": str(error)}
        except (RuntimeError, TypeError, ValueError):
            return {"status": "unavailable"}
        flash_state = (
            "eligible"
            if decision.eligible
            else "enabled"
            if decision.reason_code == "already_enabled"
            else "not_applicable"
        )
        return {
            "status": "ok",
            "model": model_id,
            "recipe": str(options.get("recipe") or "unknown"),
            "flash_attention": flash_state,
        }

    async def execute(
        self,
        connection: Any,
        operation: str,
        arguments: Mapping[str, Any],
        approval_ref: str,
    ) -> Mapping[str, Any]:
        if operation != "flash_attention":
            raise self._error("EXTENSION_OPERATION_UNSUPPORTED")
        persist = arguments.get("persist", False)
        if not isinstance(persist, bool):
            raise self._error("EXTENSION_ARGUMENT_INVALID")

        supplied_receipt = arguments.get("dry_run_receipt")
        if persist:
            if not isinstance(supplied_receipt, Mapping):
                raise self._error("DRY_RUN_RECEIPT_REQUIRED")
            supplied_approval = str(supplied_receipt.get("approval_ref") or "").strip()
            if supplied_approval != approval_ref:
                raise self._error("APPROVAL_REFERENCE_MISMATCH")

        try:
            endpoint, url, current, current_receipt = await self._validated_preview(connection)
        except ConnectionSecurityError as error:
            raise self._error(str(error)) from error
        proposed = dict(current_receipt["proposed_change"])
        if not persist:
            return {
                "status": "validated",
                "model": current_receipt["model"],
                "recipe": current_receipt["recipe"],
                "proposed_change": proposed,
                "dry_run_receipt": current_receipt,
                "reload_required": True,
            }

        if dict(supplied_receipt) != current_receipt:
            raise self._error("DRY_RUN_RECEIPT_STALE")
        try:
            saved = await self._request_json(
                endpoint,
                url,
                method="POST",
                body=proposed,
            )
        except ConnectionSecurityError as error:
            raise self._error(str(error)) from error
        if evaluate_flash_attention_policy(saved).reason_code != "already_enabled":
            raise self._error("LEMONADE_PERSIST_RESULT_INVALID")
        return {
            "status": "saved",
            "model": current_receipt["model"],
            "approval_ref": approval_ref,
            "proposed_change": proposed,
            "reload_required": True,
            "previous_state_fingerprint": self._state_fingerprint(current),
        }
