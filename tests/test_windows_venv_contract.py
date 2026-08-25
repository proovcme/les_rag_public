from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")


def _ps(script: str, cwd: Path) -> str:
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "$ErrorActionPreference='Stop'; " + script],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_venv_contract_exact_match_mismatch_and_corruption(tmp_path):
    module = ROOT / "installers" / "windows" / "app" / "venv-contract.ps1"
    (tmp_path / "uv.lock").write_text('requires-python = ">=3.12, <3.14"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12,<3.14"\n', encoding="utf-8"
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / ".les-cache-ready").write_text("cache-id", encoding="utf-8")
    marker = tmp_path / "state" / "venv-contract.json"
    marker.parent.mkdir()
    uv = shutil.which("uv")
    script = f"""
      . '{module}'
      $expected = Get-LesVenvContract -Root '{tmp_path}' -State '{marker.parent}' -BundledPython '{sys.executable}' -Uv '{uv}' -Extra 'windows-reranker' -CacheRoot '{cache}'
      $missing = Test-LesVenvContract -Expected $expected -MarkerPath '{marker}'
      Write-LesVenvContractAtomically -Contract $expected -MarkerPath '{marker}'
      $exact = Test-LesVenvContract -Expected $expected -MarkerPath '{marker}'
      Add-Content -LiteralPath '{tmp_path / "uv.lock"}' -Value '# changed'
      $changed = Get-LesVenvContract -Root '{tmp_path}' -State '{marker.parent}' -BundledPython '{sys.executable}' -Uv '{uv}' -Extra 'windows-reranker' -CacheRoot '{cache}'
      $mismatch = Test-LesVenvContract -Expected $changed -MarkerPath '{marker}'
      Set-Content -LiteralPath '{marker}' -Value '{{broken json'
      $corrupt = Test-LesVenvContract -Expected $changed -MarkerPath '{marker}'
      @{{missing=$missing; exact=$exact; mismatch=$mismatch; corrupt=$corrupt; schema=$expected.schema; requires_python=$expected.requires_python}} | ConvertTo-Json -Compress
    """

    result = json.loads(_ps(script, tmp_path).splitlines()[-1])

    assert result == {
        "missing": False,
        "exact": True,
        "mismatch": False,
        "corrupt": False,
        "schema": "les.windows-venv-contract.v1",
        "requires_python": ">=3.12,<3.14",
    }


def test_venv_health_requires_a_python_that_can_import_les(tmp_path):
    module = ROOT / "installers" / "windows" / "app" / "venv-contract.ps1"
    broken = tmp_path / "broken.cmd"
    broken.write_text("@exit /b 1\n", encoding="ascii")
    script = f"""
      . '{module}'
      $healthy = Test-LesVenvHealth -Python '{sys.executable}'
      $broken = Test-LesVenvHealth -Python '{broken}'
      @{{healthy=$healthy; broken=$broken}} | ConvertTo-Json -Compress
    """

    result = json.loads(_ps(script, ROOT).splitlines()[-1])

    assert result == {"healthy": True, "broken": False}
