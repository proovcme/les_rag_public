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
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


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
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    except (sqlite3.Error, OSError) as exc:
        raise BaselineError(f"cannot read {table} from {path}: {exc}") from exc


def _failures(value: Any) -> int:
    raw = value.get("failures") if isinstance(value, dict) else value
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise BaselineError(f"invalid integrity failure count: {value!r}") from exc


def validate_root(
    root: Path,
    *,
    minimum_norms: int = DEFAULT_MINIMUM_NORMS,
    minimum_fsem_rows: int = DEFAULT_MINIMUM_FSEM_ROWS,
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

    return {
        "schema": "les.smeta.release-baseline.validation.v1",
        "ok": True,
        "root": str(root),
        "norm_count": norm_count,
        "resource_count": resource_count,
        "minimum_norms": minimum_norms,
        "fsem_rows": fsem_count,
        "minimum_fsem_rows": minimum_fsem_rows,
        "base_sha256": base_sha,
        "source_sha256": source_sha,
    }


def create_archive(
    source_root: Path,
    archive: Path = DEFAULT_ARCHIVE,
    *,
    minimum_norms: int = DEFAULT_MINIMUM_NORMS,
    minimum_fsem_rows: int = DEFAULT_MINIMUM_FSEM_ROWS,
) -> dict[str, Any]:
    validation = validate_root(
        source_root,
        minimum_norms=minimum_norms,
        minimum_fsem_rows=minimum_fsem_rows,
    )
    source_root = source_root.resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    temp = archive.with_suffix(archive.suffix + ".tmp")
    temp.unlink(missing_ok=True)
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for relative in REQUIRED_FILES:
            source = source_root / Path(*relative.parts)
            arcname = (PAYLOAD_PREFIX / relative).as_posix()
            if relative.name in {"les_smeta_base_integrity.json", "les_smeta_base_manifest.json"}:
                payload = _json(source)
                if relative.name == "les_smeta_base_integrity.json":
                    checks = dict(payload.get("checks") or {})
                    checks["minimum_norms"] = {
                        "failures": 0,
                        "actual": validation["norm_count"],
                        "minimum": minimum_norms,
                    }
                    payload["checks"] = checks
                else:
                    payload["minimum_norms"] = minimum_norms
                raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                bundle.writestr(arcname, raw)
                digest = hashlib.sha256(raw).hexdigest()
                size = len(raw)
            else:
                bundle.write(source, arcname)
                digest = _sha256(source)
                size = source.stat().st_size
            entries.append({"path": relative.as_posix(), "sha256": digest, "bytes": size})
        manifest = {
            "schema": "les.smeta.release-baseline.v1",
            "norm_count": validation["norm_count"],
            "resource_count": validation["resource_count"],
            "minimum_norms": minimum_norms,
            "fsem_rows": validation["fsem_rows"],
            "minimum_fsem_rows": minimum_fsem_rows,
            "files": entries,
        }
        bundle.writestr(ARCHIVE_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, archive)
    return {**validation, "archive": str(archive), "archive_sha256": _sha256(archive)}


def verify_archive(archive: Path) -> dict[str, Any]:
    if not archive.is_file():
        raise BaselineError(f"smeta baseline archive is missing: {archive}")
    try:
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read(ARCHIVE_MANIFEST).decode("utf-8"))
            if manifest.get("schema") != "les.smeta.release-baseline.v1":
                raise BaselineError("unsupported smeta baseline archive schema")
            expected = {item["path"]: item for item in manifest.get("files") or []}
            required = {item.as_posix() for item in REQUIRED_FILES}
            if set(expected) != required:
                raise BaselineError("smeta baseline archive file set is incomplete")
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
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise BaselineError(f"invalid smeta baseline archive: {exc}") from exc
    minimum_norms = int(manifest.get("minimum_norms") or 0)
    minimum_fsem_rows = int(manifest.get("minimum_fsem_rows") or 0)
    if int(manifest.get("norm_count") or 0) < minimum_norms:
        raise BaselineError("smeta baseline archive norm floor is not satisfied")
    if int(manifest.get("fsem_rows") or 0) < minimum_fsem_rows:
        raise BaselineError("smeta baseline archive FSEM floor is not satisfied")
    with tempfile.TemporaryDirectory(prefix="les-smeta-baseline-verify-") as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            for relative in REQUIRED_FILES:
                member = (PAYLOAD_PREFIX / relative).as_posix()
                target = staging / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
        validation = validate_root(
            staging,
            minimum_norms=minimum_norms,
            minimum_fsem_rows=minimum_fsem_rows,
        )
    expected_counts = {
        "norm_count": validation["norm_count"],
        "resource_count": validation["resource_count"],
        "fsem_rows": validation["fsem_rows"],
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
        )
        return {**validation, "action": "kept_existing"}

    state_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="les-smeta-baseline-", dir=state_root) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive) as bundle:
            for relative in REQUIRED_FILES:
                member = (PAYLOAD_PREFIX / relative).as_posix()
                target = staging / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
        validation = validate_root(
            staging,
            minimum_norms=int(archive_status["minimum_norms"]),
            minimum_fsem_rows=int(archive_status["minimum_fsem_rows"]),
        )
        for relative in REQUIRED_FILES:
            source = staging / Path(*relative.parts)
            target = state_root / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
    return {**validation, "action": "installed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source-root", type=Path, default=ROOT)
    create.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    create.add_argument("--minimum-norms", type=int, default=DEFAULT_MINIMUM_NORMS)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    verify_root = subparsers.add_parser("verify-root")
    verify_root.add_argument("--root", type=Path, required=True)
    verify_root.add_argument("--minimum-norms", type=int, default=DEFAULT_MINIMUM_NORMS)
    provision = subparsers.add_parser("provision")
    provision.add_argument("--archive", type=Path, required=True)
    provision.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        result = create_archive(args.source_root, args.archive, minimum_norms=args.minimum_norms)
    elif args.command == "verify":
        result = verify_archive(args.archive)
    elif args.command == "verify-root":
        result = validate_root(args.root, minimum_norms=args.minimum_norms)
    else:
        result = provision_archive(args.archive, args.state_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BaselineError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
