"""Self-contained, server-owned collections of existing read attachments.

The archive is a transport container, never a user ZIP interpretation. Only the
server metadata and the verified parent hash admit it to the source catalog.
Original members stay byte-for-byte inside the parent after child expiry.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from proxy.services.chat_attachment_service import (
    _paths, _sha256, resolve_read_attachment,
)

COLLECTION_SCHEMA = "les.chat-attachment-collection.v1"
COLLECTION_METADATA_SCHEMA = "chat_read_attachment_collection_v1"
COLLECTION_SUFFIX = ".lescollection"


class AttachmentCollectionError(ValueError):
    def __init__(self, code: str, *, actual_bytes: int | None = None,
                 max_bytes: int | None = None):
        super().__init__(code)
        self.code, self.actual_bytes, self.max_bytes = code, actual_bytes, max_bytes


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AttachmentCollectionError("COLLECTION_DUPLICATE_MANIFEST_KEY")
        result[key] = value
    return result


def create_read_attachment_collection(
    attachment_ids: Sequence[str], *, max_bytes: int,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Commit a new immutable parent from opaque existing server attachment IDs."""
    if (not attachment_ids or isinstance(attachment_ids, (str, bytes))
            or any(not isinstance(value, str) for value in attachment_ids)
            or len(set(attachment_ids)) != len(attachment_ids)):
        raise AttachmentCollectionError("COLLECTION_DISTINCT_ATTACHMENT_IDS_REQUIRED")
    resolved = [resolve_read_attachment(ident, root=root) for ident in attachment_ids]
    if len({metadata["attachment_id"] for _, metadata in resolved}) != len(resolved):
        raise AttachmentCollectionError("COLLECTION_DISTINCT_ATTACHMENT_IDS_REQUIRED")
    if any(metadata.get("schema") == COLLECTION_METADATA_SCHEMA for _, metadata in resolved):
        raise AttachmentCollectionError("COLLECTION_NESTING_UNSUPPORTED")
    total = sum(path.stat().st_size for path, _ in resolved)
    if total > max_bytes:
        raise AttachmentCollectionError("UPLOAD_TOO_LARGE", actual_bytes=total, max_bytes=max_bytes)
    members = []
    for index, (path, metadata) in enumerate(resolved):
        suffix = path.suffix.lower()
        members.append({
            "member_key": metadata["attachment_id"], "attachment_id": metadata["attachment_id"],
            "original_name": metadata["original_name"], "suffix": suffix,
            "size": metadata["size"], "sha256": metadata["sha256"],
            "archive_path": f"members/{index:08d}{suffix}",
        })
    manifest = {"schema": COLLECTION_SCHEMA, "members": members}
    manifest_bytes = _json(manifest)
    ident = f"read_{uuid4().hex[:12]}"
    metadata_path, bare_path = _paths(ident, root)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path = bare_path.with_suffix(COLLECTION_SUFFIX)
    temporary = stored_path.with_suffix(COLLECTION_SUFFIX + ".tmp")
    pending = metadata_path.with_suffix(".json.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(zipfile.ZipInfo("manifest.json"), manifest_bytes)
            for (source, _), member in zip(resolved, members, strict=True):
                digest = hashlib.sha256()
                count = 0
                with source.open("rb") as reader, archive.open(zipfile.ZipInfo(member["archive_path"]), "w") as writer:
                    for block in iter(lambda: reader.read(1024 * 1024), b""):
                        count += len(block)
                        digest.update(block)
                        writer.write(block)
                if count != member["size"] or digest.hexdigest() != member["sha256"]:
                    raise AttachmentCollectionError("COLLECTION_MEMBER_CHANGED")
        temporary.replace(stored_path)
        metadata = {
            "schema": COLLECTION_METADATA_SCHEMA, "attachment_id": ident,
            "original_name": f"Комплект документов ({len(members)})",
            "stored_name": stored_path.name, "suffix": COLLECTION_SUFFIX,
            "size": stored_path.stat().st_size, "sha256": _sha256(stored_path),
            "created_at_epoch": time.time(),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "member_count": len(members), "member_bytes": total,
        }
        pending.write_bytes(_json(metadata))
        pending.replace(metadata_path)
        return metadata
    except (OSError, ValueError, zipfile.BadZipFile):
        temporary.unlink(missing_ok=True)
        stored_path.unlink(missing_ok=True)
        pending.unlink(missing_ok=True)
        raise


def load_collection_source_catalog(path: Path, *, trusted_metadata: Mapping[str, Any]):
    """Verify every member and expose a namespaced union of literal catalogs."""
    from proxy.services.attachment_source_catalog_service import (
        AttachmentSourceCatalog, _stable_id, load_tabular_source_catalog,
    )
    if (trusted_metadata.get("schema") != COLLECTION_METADATA_SCHEMA
            or trusted_metadata.get("stored_name") != path.name
            or trusted_metadata.get("size") != path.stat().st_size
            or trusted_metadata.get("sha256") != _sha256(path)):
        raise AttachmentCollectionError("COLLECTION_SERVER_METADATA_MISMATCH")
    parent_sha = str(trusted_metadata["sha256"])
    rows, sheets, origins, members, warnings = [], [], [], [], []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise AttachmentCollectionError("COLLECTION_INVALID_ENTRIES")
        if any(info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1
               or (info.external_attr >> 16) & 0o170000 == 0o120000 for info in infos):
            raise AttachmentCollectionError("COLLECTION_UNSUPPORTED_ARCHIVE_ENTRY")
        body = archive.read("manifest.json")
        if hashlib.sha256(body).hexdigest() != trusted_metadata.get("manifest_sha256"):
            raise AttachmentCollectionError("COLLECTION_MANIFEST_HASH_MISMATCH")
        manifest = json.loads(body, object_pairs_hook=_unique_object)
        if (not isinstance(manifest, dict) or manifest.get("schema") != COLLECTION_SCHEMA
                or set(manifest) != {"schema", "members"}
                or not isinstance(manifest["members"], list) or not manifest["members"]
                or len(manifest["members"]) != trusted_metadata.get("member_count")):
            raise AttachmentCollectionError("COLLECTION_INVALID_MANIFEST")
        expected = ["manifest.json"]
        keys = set()
        for index, member in enumerate(manifest["members"]):
            if (not isinstance(member, dict)
                    or set(member) != {"member_key", "attachment_id", "original_name", "suffix", "size", "sha256", "archive_path"}
                    or not isinstance(member["member_key"], str)
                    or member["member_key"] != member["attachment_id"]
                    or member["member_key"] in keys
                    or not isinstance(member["original_name"], str)
                    or Path(member["original_name"]).name != member["original_name"]
                    or member["suffix"] != Path(member["original_name"]).suffix.lower()
                    or member["suffix"] == COLLECTION_SUFFIX
                    or member["archive_path"] != f"members/{index:08d}{member['suffix']}"
                    or type(member["size"]) is not int or member["size"] < 0
                    or not isinstance(member["sha256"], str) or len(member["sha256"]) != 64):
                raise AttachmentCollectionError("COLLECTION_INVALID_MEMBER")
            # Match opaque server IDs, not arbitrary locator/path prefixes.
            from proxy.services.chat_attachment_service import _safe_id
            if _safe_id(member["member_key"]) != member["member_key"]:
                raise AttachmentCollectionError("COLLECTION_INVALID_MEMBER")
            keys.add(member["member_key"])
            expected.append(member["archive_path"])
        if set(names) != set(expected):
            raise AttachmentCollectionError("COLLECTION_UNEXPECTED_ENTRIES")
        if sum(member["size"] for member in manifest["members"]) != trusted_metadata.get("member_bytes"):
            raise AttachmentCollectionError("COLLECTION_MEMBER_SIZE_MISMATCH")
        with tempfile.TemporaryDirectory(prefix="collection-read-", dir=path.parent) as folder:
            for member in manifest["members"]:
                if archive.getinfo(member["archive_path"]).file_size != member["size"]:
                    raise AttachmentCollectionError("COLLECTION_MEMBER_SIZE_MISMATCH")
                raw = archive.read(member["archive_path"])
                if len(raw) != member["size"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
                    raise AttachmentCollectionError("COLLECTION_MEMBER_HASH_MISMATCH")
                local = Path(folder) / Path(member["archive_path"]).name
                local.write_bytes(raw)
                try:
                    catalog = load_tabular_source_catalog(local, original_name=member["original_name"])
                except (OSError, ValueError, UnicodeError, zipfile.BadZipFile):
                    catalog = None
                summary = {key: value for key, value in member.items() if key != "archive_path"}
                summary.update(status="read" if catalog is not None and catalog.rows else "unread",
                               source_extraction_complete=bool(catalog is not None and catalog.rows and catalog.extraction_complete))
                members.append(summary)
                if catalog is None or not catalog.rows:
                    warnings.append(f"collection_member_unread:{member['member_key']}:{member['original_name']}")
                    continue
                warnings.extend(f"collection_member:{member['member_key']}:{warning}" for warning in catalog.extraction_warnings)
                if not catalog.extraction_complete and not catalog.extraction_warnings:
                    warnings.append(f"collection_member_incomplete:{member['member_key']}")
                prefix = member["member_key"] + "::"
                sheets.extend((prefix + name, count) for name, count in catalog.sheets)
                for row in catalog.rows:
                    locator = prefix + row.locator
                    rows.append(replace(row, locator=locator, sheet=prefix + row.sheet,
                        row_id=prefix + row.row_id, sheet_id=prefix + row.sheet_id,
                        line=(locator + row.line[len(row.locator):]) if row.line.startswith(row.locator) else f"{locator} | {row.line}"))
                    origins.append({"source_row": locator, "member_key": member["member_key"],
                        "attachment_id": member["attachment_id"], "original_name": member["original_name"],
                        "source_file_sha256": member["sha256"], "source_file_id": catalog.source_file_id,
                        "original_locator": row.locator, "original_sheet": row.sheet,
                        "original_row_id": row.row_id, "original_sheet_id": row.sheet_id,
                        "source_start": row.source_start, "source_end": row.source_end,
                        "source_order_basis": row.source_order_basis})
    return AttachmentSourceCatalog(original_name=str(trusted_metadata["original_name"]),
        sheets=tuple(sheets), rows=tuple(rows), source_file_sha256=parent_sha,
        source_file_id=_stable_id(parent_sha, prefix="src"), extraction_complete=not warnings,
        extraction_warnings=tuple(warnings), source_members=tuple(members), source_row_origins=tuple(origins))
