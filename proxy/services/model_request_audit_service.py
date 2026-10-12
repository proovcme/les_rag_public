"""Request-local, immutable body receipts; never captures HTTP headers/configuration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


class ModelRequestAudit:
    def __init__(self, *, directory: Path, purpose: str, refs: list[dict]):
        self.directory = Path(directory)
        self.purpose = purpose
        self.refs = refs

    def _write(self, filename: str, data: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / (filename + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Publishing a hard link is atomic and refuses an existing final;
            # replace/rename can overwrite on some platforms.
            os.link(temporary, self.directory / filename)
        finally:
            try:
                temporary.unlink()
            except OSError:
                # A leftover temporary never invalidates a published final.
                pass

    @staticmethod
    def _unavailable(ref: dict) -> None:
        # Body proof is added only after a successful immutable publication.
        # An event failure must not erase that proof or request correlation.
        ref.pop("http_status", None)
        ref.update(status="audit_unavailable", error_code="MODEL_REQUEST_AUDIT_WRITE_FAILED")

    def prepare(self, body: bytes, *, revision_id: str, model_id: str) -> dict:
        receipt_id = uuid4().hex
        ref = {"receipt_id": receipt_id, "purpose": self.purpose,
               "attempt": len(self.refs) + 1, "revision_id": revision_id, "model_id": model_id}
        self.refs.append(ref)
        try:
            value = json.loads(body)
            body_file = receipt_id + ".body.json"
            self._write(body_file, body)
            ref.update(body_file=body_file, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                       tool_choice="present" if "tool_choice" in value else "omitted")
            self.mark(ref, "prepared")
        except (OSError, ValueError, TypeError):
            self._unavailable(ref)
        return ref

    def mark(self, ref: dict, status: str, *, http_status: int | None = None) -> None:
        if ref.get("status") == "audit_unavailable":
            return
        event = {**ref, "status": status}
        if http_status is not None:
            event["http_status"] = http_status
        try:
            self._write(ref["receipt_id"] + "." + status + ".json",
                        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (OSError, ValueError, TypeError):
            self._unavailable(ref)
            return
        ref.update(event)
