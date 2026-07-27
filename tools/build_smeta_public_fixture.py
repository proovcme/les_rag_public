"""Build the public synthetic smeta base used by offline contract tests.

The real FSNB SQLite is runtime data and is not published. Clean clones still need
a tiny typed base so norm-store / estimate / visible-row contracts stay green.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from tools.build_smeta_structured_base import build_structured_base
from tools.gesn_import import RESOURCE_FIELDS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "tests/fixtures/smeta/public_base/norms.json"
DEFAULT_OUT_DIR = ROOT / "tests/fixtures/smeta/public_base"


def _resource_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for norm in spec.get("norms") or []:
        work_steps = json.dumps(list(norm.get("work_steps") or []), ensure_ascii=False)
        for resource in norm.get("resources") or []:
            row = {field: None for field in RESOURCE_FIELDS}
            row.update(
                {
                    "norm_code": norm["norm_code"],
                    "norm_key": norm["norm_key"],
                    "base_type": norm["base_type"],
                    "norm_name": norm["norm_name"],
                    "norm_unit": norm["norm_unit"],
                    "work_steps": work_steps,
                    # Resource provenance stays empty on purpose: missing_provenance fails
                    # pricing trust while navigation checks still pass.
                    "source_doc": "",
                    "source_guid": "",
                    "kind": resource["kind"],
                    "resource_code": resource.get("resource_code") or "",
                    "resource_name": resource["resource_name"],
                    "resource_unit": resource.get("resource_unit") or "",
                    "per_unit": resource.get("per_unit"),
                    "price": resource.get("price"),
                }
            )
            rows.append(row)
    return rows


def _stamp_norm_provenance(sqlite_out: Path, spec: dict[str, Any]) -> None:
    """Restore card-level source_ref after the builder copied empty resource provenance."""
    with sqlite3.connect(sqlite_out) as conn:
        for norm in spec.get("norms") or []:
            conn.execute(
                "UPDATE norms SET source_doc = ?, source_guid = ? WHERE norm_key = ?",
                (
                    str(norm.get("source_doc") or ""),
                    str(norm.get("source_guid") or ""),
                    str(norm["norm_key"]),
                ),
            )
        conn.commit()


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rewrite_integrity_after_provenance_stamp(
    *,
    sqlite_out: Path,
    integrity_out: Path,
    manifest_out: Path,
) -> dict[str, Any]:
    """Recompute provenance/fts checks and hashes after norm-level source stamps."""
    integrity = json.loads(integrity_out.read_text(encoding="utf-8"))
    with sqlite3.connect(sqlite_out) as conn:
        missing_provenance = int(
            conn.execute(
                "SELECT count(*) FROM norms WHERE source_doc = '' OR source_guid = ''"
            ).fetchone()[0]
        ) + int(
            conn.execute(
                "SELECT count(*) FROM resources WHERE source_doc = '' OR source_guid = ''"
            ).fetchone()[0]
        )
        fts_coverage = abs(
            int(conn.execute("SELECT count(*) FROM norms").fetchone()[0])
            - int(conn.execute("SELECT count(*) FROM norms_fts").fetchone()[0])
        )
    checks = dict(integrity.get("checks") or {})
    checks["missing_provenance"] = {"failures": missing_provenance}
    checks["fts_coverage"] = {"failures": fts_coverage}
    integrity["checks"] = checks
    integrity["base_sha256"] = _sha256(sqlite_out)
    integrity["verdict"] = (
        "passed" if not any(int(item.get("failures") or 0) for item in checks.values()) else "failed"
    )
    integrity_out.write_text(json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
    output = dict(manifest.get("output") or {})
    output["sha256"] = integrity["base_sha256"]
    manifest["output"] = output
    manifest["integrity"] = {
        "path": str(integrity_out),
        "schema": integrity.get("schema"),
        "verdict": integrity.get("verdict"),
    }
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return integrity


def build_public_fixture(
    *,
    spec_path: Path = DEFAULT_SPEC,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> dict[str, Any]:
    import shutil
    import tempfile

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_out = out_dir / "les_smeta_base.sqlite"
    manifest_out = out_dir / "les_smeta_base_manifest.json"
    integrity_out = out_dir / "les_smeta_base_integrity.json"

    rows = _resource_rows(spec)
    if not rows:
        raise RuntimeError(f"public fixture spec has no resources: {spec_path}")

    with tempfile.TemporaryDirectory(prefix="les_public_smeta_", ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        source = tmp_dir / "public_norms.parquet"
        tmp_sqlite = tmp_dir / "les_smeta_base.sqlite"
        tmp_manifest = tmp_dir / "les_smeta_base_manifest.json"
        tmp_integrity = tmp_dir / "les_smeta_base_integrity.json"
        pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(source, index=False)

        manifest = build_structured_base(
            source=source,
            out=tmp_sqlite,
            manifest_out=tmp_manifest,
            integrity_out=tmp_integrity,
            edition=str(spec.get("edition") or "PUBLIC-FIXTURE"),
            minimum_norms=0,
        )
        _stamp_norm_provenance(tmp_sqlite, spec)
        integrity = _rewrite_integrity_after_provenance_stamp(
            sqlite_out=tmp_sqlite,
            integrity_out=tmp_integrity,
            manifest_out=tmp_manifest,
        )
        # Copy finished artifacts into the fixture directory. Avoid in-place SQLite
        # replace on Windows, where antivirus can briefly lock the target path.
        shutil.copy2(source, out_dir / "public_norms.parquet")
        shutil.copy2(tmp_sqlite, sqlite_out)
        shutil.copy2(tmp_manifest, manifest_out)
        shutil.copy2(tmp_integrity, integrity_out)

    # Point manifest at the durable fixture paths, not the build tempdir.
    manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
    source_info = dict(manifest.get("source") or {})
    source_info["path"] = str(out_dir / "public_norms.parquet")
    manifest["source"] = source_info
    output = dict(manifest.get("output") or {})
    output["path"] = str(sqlite_out)
    manifest["output"] = output
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    missing = int(
        (integrity.get("checks") or {}).get("missing_provenance", {}).get("failures") or 0
    )
    if missing <= 0:
        raise RuntimeError(
            "public fixture must keep missing_provenance failures so pricing stays untrusted"
        )
    if integrity.get("verdict") == "passed":
        raise RuntimeError("public fixture integrity must stay failed for pricing quarantine")
    return {
        "spec": str(spec_path),
        "sqlite": str(sqlite_out),
        "manifest": str(manifest_out),
        "integrity": str(integrity_out),
        "norms": manifest["output"]["norms"],
        "resources": manifest["output"]["resources"],
        "integrity_verdict": integrity.get("verdict"),
        "missing_provenance": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    summary = build_public_fixture(spec_path=args.spec, out_dir=args.out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
