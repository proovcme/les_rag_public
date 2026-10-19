"""Both Windows launchers preserve the GUI reranker choice before config loads."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import windows_runtime


CASES = [
    pytest.param(None, None, "true", id="common-rerank-default"),
    pytest.param("false", None, "false", id="persisted-false"),
    pytest.param("true", None, "true", id="persisted-true"),
    pytest.param(None, "false", "false", id="process-false"),
    pytest.param(None, "true", "true", id="process-true"),
    pytest.param("true", "false", "true", id="persisted-true-wins"),
    pytest.param("false", "true", "false", id="persisted-false-wins"),
    pytest.param("", "false", "false", id="empty-persisted-falls-back"),
    pytest.param("  ", None, "true", id="blank-default"),
    pytest.param("'true'", "false", "true", id="quoted-persisted-true"),
]


def _state(tmp_path, persisted):
    state = tmp_path / "state \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430 'with spaces'"
    state.mkdir()
    lines = ["LES_LLM_PROVIDER=ollama", "FIXTURE_UNRELATED_VALUE=leave-this-alone"]
    if persisted is not None:
        lines.append("RERANKER_ENABLED=" + persisted)
    env_path = state / ".env"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return state, env_path, env_path.read_bytes()


@pytest.mark.parametrize("persisted,process,expected", CASES)
def test_python_runtime_environment_preserves_reranker_precedence(
    tmp_path, monkeypatch, persisted, process, expected
):
    state, env_path, before = _state(tmp_path, persisted)
    inherited = {"FIXTURE_PROCESS_ONLY": "unchanged"}
    if process is not None:
        inherited["RERANKER_ENABLED"] = process
    monkeypatch.setattr(windows_runtime, "os", SimpleNamespace(environ=inherited))

    effective = windows_runtime.runtime_environment(tmp_path / "runtime", state)

    assert effective["RERANKER_ENABLED"] == expected
    assert effective["FIXTURE_UNRELATED_VALUE"] == "leave-this-alone"
    assert effective["FIXTURE_PROCESS_ONLY"] == "unchanged"
    assert effective["RERANKER_BACKEND"] == "sentence_transformers"
    assert effective["RERANK_MODEL"] == "BAAI/bge-reranker-v2-m3"
    assert env_path.read_bytes() == before
    assert inherited == {
        "FIXTURE_PROCESS_ONLY": "unchanged",
        **({"RERANKER_ENABLED": process} if process is not None else {}),
    }


def _function(text: str, name: str) -> str:
    match = re.search(r"(?ms)^function " + re.escape(name) + r"\b.*?^}", text)
    assert match is not None, name
    return match.group(0)


@pytest.mark.parametrize("persisted,process,expected", CASES)
def test_native_powershell_embeds_only_preserve_reranker_precedence(
    tmp_path, persisted, process, expected
):
    """Run only two shipped pure helpers; never start a service or model."""
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell is required for the Windows launcher contract")
    state, env_path, before = _state(tmp_path, persisted)
    source = (ROOT / "installers/windows/start-light.ps1").read_text(encoding="utf-8-sig")
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps({"env_path": str(env_path), "process": process}), encoding="utf-8")
    harness = tmp_path / "reranker-choice-contract.ps1"
    harness.write_text(
        '''param([string]$FixturePath)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$fixture = Get-Content -LiteralPath $FixturePath -Raw | ConvertFrom-Json
$env:LES_ENV_PATH = $fixture.env_path
$env:RERANKER_ENABLED = $fixture.process
'''
        + _function(source, "Get-LesDotEnvValue")
        + "\n"
        + _function(source, "Set-LesOllamaEmbeddings")
        + '''
Set-LesOllamaEmbeddings
@{ reranker_enabled=$env:RERANKER_ENABLED } | ConvertTo-Json -Compress
''',
        encoding="utf-8-sig",
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(harness), "-FixturePath", str(fixture_path)],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )

    assert json.loads(completed.stdout)["reranker_enabled"] == expected
    assert env_path.read_bytes() == before


def test_native_static_contract_reads_only_reranker_choice_before_default():
    source = (ROOT / "installers/windows/start-light.ps1").read_text(encoding="utf-8-sig")
    body = _function(source, "Set-LesOllamaEmbeddings")
    persisted = body.index('Get-LesDotEnvValue "RERANKER_ENABLED"')
    inherited = body.index("[string]$env:RERANKER_ENABLED", persisted)
    default = body.index('$rerankerEnabled = "true"', inherited)
    assigned = body.index("$env:RERANKER_ENABLED = $rerankerEnabled.Trim()", default)
    assert persisted < inherited < default < assigned
    assert body.count("Get-LesDotEnvValue") == 1
    assert '$env:RERANKER_ENABLED = "false"' not in source
    for provider in ("ollama", "freetoken"):
        branch = re.search(r'(?ms)^  "' + provider + r'" \{.*?^  }', source)
        assert branch is not None
        assert "Set-LesOllamaEmbeddings" in branch.group(0)
