"""Release proof «ни один эталонный иток не зависит от книги оператора» (§ 3, сборка 830).

Every money pin in the ЛСР suites used to be measured against whichever parquet happened to
sit in ``data/price_base`` on the workstation: ``test_lsr_assembly_service`` pinned the
amount the demo seed produced, ``test_fsem_machinist_service`` called ``_resolve_book(None)``
and accepted whichever book the runtime resolved, and the endpoint/chat/artifact tests read
the default stem.  On a machine with another region or quarter installed those tests would
have failed — or, worse, kept passing while proving nothing about the shipped build.

The ruling this file enforces: pinned money comes from a book the test owns — either rates
written in the test itself, or the deterministic ``_Book`` of
``tests/test_rim_lsr_trace_service.py`` (rows measured from ``sankt-peterburg_2kv2026``,
``stage_b/live_830/gold_rebaseline_830.json``) injected through
``tests/lsr_gold_pricebook.py``.  The verified norm base stays a real dependency: cards are
shipped with the build, prices are not.

This is checked by re-running the money suites in a child process whose price root does not
exist (``tests/pricebook_probe.py``).  The norm base is untouched, so any failure there is a
pin that read the operator's book, not a card that went missing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    os.environ.get("LES_PRICEBOOK_PROBE") == "1",
    reason="this process already has no price book: the gate would only re-run itself",
)

# The suites that pin сметные деньги, in the order a reviewer would read them: the gold
# position, its render, the two HTTP routes, chat, the artifact, then the engines feeding them.
MONEY_SUITES = (
    "tests/test_rim_lsr_trace_service.py",
    "tests/test_rim_trace_xlsx.py",
    "tests/test_lsr_rim_trace_api.py",
    "tests/test_lsr_assembly_service.py",
    "tests/test_smeta_chat_service.py",
    "tests/test_smeta_artifact_service.py",
    "tests/test_fsem_machinist_service.py",
    "tests/test_gesn_service.py",
    "tests/test_lsr_price_ownership.py",
    "tests/test_lsr_disguised_gaps.py",
    "tests/test_revision_projection_830.py",
    "tests/test_lsr_labor_tariff_830.py",
    "tests/test_gesn_seed_is_test_only_830.py",
    "tests/test_workbook_tool_service.py",
)


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    # `tests` must be importable at plugin pre-parse, before pytest reads the ini's pythonpath.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "tests"), *(p for p in (env.get("PYTHONPATH") or "").split(os.pathsep) if p)]
    )
    # A configured default book would be a machine setting leaking into the proof.
    env.pop("LES_DEFAULT_PRICEBOOK", None)
    return env


def test_every_money_suite_passes_with_no_price_book_installed(tmp_path):
    """The hermeticity gate: the same pins, on a machine that has no ценовая база."""

    assert MONEY_SUITES, "the gate would be asserting an empty claim"
    for suite in MONEY_SUITES:
        assert (ROOT / suite).is_file(), f"money suite vanished from the gate: {suite}"

    completed = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-m", "pytest",
            "-p", "pricebook_probe",
            "-q",
            "--basetemp", str(tmp_path / "probe"),
            "-o", "addopts=",
            *MONEY_SUITES,
        ],
        cwd=ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=1800,
    )

    tail = "\n".join(completed.stdout.strip().splitlines()[-40:])
    assert completed.returncode == 0, (
        "a pinned сметный иток depends on the installed ценовая база — the run above has no "
        f"price book at all:\n{tail}\n{completed.stderr[-2000:]}"
    )
