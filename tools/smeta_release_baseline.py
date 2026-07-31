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
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
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


class BaselineError(RuntimeError):
    """The release baseline is missing, inconsistent or unsafe to provision."""


def _repair_windows_file_acl(state_root: Path) -> None:
    """Restore current-user access only for the immutable baseline allowlist."""
    if os.name != "nt":
        return
    identity = "\\".join(
        value for value in (os.getenv("USERDOMAIN", ""), os.getenv("USERNAME", "")) if value
    )
    if not identity:
        raise BaselineError("cannot determine the Windows identity for baseline ACL repair")
    for relative in REQUIRED_FILES:
        target = state_root / Path(*relative.parts)
        if not target.is_file():
            continue
        for command in (
            ["takeown.exe", "/F", str(target)],
            ["icacls.exe", str(target), "/inheritance:e", "/grant:r", f"{identity}:(F)", "/Q"],
        ):
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=0x08000000,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-800:]
                raise BaselineError(
                    f"Windows ACL repair failed for {relative.as_posix()}: {detail}"
                )


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
) -> dict[str, Any]:
    validation = validate_root(
        source_root,
        minimum_norms=minimum_norms,
        minimum_fsem_rows=minimum_fsem_rows,
        minimum_price_rows=minimum_price_rows,
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
            "pricebook_rows": validation["pricebook_rows"],
            "minimum_pricebook_rows": minimum_price_rows,
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
    minimum_price_rows = int(manifest.get("minimum_pricebook_rows") or 0)
    if int(manifest.get("norm_count") or 0) < minimum_norms:
        raise BaselineError("smeta baseline archive norm floor is not satisfied")
    if int(manifest.get("fsem_rows") or 0) < minimum_fsem_rows:
        raise BaselineError("smeta baseline archive FSEM floor is not satisfied")
    if int(manifest.get("pricebook_rows") or 0) < minimum_price_rows:
        raise BaselineError("smeta baseline archive pricebook floor is not satisfied")
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
            minimum_price_rows=minimum_price_rows,
        )
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
            minimum_price_rows=int(archive_status["minimum_pricebook_rows"]),
        )
        for relative in REQUIRED_FILES:
            source = staging / Path(*relative.parts)
            target = state_root / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
    return {**validation, "action": "installed"}


def repair_archive(archive: Path, state_root: Path) -> dict[str, Any]:
    """Restore a broken/partial baseline from the verified release payload.

    A valid newer operator base is kept. A broken state is copied to a dated
    recovery directory before the verified baseline replaces the complete
    linked file set, so norms/manifests/FSEM can never be mixed across revisions.
    """
    archive_status = verify_archive(archive)
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
            return {**current, "action": "kept_valid"}
        reason = "persistent smeta baseline is older than release payload: " + ", ".join(behind)
    except (BaselineError, OSError) as current_error:
        reason = str(current_error)
        access_error = isinstance(current_error, PermissionError) or isinstance(
            getattr(current_error, "__cause__", None), PermissionError
        )
        if access_error:
            _repair_windows_file_acl(state_root)

    state_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = state_root / "storage" / "recovery" / f"smeta_baseline_{stamp}"
    backed_up: list[str] = []
    with tempfile.TemporaryDirectory(prefix="les-smeta-repair-", dir=state_root) as temporary:
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
            for relative in REQUIRED_FILES:
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source-root", type=Path, default=ROOT)
    create.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    create.add_argument("--minimum-norms", type=int, default=DEFAULT_MINIMUM_NORMS)
    create.add_argument("--minimum-price-rows", type=int, default=DEFAULT_MINIMUM_PRICE_ROWS)
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
