from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from tools import smeta_release_baseline as baseline


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_root(root: Path, *, norms: int = 2, fsem_rows: int = 2) -> Path:
    source = root / "data/gesn_base/gesn2022_unified.parquet"
    base = root / "data/smeta_base/les_smeta_base.sqlite"
    fsem = root / "data/smeta_base/fsem_2022.sqlite"
    source.parent.mkdir(parents=True)
    base.parent.mkdir(parents=True)
    source.write_bytes(b"typed-parquet-fixture")
    with sqlite3.connect(base) as conn:
        conn.executescript("CREATE TABLE norms(norm_key TEXT); CREATE TABLE resources(norm_key TEXT);")
        conn.executemany("INSERT INTO norms VALUES(?)", [(f"ГЭСН:{i}",) for i in range(norms)])
        conn.executemany("INSERT INTO resources VALUES(?)", [(f"ГЭСН:{i}",) for i in range(norms * 2)])
    with sqlite3.connect(fsem) as conn:
        conn.execute("CREATE TABLE machines(machine_code TEXT)")
        conn.executemany("INSERT INTO machines VALUES(?)", [(str(i),) for i in range(fsem_rows)])
    manifest = {
        "schema": "les_smeta_base_v2",
        "source": {"sha256": _sha(source)},
        "output": {"norms": norms, "resources": norms * 2},
    }
    integrity = {
        "schema": "les_smeta_base_integrity_v1",
        "verdict": "passed",
        "source_sha256": _sha(source),
        "base_sha256": _sha(base),
        "checks": {name: {"failures": 0} for name in baseline.REQUIRED_ZERO_CHECKS},
    }
    fsem_manifest = {
        "schema": "fsem_2022_catalog_manifest_v1",
        "verdict": "passed",
        "output": {"rows": fsem_rows, "sha256": _sha(fsem)},
    }
    (base.parent / "les_smeta_base_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base.parent / "les_smeta_base_integrity.json").write_text(json.dumps(integrity), encoding="utf-8")
    (base.parent / "fsem_2022_manifest.json").write_text(json.dumps(fsem_manifest), encoding="utf-8")
    return root


def test_release_baseline_roundtrip_provisions_clean_state(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"

    created = baseline.create_archive(source_root, archive, minimum_norms=2, minimum_fsem_rows=2)
    verified = baseline.verify_archive(archive)
    installed = baseline.provision_archive(archive, tmp_path / "state")

    assert created["norm_count"] == 2
    assert verified["schema"] == "les.smeta.release-baseline.v1"
    assert installed["action"] == "installed"
    assert installed["norm_count"] == 2
    packaged_integrity = json.loads(
        (tmp_path / "state/data/smeta_base/les_smeta_base_integrity.json").read_text(encoding="utf-8")
    )
    assert packaged_integrity["checks"]["minimum_norms"]["minimum"] == 2
    packaged_manifest = json.loads(
        (tmp_path / "state/data/smeta_base/les_smeta_base_manifest.json").read_text(encoding="utf-8")
    )
    assert packaged_manifest["minimum_norms"] == 2


def test_release_baseline_keeps_complete_existing_state(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(source_root, archive, minimum_norms=2, minimum_fsem_rows=2)
    state = tmp_path / "state"
    baseline.provision_archive(archive, state)

    assert baseline.provision_archive(archive, state)["action"] == "kept_existing"


def test_release_baseline_refuses_partial_existing_state(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(source_root, archive, minimum_norms=2, minimum_fsem_rows=2)
    state = tmp_path / "state"
    partial = state / "data/smeta_base/les_smeta_base.sqlite"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"user-state")

    with pytest.raises(baseline.BaselineError, match="refusing to overwrite"):
        baseline.provision_archive(archive, state)
    assert partial.read_bytes() == b"user-state"


def test_release_baseline_rejects_norm_count_regression(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source", norms=1)

    with pytest.raises(baseline.BaselineError, match="1 < 2 norms"):
        baseline.create_archive(source_root, tmp_path / "baseline.zip", minimum_norms=2, minimum_fsem_rows=2)


def test_release_baseline_rejects_corrupt_archive(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(source_root, archive, minimum_norms=2, minimum_fsem_rows=2)
    raw = bytearray(archive.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    archive.write_bytes(raw)

    with pytest.raises(baseline.BaselineError):
        baseline.verify_archive(archive)


def test_release_baseline_rejects_self_consistent_manifest_with_false_counts(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(source_root, archive, minimum_norms=2, minimum_fsem_rows=2)
    rewritten = tmp_path / "rewritten.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rewritten, "w") as target:
        for info in source.infolist():
            raw = source.read(info.filename)
            if info.filename == baseline.ARCHIVE_MANIFEST:
                manifest = json.loads(raw)
                manifest["norm_count"] = 3
                raw = json.dumps(manifest).encode("utf-8")
            target.writestr(info, raw)

    with pytest.raises(baseline.BaselineError, match="counts do not match payload"):
        baseline.verify_archive(rewritten)
