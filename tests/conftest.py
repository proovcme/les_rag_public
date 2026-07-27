"""Offline and reproducible defaults for the LES unit/integration test process."""

from __future__ import annotations

import os
from pathlib import Path

# Test collection/imports and health/config reads must not download models or
# depend on whether the workstation currently has internet access.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("RAG_TOKENIZER_LOCAL_FILES_ONLY", "true")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_BASE_DIR = _REPO_ROOT / "tests" / "fixtures" / "smeta" / "public_base"
_PUBLIC_SQLITE = _PUBLIC_BASE_DIR / "les_smeta_base.sqlite"
_PUBLIC_MANIFEST = _PUBLIC_BASE_DIR / "les_smeta_base_manifest.json"
_PUBLIC_INTEGRITY = _PUBLIC_BASE_DIR / "les_smeta_base_integrity.json"
_PUBLIC_SOURCE = _PUBLIC_BASE_DIR / "public_norms.parquet"
_PRODUCTION_SQLITE = _REPO_ROOT / "data" / "smeta_base" / "les_smeta_base.sqlite"


def _install_public_smeta_fixture() -> None:
    """Clean public clones have no FSNB runtime base; contract tests use a synthetic pack.

    Installed at import time so LES_SMETA_* env is visible before cached loaders run.
    """
    if os.getenv("LES_SMETA_STRUCTURED_BASE", "").strip():
        return
    if _PRODUCTION_SQLITE.exists():
        return

    if not _PUBLIC_SQLITE.exists() or not _PUBLIC_MANIFEST.exists() or not _PUBLIC_INTEGRITY.exists():
        from tools.build_smeta_public_fixture import build_public_fixture

        build_public_fixture(out_dir=_PUBLIC_BASE_DIR)

    os.environ["LES_SMETA_PUBLIC_FIXTURE"] = "1"
    os.environ["LES_SMETA_STRUCTURED_BASE"] = str(_PUBLIC_SQLITE)
    os.environ["LES_SMETA_BASE_MANIFEST"] = str(_PUBLIC_MANIFEST)
    os.environ["LES_SMETA_BASE_INTEGRITY"] = str(_PUBLIC_INTEGRITY)
    if _PUBLIC_SOURCE.exists():
        os.environ["LES_SMETA_BASE_SOURCE"] = str(_PUBLIC_SOURCE)


_install_public_smeta_fixture()
