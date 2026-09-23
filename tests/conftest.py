"""Offline and reproducible defaults for the LES unit/integration test process."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Test collection/imports and health/config reads must not download models or
# depend on whether the workstation currently has internet access.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("RAG_TOKENIZER_LOCAL_FILES_ONLY", "true")

# A handful of tools/services assign os.environ["LES_WINDOWS_STATE_ROOT"]
# directly (not via monkeypatch) — for example an installed
# %LOCALAPPDATA%\LES state root resolved on a developer workstation that
# happens to run LES. That value is never undone, so it leaks into unrelated
# later tests and makes them read/write AppData paths instead of the offline
# ./data defaults they assert. The result is order- and machine-dependent:
# identical sources pass in isolation but fail in full-suite order.
_HERMETIC_ENV_REMOVALS = ("LES_WINDOWS_STATE_ROOT",)


@pytest.fixture(autouse=True)
def _hermetic_process_state():
    """Give every test a clean, reproducible process-global baseline.

    Snapshot os.environ and the cwd, drop the known non-restored install state
    root for the duration of the test, and restore the (cleaned) snapshot
    afterwards so no direct os.environ/chdir mutation from one test can bleed
    into the next. Tests that legitimately need state still set it through
    monkeypatch, which runs and unwinds inside this window.
    """
    for name in _HERMETIC_ENV_REMOVALS:
        os.environ.pop(name, None)
    env_snapshot = dict(os.environ)
    cwd_snapshot = os.getcwd()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)
        try:
            os.chdir(cwd_snapshot)
        except OSError:
            os.chdir(Path(__file__).resolve().parents[1])
