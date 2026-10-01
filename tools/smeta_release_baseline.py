"""Build, verify and provision the immutable smeta baseline for boxed releases.

Runtime data stays outside git, but a clean production install must still have a
trusted normative base.  The release orchestrator creates this archive from an
already verified operator root; Windows bundles it and first-run provisioning
copies it into persistent state only when the target is completely empty.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "dist" / "LES-smeta-baseline.zip"
ARCHIVE_MANIFEST = "baseline-manifest.json"
PAYLOAD_PREFIX = PurePosixPath("payload")
REQUIRED_FILES = (
    PurePosixPath("data/gesn_base/gesn2022_unified.parquet"),
    PurePosixPath("data/smeta_base/les_smeta_base.sqlite"),
    PurePosixPath("data/smeta_base/les_smeta_base_manifest.json"),
    PurePosixPath("data/smeta_base/les_smeta_base_integrity.json"),
    PurePosixPath("data/smeta_base/fsem_2022.sqlite"),
    PurePosixPath("data/smeta_base/fsem_2022_manifest.json"),
    PurePosixPath("data/price_base/sankt-peterburg_2kv2026.parquet"),
)
REQUIRED_ZERO_CHECKS = (
    "cross_family_contamination",
    "orphan_resources",
    "duplicate_norm_keys",
    "resource_parent_mismatch",
    "empty_machine_base",
    "missing_provenance",
    "fts_coverage",
)
DEFAULT_MINIMUM_NORMS = 40_000
DEFAULT_MINIMUM_FSEM_ROWS = 1_500
DEFAULT_MINIMUM_PRICE_ROWS = 200_000
REQUIRED_PRICE_COLUMNS = {
    "code",
    "name",
    "unit",
    "price_current_eff",
    "region",
    "quarter",
}
BASELINE_V1 = "les.smeta.release-baseline.v1"
BASELINE_V2 = "les.smeta.release-baseline.v2"


class BaselineError(RuntimeError):
    """The release baseline is missing, inconsistent or unsafe to provision."""




def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - surface the exact broken artifact
        raise BaselineError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BaselineError(f"JSON object expected: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_count(path: Path, table: str) -> int:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    except (sqlite3.Error, OSError) as exc:
        raise BaselineError(f"cannot read {table} from {path}: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


def _parquet_shape(path: Path) -> tuple[int, set[str]]:
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        return int(parquet.metadata.num_rows), set(parquet.schema_arrow.names)
    except Exception as exc:  # noqa: BLE001 - reject any unreadable release payload
        raise BaselineError(f"cannot read pricebook parquet {path}: {exc}") from exc


def _failures(value: Any) -> int:
    raw = value.get("failures") if isinstance(value, dict) else value
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise BaselineError(f"invalid integrity failure count: {value!r}") from exc


def _extra_pricebook_paths(values: Sequence[str | Path | PurePosixPath]) -> tuple[PurePosixPath, ...]:
    result: list[PurePosixPath] = []
    seen = {path.as_posix().casefold() for path in REQUIRED_FILES}
    for value in values:
        literal = str(value).replace("\\", "/")
        relative = PurePosixPath(literal)
        if (
            relative.as_posix() != literal or len(relative.parts) != 3
            or relative.parts[:2] != ("data", "price_base")
            or relative.suffix != ".parquet" or any(character in literal for character in '<>:"|?*\0')
            or ".." in relative.parts or relative.as_posix().casefold() in seen
        ):
            raise BaselineError(f"invalid extra pricebook path: {value}")
        result.append(relative)
        seen.add(relative.as_posix().casefold())
    return tuple(result)


def _validate_extra_pricebook(root: Path, relative: PurePosixPath) -> dict[str, Any]:
    from proxy.services.fgis_price_service import PRICE_FIELDS, get_pricebook, normalize_code

    root = root.resolve()
    path = root / Path(*relative.parts)
    if not path.resolve().is_relative_to(root):
        raise BaselineError(f"extra pricebook escapes source root: {relative}")
    try:
        book = get_pricebook(str(path))
    except (OSError, ValueError, TypeError) as exc:
        raise BaselineError(f"cannot read extra pricebook: {relative}") from exc
    rows = len(book._rows)
    columns = set(book._rows[0]) if rows else set()
    if not {"code", "name", "unit", "region", "quarter"}.issubset(columns) or not rows:
        raise BaselineError(f"extra pricebook misses typed identity: {relative}")
    if columns - {*PRICE_FIELDS, "region", "quarter"}:
        raise BaselineError(f"extra pricebook has unsupported columns: {relative}")
    price_fields = {"price_release", "price_current_eff", "price_current", "price_base", "index"} & columns
    if not price_fields:
        raise BaselineError(f"extra pricebook misses price columns: {relative}")
    regions: set[str] = set()
    quarters: set[str] = set()
    codes: set[str] = set()
    priced_rows = 0
    missing_unit_rows = 0
    duplicate_code_rows = 0
    for row in book._rows:
        if not all(isinstance(row.get(key), str) and row[key].strip() for key in ("code", "region", "quarter")):
            raise BaselineError(f"extra pricebook has blank code/metadata: {relative}")
        if row.get("unit") is not None and not isinstance(row["unit"], str):
            raise BaselineError(f"extra pricebook has invalid unit type: {relative}")
        missing_unit_rows += int(not str(row.get("unit") or "").strip())
        code = normalize_code(row["code"])
        duplicate_code_rows += int(code in codes)
        codes.add(code)
        regions.add(row["region"].strip())
        quarters.add(row["quarter"].strip())
        for field in price_fields:
            value = row.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise BaselineError(f"extra pricebook has invalid numeric price: {relative}")
        if any(row.get(field) is not None for field in ("price_release", "price_current_eff", "price_current", "price_base")):
            priced_rows += 1
    if len(regions) != 1 or len(quarters) != 1:
        raise BaselineError(f"extra pricebook has mixed region/period: {relative}")
    return {
        "path": relative.as_posix(), "sha256": book.source_sha256, "bytes": book.source_byte_size,
        "rows": rows, "region": next(iter(regions)), "quarter": next(iter(quarters)),
        "rows_with_price_values": priced_rows, "missing_price_rows": rows - priced_rows,
        "missing_unit_rows": missing_unit_rows, "duplicate_code_rows": duplicate_code_rows,
    }


def _public_manifest_payload(relative: PurePosixPath, payload: dict[str, Any]) -> dict[str, Any]:
    """Known producer schemas expose hashes/counts and relative payload identities."""
    def fields(value: Any, keys: Sequence[str]) -> dict[str, Any]:
        return {key: value[key] for key in keys if isinstance(value, dict) and key in value}

    def checks(value: Any, keys: Sequence[str]) -> dict[str, Any]:
        return {key: fields(value[key], ("failures", "actual", "minimum", "rows"))
                if isinstance(value[key], dict) else value[key]
                for key in keys if isinstance(value, dict) and key in value}

    schema = payload.get("schema")
    if schema == "les_smeta_base_v2":
        result = fields(payload, ("schema", "minimum_norms", "created_at"))
        result["excluded"] = fields(payload.get("excluded"), (
            "rows_missing_norm_key", "resource_rows_missing_kind_or_name", "resource_identity_duplicates_dropped",
            "norms_missing_name_or_unit", "norms_without_resources", "untrusted_identity_rows_quarantined",
            "family_mismatch_rows_quarantined", "metadata_conflict_norms",
        ))
        result["examples"] = fields(payload.get("examples"), (
            "missing_metadata_norm_keys", "norms_without_resources", "metadata_conflict_norm_keys",
        ))
        result["source"] = fields(payload.get("source"), ("sha256", "rows", "norm_keys"))
        result["source"]["path"] = REQUIRED_FILES[0].as_posix()
        result["output"] = fields(payload.get("output"), ("sha256", "edition", "norms", "resources"))
        result["output"]["path"] = REQUIRED_FILES[1].as_posix()
        if isinstance(payload.get("integrity"), dict):
            result["integrity"] = fields(payload["integrity"], ("schema", "verdict"))
            result["integrity"]["path"] = REQUIRED_FILES[3].as_posix()
        return result
    if schema == "les_smeta_base_integrity_v1":
        result = fields(payload, ("schema", "created_at", "verdict", "edition", "source_sha256", "base_sha256"))
        result["checks"] = checks(payload.get("checks"), (*REQUIRED_ZERO_CHECKS, "minimum_norms"))
        result["quarantine"] = fields(payload.get("quarantine"), (
            "untrusted_identity_rows", "family_mismatch_rows", "metadata_conflict_norms",
        ))
        return result
    if schema == "fsem_2022_catalog_manifest_v1":
        result = fields(payload, ("schema", "created_at", "verdict"))
        result["checks"] = checks(payload.get("checks"), ("minimum_rows", "invalid_driver_rows", "duplicate_machine_keys"))
        result["coverage"] = fields(payload.get("coverage"), ("driver_rows", "no_driver_rows"))
        result["quarantine"] = fields(payload.get("quarantine"), ("numeric_conflict_codes", "numeric_conflict_count", "same_numeric_duplicates"))
        result["source"] = fields(payload.get("source"), ("sha256", "pages"))
        result["output"] = fields(payload.get("output"), ("sha256", "rows"))
        result["output"]["path"] = REQUIRED_FILES[4].as_posix()
        return result
    raise BaselineError(f"unsupported public manifest projection: {relative}")


def _archive_paths(manifest: dict[str, Any]) -> tuple[PurePosixPath, ...]:
    schema = manifest.get("schema")
    if schema not in {BASELINE_V1, BASELINE_V2}:
        raise BaselineError("unsupported smeta baseline archive schema")
    declared_books = manifest.get("pricebooks", [])
    if not isinstance(declared_books, list) or any(not isinstance(item, dict) for item in declared_books):
        raise BaselineError("invalid extra pricebook manifest")
    if schema == BASELINE_V1 and declared_books:
        raise BaselineError("legacy baseline cannot declare extra pricebooks")
    extras = _extra_pricebook_paths([item.get("path", "") for item in declared_books])
    paths = (*REQUIRED_FILES, *extras)
    records = manifest.get("files")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise BaselineError("invalid smeta baseline file manifest")
    if any(not isinstance(item.get("path"), str) for item in records):
        raise BaselineError("invalid smeta baseline file path")
    if len(records) != len(paths) or {item.get("path") for item in records} != {path.as_posix() for path in paths}:
        raise BaselineError("smeta baseline archive file set is incomplete")
    for book in declared_books:
        entry = next(item for item in records if item["path"] == book["path"])
        if book.get("sha256") != entry.get("sha256") or book.get("bytes") != entry.get("bytes"):
            raise BaselineError("extra pricebook manifest fingerprint differs from file")
    return paths


def _extract_archive(archive: Path, staging: Path, paths: Sequence[PurePosixPath]) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for relative in paths:
            target = staging / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open((PAYLOAD_PREFIX / relative).as_posix()) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)


def _extra_install_plan(state_root: Path, manifest: dict[str, Any]) -> tuple[tuple[PurePosixPath, ...], list[str]]:
    missing: list[PurePosixPath] = []
    kept: list[str] = []
    for declared in manifest.get("pricebooks", []):
        relative = PurePosixPath(declared["path"])
        target = state_root / Path(*relative.parts)
        if not target.resolve().is_relative_to(state_root.resolve()):
            raise BaselineError(f"extra pricebook escapes state root: {relative}")
        if target.exists():
            _validate_extra_pricebook(state_root, relative)
            kept.append(relative.as_posix())
        else:
            missing.append(relative)
    return tuple(missing), kept


def _provision_extra_pricebooks(archive: Path, state_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    missing, kept = _extra_install_plan(state_root, manifest)
    installed: list[PurePosixPath] = []
    if missing:
        with tempfile.TemporaryDirectory(prefix="les-pricebook-baseline-", dir=state_root) as temporary:
            staging = Path(temporary)
            _extract_archive(archive, staging, missing)
            try:
                for relative in missing:
                    source = staging / Path(*relative.parts)
                    target = state_root / Path(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source, target)
                    installed.append(relative)
            except OSError:
                for relative in reversed(installed):
                    (state_root / Path(*relative.parts)).unlink(missing_ok=True)
                raise
    return {"installed_pricebooks": [item.as_posix() for item in installed], "kept_pricebooks": kept}


def validate_root(
    root: Path,
    *,
    minimum_norms: int = DEFAULT_MINIMUM_NORMS,
    minimum_fsem_rows: int = DEFAULT_MINIMUM_FSEM_ROWS,
    minimum_price_rows: int = DEFAULT_MINIMUM_PRICE_ROWS,
) -> dict[str, Any]:
    root = root.resolve()
    paths = {str(rel): root / Path(*rel.parts) for rel in REQUIRED_FILES}
    missing = [rel for rel, path in paths.items() if not path.is_file()]
    if missing:
        raise BaselineError("smeta baseline misses: " + ", ".join(missing))

    source = paths["data/gesn_base/gesn2022_unified.parquet"]
    base = paths["data/smeta_base/les_smeta_base.sqlite"]
    manifest = _json(paths["data/smeta_base/les_smeta_base_manifest.json"])
    integrity_path = paths["data/smeta_base/les_smeta_base_integrity.json"]
    integrity = _json(integrity_path)
    fsem = paths["data/smeta_base/fsem_2022.sqlite"]
    fsem_manifest = _json(paths["data/smeta_base/fsem_2022_manifest.json"])
    pricebook = paths["data/price_base/sankt-peterburg_2kv2026.parquet"]

    if manifest.get("schema") != "les_smeta_base_v2":
        raise BaselineError("unsupported structured-base manifest schema")
    if integrity.get("schema") != "les_smeta_base_integrity_v1":
        raise BaselineError("unsupported structured-base integrity schema")
    checks = integrity.get("checks") if isinstance(integrity.get("checks"), dict) else {}
    failed = [name for name in REQUIRED_ZERO_CHECKS if _failures(checks.get(name)) != 0]
    if integrity.get("verdict") != "passed" or failed:
        raise BaselineError("structured-base integrity checks failed: " + ", ".join(failed))

    source_sha = _sha256(source)
    base_sha = _sha256(base)
    if source_sha != str((manifest.get("source") or {}).get("sha256") or ""):
        raise BaselineError("unified parquet does not match structured-base manifest")
    if source_sha != str(integrity.get("source_sha256") or ""):
        raise BaselineError("unified parquet does not match integrity report")
    if base_sha != str(integrity.get("base_sha256") or ""):
        raise BaselineError("structured SQLite does not match integrity report")

    norm_count = _sqlite_count(base, "norms")
    resource_count = _sqlite_count(base, "resources")
    manifest_norms = int((manifest.get("output") or {}).get("norms") or 0)
    manifest_resources = int((manifest.get("output") or {}).get("resources") or 0)
    if norm_count != manifest_norms or resource_count != manifest_resources:
        raise BaselineError("structured SQLite counts do not match manifest")
    if norm_count < minimum_norms:
        raise BaselineError(f"structured base is incomplete: {norm_count} < {minimum_norms} norms")

    if fsem_manifest.get("schema") != "fsem_2022_catalog_manifest_v1":
        raise BaselineError("unsupported FSEM manifest schema")
    if fsem_manifest.get("verdict") != "passed":
        raise BaselineError("FSEM manifest is not passed")
    fsem_count = _sqlite_count(fsem, "machines")
    fsem_output = fsem_manifest.get("output") or {}
    if fsem_count != int(fsem_output.get("rows") or 0):
        raise BaselineError("FSEM SQLite count does not match manifest")
    if fsem_count < minimum_fsem_rows:
        raise BaselineError(f"FSEM catalog is incomplete: {fsem_count} < {minimum_fsem_rows} rows")
    if _sha256(fsem) != str(fsem_output.get("sha256") or ""):
        raise BaselineError("FSEM SQLite does not match manifest")

    price_rows, price_columns = _parquet_shape(pricebook)
    missing_price_columns = sorted(REQUIRED_PRICE_COLUMNS - price_columns)
    if missing_price_columns:
        raise BaselineError("pricebook misses columns: " + ", ".join(missing_price_columns))
    if price_rows < minimum_price_rows:
        raise BaselineError(
            f"default pricebook is incomplete: {price_rows} < {minimum_price_rows} rows"
        )

    return {
        "schema": "les.smeta.release-baseline.validation.v1",
        "ok": True,
        "root": str(root),
        "norm_count": norm_count,
        "resource_count": resource_count,
        "minimum_norms": minimum_norms,
        "fsem_rows": fsem_count,
        "minimum_fsem_rows": minimum_fsem_rows,
        "pricebook_rows": price_rows,
        "minimum_pricebook_rows": minimum_price_rows,
        "pricebook_sha256": _sha256(pricebook),
        "base_sha256": base_sha,
        "source_sha256": source_sha,
    }


def create_archive(
    source_root: Path,
    archive: Path = DEFAULT_ARCHIVE,
    *,
    minimum_norms: int = DEFAULT_MINIMUM_NORMS,
    minimum_fsem_rows: int = DEFAULT_MINIMUM_FSEM_ROWS,
    minimum_price_rows: int = DEFAULT_MINIMUM_PRICE_ROWS,
    extra_pricebooks: Sequence[str | Path | PurePosixPath] = (),
) -> dict[str, Any]:
    validation = validate_root(
        source_root,
        minimum_norms=minimum_norms,
        minimum_fsem_rows=minimum_fsem_rows,
        minimum_price_rows=minimum_price_rows,
    )
    source_root = source_root.resolve()
    extra_paths = _extra_pricebook_paths(extra_pricebooks)
    pricebooks = [_validate_extra_pricebook(source_root, relative) for relative in extra_paths]
    archive.parent.mkdir(parents=True, exist_ok=True)
    temp = archive.with_suffix(archive.suffix + ".tmp")
    temp.unlink(missing_ok=True)
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for relative in (*REQUIRED_FILES, *extra_paths):
            source = source_root / Path(*relative.parts)
            arcname = (PAYLOAD_PREFIX / relative).as_posix()
            if relative.name in {"les_smeta_base_integrity.json", "les_smeta_base_manifest.json", "fsem_2022_manifest.json"}:
                payload = _public_manifest_payload(relative, _json(source))
                if relative.name == "les_smeta_base_integrity.json":
                    checks = dict(payload.get("checks") or {})
                    checks["minimum_norms"] = {
                        "failures": 0,
                        "actual": validation["norm_count"],
                        "minimum": minimum_norms,
                    }
                    payload["checks"] = checks
                elif relative.name == "les_smeta_base_manifest.json":
                    payload["minimum_norms"] = minimum_norms
                raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                bundle.writestr(arcname, raw)
                digest = hashlib.sha256(raw).hexdigest()
                size = len(raw)
            else:
                hasher = hashlib.sha256()
                size = 0
                with source.open("rb") as input_stream, bundle.open(arcname, "w") as output_stream:
                    for block in iter(lambda: input_stream.read(8 * 1024 * 1024), b""):
                        output_stream.write(block)
                        hasher.update(block)
                        size += len(block)
                digest = hasher.hexdigest()
                if relative in extra_paths:
                    snapshot = next(item for item in pricebooks if item["path"] == relative.as_posix())
                    if digest != snapshot["sha256"] or size != snapshot["bytes"]:
                        raise BaselineError(f"extra pricebook changed during packaging: {relative}")
            entries.append({"path": relative.as_posix(), "sha256": digest, "bytes": size})
        manifest = {
            "schema": BASELINE_V2 if extra_paths else BASELINE_V1,
            "norm_count": validation["norm_count"],
            "resource_count": validation["resource_count"],
            "minimum_norms": minimum_norms,
            "fsem_rows": validation["fsem_rows"],
            "minimum_fsem_rows": minimum_fsem_rows,
            "pricebook_rows": validation["pricebook_rows"],
            "minimum_pricebook_rows": minimum_price_rows,
            "files": entries,
        }
        if extra_paths:
            manifest["pricebooks"] = pricebooks
        bundle.writestr(ARCHIVE_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, archive)
    return {**validation, "archive": str(archive), "archive_sha256": _sha256(archive),
            **({"pricebooks": pricebooks} if extra_paths else {})}


def verify_archive(archive: Path) -> dict[str, Any]:
    if not archive.is_file():
        raise BaselineError(f"smeta baseline archive is missing: {archive}")
    try:
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read(ARCHIVE_MANIFEST).decode("utf-8"))
            if not isinstance(manifest, dict):
                raise BaselineError("invalid smeta baseline archive manifest")
            paths = _archive_paths(manifest)
            expected = {item["path"]: item for item in manifest.get("files") or []}
            members = [item.filename for item in bundle.infolist()]
            allowed = {ARCHIVE_MANIFEST, *((PAYLOAD_PREFIX / path).as_posix() for path in paths)}
            if len(members) != len(allowed) or set(members) != allowed:
                raise BaselineError("smeta baseline archive has undeclared/duplicate members")
            for relative, item in expected.items():
                member = (PAYLOAD_PREFIX / PurePosixPath(relative)).as_posix()
                digest = hashlib.sha256()
                size = 0
                with bundle.open(member) as stream:
                    for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
                if digest.hexdigest() != item.get("sha256") or size != int(item.get("bytes") or -1):
                    raise BaselineError(f"smeta baseline archive entry is corrupt: {relative}")
    except (zipfile.BadZipFile, zlib.error, KeyError, json.JSONDecodeError) as exc:
        raise BaselineError(f"invalid smeta baseline archive: {exc}") from exc
    minimum_norms = int(manifest.get("minimum_norms") or 0)
    minimum_fsem_rows = int(manifest.get("minimum_fsem_rows") or 0)
    minimum_price_rows = int(manifest.get("minimum_pricebook_rows") or 0)
    if int(manifest.get("norm_count") or 0) < minimum_norms:
        raise BaselineError("smeta baseline archive norm floor is not satisfied")
    if int(manifest.get("fsem_rows") or 0) < minimum_fsem_rows:
        raise BaselineError("smeta baseline archive FSEM floor is not satisfied")
    if int(manifest.get("pricebook_rows") or 0) < minimum_price_rows:
        raise BaselineError("smeta baseline archive pricebook floor is not satisfied")
    with tempfile.TemporaryDirectory(prefix="les-smeta-baseline-verify-") as temporary:
        staging = Path(temporary)
        _extract_archive(archive, staging, paths)
        validation = validate_root(
            staging,
            minimum_norms=minimum_norms,
            minimum_fsem_rows=minimum_fsem_rows,
            minimum_price_rows=minimum_price_rows,
        )
        for declared in manifest.get("pricebooks", []):
            actual = _validate_extra_pricebook(staging, PurePosixPath(declared["path"]))
            if actual != declared:
                raise BaselineError(f"extra pricebook metadata does not match payload: {declared['path']}")
    expected_counts = {
        "norm_count": validation["norm_count"],
        "resource_count": validation["resource_count"],
        "fsem_rows": validation["fsem_rows"],
        "pricebook_rows": validation["pricebook_rows"],
    }
    mismatched = [
        name for name, actual in expected_counts.items() if int(manifest.get(name) or -1) != actual
    ]
    if mismatched:
        raise BaselineError("smeta baseline archive counts do not match payload: " + ", ".join(mismatched))
    return {"ok": True, "archive": str(archive), **manifest}


def provision_archive(archive: Path, state_root: Path) -> dict[str, Any]:
    archive_status = verify_archive(archive)
    state_root = state_root.resolve()
    targets = [state_root / Path(*relative.parts) for relative in REQUIRED_FILES]
    present = [path.is_file() for path in targets]
    if any(present):
        if not all(present):
            raise BaselineError("persistent smeta baseline is partial; refusing to overwrite user state")
        validation = validate_root(
            state_root,
            minimum_norms=int(archive_status["minimum_norms"]),
            minimum_fsem_rows=int(archive_status["minimum_fsem_rows"]),
            minimum_price_rows=int(archive_status["minimum_pricebook_rows"]),
        )
        return {**validation, "action": "kept_existing",
                **_provision_extra_pricebooks(archive, state_root, archive_status)}

    state_root.mkdir(parents=True, exist_ok=True)
    missing_extras, kept_extras = _extra_install_plan(state_root, archive_status)
    install_paths = (*REQUIRED_FILES, *missing_extras)
    with tempfile.TemporaryDirectory(prefix="les-smeta-baseline-", dir=state_root) as temporary:
        staging = Path(temporary)
        _extract_archive(archive, staging, install_paths)
        validation = validate_root(
            staging,
            minimum_norms=int(archive_status["minimum_norms"]),
            minimum_fsem_rows=int(archive_status["minimum_fsem_rows"]),
            minimum_price_rows=int(archive_status["minimum_pricebook_rows"]),
        )
        installed: list[PurePosixPath] = []
        try:
            for relative in install_paths:
                source = staging / Path(*relative.parts)
                target = state_root / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                installed.append(relative)
        except OSError:
            for relative in reversed(installed):
                (state_root / Path(*relative.parts)).unlink(missing_ok=True)
            raise
    return {**validation, "action": "installed", "installed_pricebooks": [item.as_posix() for item in missing_extras],
            "kept_pricebooks": kept_extras}


def repair_archive(archive: Path, state_root: Path) -> dict[str, Any]:
    """Restore a broken/partial baseline from the verified release payload.

    A valid newer operator base is kept. A broken state is copied to a dated
    recovery directory before the verified baseline replaces the complete
    linked file set, so norms/manifests/FSEM can never be mixed across revisions.
    """
    archive_status = verify_archive(archive)
    kept_core: dict[str, Any] | None = None
    try:
        current = validate_root(
            state_root,
            minimum_norms=int(archive_status["minimum_norms"]),
            minimum_fsem_rows=int(archive_status["minimum_fsem_rows"]),
            minimum_price_rows=int(archive_status["minimum_pricebook_rows"]),
        )
        behind = [
            f"{label}={int(current.get(current_key) or 0)}"
            f"<{int(archive_status.get(archive_key) or 0)}"
            for label, current_key, archive_key in (
                ("norms", "norm_count", "norm_count"),
                ("resources", "resource_count", "resource_count"),
                ("FSEM", "fsem_rows", "fsem_rows"),
                ("pricebook", "pricebook_rows", "pricebook_rows"),
            )
            if int(current.get(current_key) or 0) < int(archive_status.get(archive_key) or 0)
        ]
        if not behind:
            kept_core = current
        else:
            reason = "persistent smeta baseline is older than release payload: " + ", ".join(behind)
    except (BaselineError, OSError) as current_error:
        reason = str(current_error)

    if kept_core is not None:
        return {**kept_core, "action": "kept_valid",
                **_provision_extra_pricebooks(archive, state_root, archive_status)}

    state_root.mkdir(parents=True, exist_ok=True)
    missing_extras, kept_extras = _extra_install_plan(state_root, archive_status)
    install_paths = (*REQUIRED_FILES, *missing_extras)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = state_root / "storage" / "recovery" / f"smeta_baseline_{stamp}"
    backed_up: list[str] = []
    with tempfile.TemporaryDirectory(prefix="les-smeta-repair-", dir=state_root) as temporary:
        staging = Path(temporary)
        _extract_archive(archive, staging, install_paths)
        validation = validate_root(
            staging,
            minimum_norms=int(archive_status["minimum_norms"]),
            minimum_fsem_rows=int(archive_status["minimum_fsem_rows"]),
            minimum_price_rows=int(archive_status["minimum_pricebook_rows"]),
        )
        installed: list[PurePosixPath] = []
        try:
            # Same-volume moves preserve the previous files without requiring
            # read access to a malformed Windows ACL. The replacement is fully
            # extracted and validated before this transaction starts.
            for relative in REQUIRED_FILES:
                source = state_root / Path(*relative.parts)
                if not source.is_file():
                    continue
                target = backup_root / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                backed_up.append(relative.as_posix())
            for relative in install_paths:
                source = staging / Path(*relative.parts)
                target = state_root / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                installed.append(relative)
        except OSError:
            for relative in reversed(installed):
                (state_root / Path(*relative.parts)).unlink(missing_ok=True)
            for value in reversed(backed_up):
                relative = PurePosixPath(value)
                saved = backup_root / Path(*relative.parts)
                target = state_root / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if saved.is_file():
                    os.replace(saved, target)
            raise
    return {
        **validation,
        "action": "repaired",
        "reason": reason,
        "backup": str(backup_root) if backed_up else "",
        "backed_up": backed_up,
        "installed_pricebooks": [item.as_posix() for item in missing_extras],
        "kept_pricebooks": kept_extras,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source-root", type=Path, default=ROOT)
    create.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    create.add_argument("--minimum-norms", type=int, default=DEFAULT_MINIMUM_NORMS)
    create.add_argument("--minimum-price-rows", type=int, default=DEFAULT_MINIMUM_PRICE_ROWS)
    create.add_argument("--pricebook", action="append", default=[],
                        help="explicit additional data/price_base/*.parquet; repeat for each book")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    verify_root = subparsers.add_parser("verify-root")
    verify_root.add_argument("--root", type=Path, required=True)
    verify_root.add_argument("--minimum-norms", type=int, default=DEFAULT_MINIMUM_NORMS)
    verify_root.add_argument("--minimum-price-rows", type=int, default=DEFAULT_MINIMUM_PRICE_ROWS)
    provision = subparsers.add_parser("provision")
    provision.add_argument("--archive", type=Path, required=True)
    provision.add_argument("--state-root", type=Path, required=True)
    repair = subparsers.add_parser("repair")
    repair.add_argument("--archive", type=Path, required=True)
    repair.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        result = create_archive(
            args.source_root,
            args.archive,
            minimum_norms=args.minimum_norms,
            minimum_price_rows=args.minimum_price_rows,
            extra_pricebooks=args.pricebook,
        )
    elif args.command == "verify":
        result = verify_archive(args.archive)
    elif args.command == "verify-root":
        result = validate_root(
            args.root,
            minimum_norms=args.minimum_norms,
            minimum_price_rows=args.minimum_price_rows,
        )
    elif args.command == "provision":
        result = provision_archive(args.archive, args.state_root)
    else:
        result = repair_archive(args.archive, args.state_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BaselineError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
