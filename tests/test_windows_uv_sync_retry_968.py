from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell")
MODULE = ROOT / "installers/windows/app/venv-contract.ps1"
BOOTSTRAP = ROOT / "installers/windows/app/bootstrap.ps1"
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
PE_ERROR = (
    "error: Failed to install: distro.whl\n"
    "Caused by: Failed to update Windows PE resources: C:\\fixture\\uv-trampoline-123.exe\n"
    "Caused by: Access denied. (os error -2147024891)"
)
ARGS = ["sync", "--locked", "--offline", "--python", "C:\\space path\\python.exe",
        "--no-python-downloads", "--extra", "windows-reranker"]


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run_ps(tmp_path: Path, script: str) -> dict:
    path = tmp_path / "run.ps1"
    path.write_text("$ErrorActionPreference='Stop'\n[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)\n" + script, encoding="utf-8-sig")
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _fake_uv(tmp_path: Path, outcomes: list[dict], *, healthy: bool = False) -> tuple[Path, Path, Path, Path]:
    directory = tmp_path / "uv path ' кириллица"
    directory.mkdir()
    marker, health = tmp_path / "venv-contract.json", tmp_path / "healthy"
    marker.write_text('{"schema":"fixture-contract"}', encoding="utf-8")
    if healthy:
        health.write_text("yes", encoding="ascii")
    state = directory / "state.json"
    state.write_text(json.dumps({"outcomes": outcomes, "calls": [], "marker": str(marker),
                                 "health": str(health), "partial": str(tmp_path / "partial")}), encoding="utf-8")
    worker = directory / "fake_uv.py"
    worker.write_text(
        "import json,pathlib,sys\n"
        "p=pathlib.Path(__file__).with_name('state.json'); s=json.loads(p.read_text(encoding='utf-8-sig'))\n"
        "i=len(s['calls']); outcome=s['outcomes'][min(i,len(s['outcomes'])-1)]\n"
        "s['calls'].append({'argv':sys.argv[1:], 'marker_exists':pathlib.Path(s['marker']).exists(),"
        "'partial_exists':pathlib.Path(s['partial']).exists()})\n"
        "pathlib.Path(s['partial']).write_text('partial',encoding='ascii')\n"
        "p.write_text(json.dumps(s),encoding='utf-8')\n"
        "print('fixture attempt '+str(i+1))\n"
        "print(outcome.get('output',''),file=sys.stderr)\n"
        "if not outcome['exit'] and outcome.get('healthy',True): pathlib.Path(s['health']).write_text('yes',encoding='ascii')\n"
        "sys.exit(outcome['exit'])\n", encoding="ascii",
    )
    command = directory / "fake uv.cmd"
    command.write_text(f'@"{sys.executable}" "%~dp0fake_uv.py" %*\n', encoding="ascii")
    return command, state, marker, health


@pytest.mark.parametrize("outcomes, expected_attempts, expected_exit", [
    ([{"exit": 2, "output": PE_ERROR}, {"exit": 0}], 2, 0),
    ([{"exit": 2, "output": PE_ERROR}, {"exit": 2, "output": PE_ERROR}, {"exit": 0}], 3, 0),
    ([{"exit": 2, "output": PE_ERROR}], 3, 2),
    ([{"exit": 0, "output": PE_ERROR}], 1, 0),
    ([{"exit": 7, "output": "Access denied. (os error -2147024891)"}], 1, 7),
    ([{"exit": 7, "output": PE_ERROR.replace("uv-trampoline-123.exe", "unrelated.exe")}], 1, 7),
    ([{"exit": 7, "output": PE_ERROR.replace("-2147024891", "-2147024786")}], 1, 7),
    ([{"exit": 7, "output": PE_ERROR.replace("-2147024891", "-21470248910")}], 1, 7),
    ([{"exit": 7, "output": "SHA-256 mismatch: offline wheel"}], 1, 7),
    ([{"exit": 7, "output": "Network timeout while downloading"}], 1, 7),
])
def test_real_uv_helper_retries_only_observed_pe_failure_and_keeps_argv_and_eap(
    tmp_path, outcomes, expected_attempts, expected_exit,
):
    command, state_path, _, _ = _fake_uv(tmp_path, outcomes)
    argument_json = tmp_path / "argv.json"
    argument_json.write_text(json.dumps(ARGS), encoding="utf-8")
    result = _run_ps(tmp_path, f"""
      . {_quote(MODULE)}
      $argvList = Get-Content -LiteralPath {_quote(argument_json)} -Raw | ConvertFrom-Json
      $result = Invoke-LesUvSyncWithRetry -Uv {_quote(command)} -SyncArgs $argvList
      @{{exit_code=$result.ExitCode; attempts=$result.Attempts; output=@($result.Output | ForEach-Object {{[string]$_}});
         records=@($result.AttemptResults | ForEach-Object {{@{{attempt=$_.Attempt; exit_code=$_.ExitCode}}}});
         preference=[string]$ErrorActionPreference}} | ConvertTo-Json -Depth 8 -Compress
    """)
    calls = json.loads(state_path.read_text(encoding="utf-8"))["calls"]
    assert result["exit_code"] == expected_exit
    assert result["attempts"] == len(calls) == len(result["records"]) == expected_attempts
    assert [record["attempt"] for record in result["records"]] == list(range(1, expected_attempts + 1))
    assert all(call["argv"] == ARGS for call in calls)
    assert [call["partial_exists"] for call in calls] == [False] + [True] * (expected_attempts - 1)
    assert result["preference"] == "Stop"
    assert all(f"fixture attempt {number}" in "\n".join(result["output"]) for number in range(1, expected_attempts + 1))
    if outcomes[0].get("output"):
        # Native stdout/stderr can interleave; every original diagnostic line
        # must survive, without assuming an ordering between the two streams.
        assert all(line in "\n".join(result["output"]) for line in outcomes[0]["output"].splitlines())


def test_uv_launch_exception_is_not_hidden_and_restores_eap(tmp_path):
    result = _run_ps(tmp_path, f"""
      . {_quote(MODULE)}
      $LASTEXITCODE = 0
      $failure = ''
      try {{ Invoke-LesUvSyncWithRetry -Uv {_quote(tmp_path / 'missing uv.exe')} -SyncArgs @('sync','--locked','--offline') | Out-Null }}
      catch {{ $failure = $_.Exception.Message }}
      @{{failure=$failure; preference=[string]$ErrorActionPreference}} | ConvertTo-Json -Compress
    """)
    assert "missing uv.exe" in result["failure"]
    assert result["preference"] == "Stop"


def _bootstrap_runs(tmp_path: Path, outcomes: list[dict], *, runs: int, healthy: bool = True) -> tuple[dict, dict]:
    command, state_path, marker, health = _fake_uv(tmp_path, outcomes, healthy=healthy)
    if healthy:
        marker.write_text('{"schema":"previous-contract"}', encoding="utf-8")
    text = BOOTSTRAP.read_text(encoding="utf-8-sig")
    block = text.split("# --- 2. Environment", 1)[1].split("\n", 1)[1].split("# A clean install", 1)[0]
    # Execute the actual shipped environment block. Only nonenvironment UI/status
    # and the expensive Python import probe are stubbed; contract/marker/sync are real.
    block_path = tmp_path / "environment-block.ps1"
    block_path.write_text(block, encoding="utf-8-sig")
    result = _run_ps(tmp_path, f"""
      . {_quote(MODULE)}
      $script:logs = New-Object System.Collections.Generic.List[string]
      function Log([string]$line) {{ $script:logs.Add($line) }}
      function Toast([string]$line) {{ }}
      function Write-Status {{ param($Phase,$State,$Message) }}
      function Fail([string]$message,[string]$code) {{ throw ($code + ': ' + $message) }}
      function Get-LesVenvContract {{ return [ordered]@{{schema='fixture-contract'}} }}
      function Test-LesVenvHealth {{ return (Test-Path -LiteralPath {_quote(health)}) }}
      $Uv = {_quote(command)}; $BundledPython = 'C:\\space path\\python.exe'
      $State = @{{state_root={_quote(tmp_path)}}}; $env:UV_PROJECT_ENVIRONMENT = {_quote(tmp_path / 'venv')}
      $env:LES_TAURI_SHELL = '1'
      $actualMarker = Join-Path $State.state_root 'artifacts\\venv-contract.json'
      New-Item -ItemType Directory -Path (Split-Path $actualMarker) -Force | Out-Null
      Move-Item -LiteralPath {_quote(marker)} -Destination $actualMarker
      $fixture = Get-Content -LiteralPath {_quote(state_path)} -Raw | ConvertFrom-Json
      $fixture.marker = $actualMarker
      $fixture | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath {_quote(state_path)} -Encoding UTF8
      $summaries = @()
      for ($boot = 1; $boot -le {runs}; $boot++) {{
        $errorText = ''; $script:EnvironmentAction = ''
        try {{ . {_quote(block_path)} }} catch {{ $errorText = $_.Exception.Message }}
        $summaries += @{{error=$errorText; marker_exists=(Test-Path -LiteralPath $actualMarker);
                         action=$script:EnvironmentAction; preference=[string]$ErrorActionPreference}}
      }}
      @{{runs=@($summaries); logs=@($script:logs)}} | ConvertTo-Json -Depth 8 -Compress
    """)
    return result, json.loads(state_path.read_text(encoding="utf-8-sig"))


def test_actual_bootstrap_recovers_then_second_boot_skips_and_redacts_every_attempt(tmp_path):
    result, state = _bootstrap_runs(tmp_path, [
        {"exit": 2, "output": PE_ERROR + "\nhttps://fixture-user:fixture-password@example.invalid/a"},
        {"exit": 0},
    ], runs=2, healthy=False)
    assert [run["error"] for run in result["runs"]] == ["", ""]
    assert [run["action"] for run in result["runs"]] == ["repaired", "skipped"]
    assert all(run["marker_exists"] and run["preference"] == "Stop" for run in result["runs"])
    assert len(state["calls"]) == 2
    assert all(not call["marker_exists"] for call in state["calls"])
    assert state["calls"][0]["argv"] == state["calls"][1]["argv"] == ARGS
    logs = "\n".join(result["logs"])
    assert "fixture attempt 1" in logs and "fixture attempt 2" in logs
    assert "fixture-password" not in logs and "fixture-user" not in logs
    assert "https://***@example.invalid/a" in logs


def test_failed_sync_invalidates_stale_marker_and_next_boot_really_syncs(tmp_path):
    result, state = _bootstrap_runs(tmp_path, [{"exit": 2, "output": PE_ERROR}] * 3 + [{"exit": 0}], runs=2)
    assert result["runs"][0]["error"].startswith("python_environment_invalid:")
    assert result["runs"][0]["marker_exists"] is False
    assert result["runs"][1]["error"] == ""
    assert result["runs"][1]["action"] == "synced"
    assert result["runs"][1]["marker_exists"] is True
    assert len(state["calls"]) == 4
    assert all(not call["marker_exists"] for call in state["calls"])
    assert all(run["preference"] == "Stop" for run in result["runs"])
    assert all(f"fixture attempt {number}" in "\n".join(result["logs"]) for number in range(1, 5))


def test_failed_unrelated_sync_stops_after_one_and_retains_diagnostic(tmp_path):
    # A matching but stale marker must be invalidated when the core import probe fails.
    result, state = _bootstrap_runs(tmp_path, [{"exit": 9, "output": "wheel SHA-256 mismatch"}], runs=1, healthy=False)
    assert len(state["calls"]) == 1
    assert result["runs"][0]["marker_exists"] is False
    assert "код 9" in result["runs"][0]["error"]
    assert "wheel SHA-256 mismatch" in result["runs"][0]["error"]


def test_successful_sync_still_requires_existing_import_smoke_before_marker(tmp_path):
    result, state = _bootstrap_runs(tmp_path, [{"exit": 0, "healthy": False}], runs=1, healthy=False)
    assert len(state["calls"]) == 1
    assert result["runs"][0]["error"].startswith("python_environment_invalid:")
    assert result["runs"][0]["marker_exists"] is False
