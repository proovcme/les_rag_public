from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from backend.qdrant_adapter import _resolve_embedding_runtime
from extensions.lemonade.runtime_env import windows_runtime_environment
from tools import windows_runtime, windows_update_engine
from tools.windows_runtime import runtime_environment


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_ENV = ROOT / "installers" / "windows" / "provider-env.ps1"
RUNTIME_PROCESS = ROOT / "installers" / "windows" / "runtime-process.ps1"


def _powershell() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is required to execute the Windows provider environment contract")
    return executable


def _run_provider_environment(provider: str, initial: dict[str, str]) -> dict[str, object]:
    quoted_path = str(PROVIDER_ENV).replace("'", "''")
    assignments = "\n".join(
        "[Environment]::SetEnvironmentVariable("
        f"'{key}', '{value.replace(chr(39), chr(39) * 2)}', 'Process')"
        for key, value in initial.items()
    )
    keys = sorted(
        {
            *initial,
            "LEMONADE_BASE_URL",
            "LEMONADE_MODEL",
            "LEMONADE_HOST_PORT",
            "MLX_URL",
            "EMBED_URL_PARSE",
            "LEMONADE_EMBED_MODEL",
            "EMBED_MODEL",
            "LES_SMETA_NORM_EMBED_MODEL",
            "EMBEDDING_MODEL",
            "LEMONADE_EMBED_BACKEND",
            "EMBED_BACKEND",
            "LES_EMBED_PROFILE",
            "RAG_VECTOR_SIZE",
        }
    )
    key_literals = ",".join(f"'{key}'" for key in keys)
    command = f"""
$ErrorActionPreference = 'Stop'
{assignments}
. '{quoted_path}'
function Get-TestEnvironment {{
  $result = @{{}}
  foreach ($name in @({key_literals})) {{
    $result[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  }}
  return $result
}}
Set-LesProviderEnvironment -Provider '{provider}' -AdapterPort 18080
$first = Get-TestEnvironment
Set-LesProviderEnvironment -Provider '{provider}' -AdapterPort 18080
$second = Get-TestEnvironment
[pscustomobject]@{{ first = $first; second = $second }} | ConvertTo-Json -Depth 5 -Compress
"""
    completed = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _powershell_lifecycle_state() -> dict[str, object]:
    quoted_path = str(RUNTIME_PROCESS).replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
. '{quoted_path}'
$adapterProcess = [pscustomobject]@{{ Id = 503; HasExited = $false }}
New-LesLemonadeLifecycleState -LemonadeHost $adapterProcess -LemonadeHostPort 18080 |
  ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _powershell_adapter_port_guard(port: int, is_free: bool) -> subprocess.CompletedProcess[str]:
    quoted_path = str(RUNTIME_PROCESS).replace("'", "''")
    command = f"""
$ErrorActionPreference = 'Stop'
. '{quoted_path}'
function Test-LesPortFree([int]$Port) {{ return ${str(is_free).lower()} }}
Assert-LesLemonadeAdapterPort -Port {port}
"""
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _write_lifecycle_state(state_root: Path, payload: dict[str, object]) -> None:
    logs = state_root / "logs"
    logs.mkdir(parents=True)
    python = state_root / ".venv" / "Scripts" / "pythonw.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"fixture")
    (logs / "windows-light-state.json").write_text(
        json.dumps(
            {
                "status": "started",
                "mode": "full",
                "provider": "lemonade",
                "proxy_pid": 501,
                "ui_pid": 502,
                **payload,
                "state_root": str(state_root),
                "process_contract": windows_runtime.PROCESS_CONTRACT,
                "python_executable": str(python),
            }
        ),
        encoding="utf-8",
    )


def test_powershell_lifecycle_state_releases_owned_adapter_for_candidate_and_rollback(
    tmp_path, monkeypatch
):
    state = tmp_path / "LES"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    legacy_payload = _powershell_lifecycle_state()
    assert legacy_payload["lemonade_host_port"] == 18080
    # The deployed pre-fix start-light state had these same fields except port.
    # Update must release its fixed adapter before the candidate writes new state.
    legacy_payload.pop("lemonade_host_port")
    _write_lifecycle_state(state, legacy_payload)
    listeners = {8050: 501, 8051: 502, 18080: 503}
    terminated: list[tuple[int, bool]] = []
    spawned: list[list[str]] = []

    class Process:
        def __init__(self, pid: int):
            self.pid = pid

        def poll(self):
            return None

    def listening_pids(ports):
        return {port: pid for port, pid in listeners.items() if port in ports}

    def terminate(pid, *, image_confirmed=False):
        terminated.append((pid, image_confirmed))
        for port, owner in list(listeners.items()):
            if owner == pid:
                listeners.pop(port)

    def spawn(_python, arguments, **kwargs):
        kwargs["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
        spawned.append(arguments)
        pid = 600 + len(spawned)
        if arguments == ["lemonade_host.py"]:
            listeners[18080] = pid
        elif "uvicorn" in arguments:
            listeners[8050] = pid
        else:
            listeners[8051] = pid
        return Process(pid)

    monkeypatch.setattr(windows_runtime, "_listening_pids", listening_pids)
    monkeypatch.setattr(windows_runtime, "_live_runtime_matches", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(windows_runtime, "_process_name", lambda _pid: "pythonw.exe")
    monkeypatch.setattr(windows_runtime, "_terminate_pid", terminate)
    monkeypatch.setattr(windows_runtime, "_port_free", lambda port: port not in listeners)
    monkeypatch.setattr(
        windows_runtime, "_python", lambda _state: state / ".venv" / "Scripts" / "pythonw.exe"
    )
    monkeypatch.setattr(windows_runtime, "_wait_process_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(windows_runtime, "_spawn", spawn)
    (state / ".env").write_text("LES_LLM_PROVIDER=lemonade\n", encoding="utf-8")

    stopped = windows_runtime.stop(state, runtime=runtime)

    assert stopped["pids"] == [501, 502, 503]
    assert terminated == [(501, True), (502, True), (503, True)]
    assert 18080 not in listeners

    candidate = windows_runtime.start(runtime, state)
    rollback_stop = windows_runtime.stop(state, runtime=runtime)
    rollback = windows_runtime.start(runtime, state)

    assert candidate["lemonade_host_port"] == 18080
    assert rollback_stop["pids"] == [601, 602, 603]
    assert rollback["lemonade_host_port"] == 18080
    assert [arguments for arguments in spawned if arguments == ["lemonade_host.py"]] == [
        ["lemonade_host.py"],
        ["lemonade_host.py"],
    ]


def test_powershell_lifecycle_state_never_replaces_foreign_adapter_owner(tmp_path, monkeypatch):
    state = tmp_path / "LES"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    _write_lifecycle_state(state, _powershell_lifecycle_state())
    listeners = {8050: 501, 8051: 502, 18080: 999}
    terminated: list[int] = []
    spawned: list[list[str]] = []

    monkeypatch.setattr(
        windows_runtime,
        "_listening_pids",
        lambda ports: {port: pid for port, pid in listeners.items() if port in ports},
    )
    monkeypatch.setattr(windows_runtime, "_terminate_pid", lambda pid, **_kwargs: terminated.append(pid))
    monkeypatch.setattr(windows_runtime, "_port_free", lambda port: port not in listeners)
    monkeypatch.setattr(windows_runtime, "_spawn", lambda _python, arguments, **_kwargs: spawned.append(arguments))

    with pytest.raises(RuntimeError, match="foreign_port_owner: 18080:999"):
        windows_runtime.stop(state, runtime=runtime)
    with pytest.raises(RuntimeError, match="foreign_port_owner: 18080:999"):
        windows_runtime.start(runtime, state)

    assert terminated == []
    assert listeners[18080] == 999
    assert spawned == []


def test_powershell_adapter_refuses_dynamic_or_occupied_port():
    assert _powershell_adapter_port_guard(18080, True).returncode == 0

    dynamic = _powershell_adapter_port_guard(18081, True)
    occupied = _powershell_adapter_port_guard(18080, False)

    assert dynamic.returncode != 0
    assert "must be 18080" in dynamic.stderr
    assert occupied.returncode != 0
    assert "18080 is occupied" in occupied.stderr


@pytest.mark.parametrize(
    ("adapter_url", "expected_port"),
    [
        ("http://127.0.0.1:18081", 18081),
        ("http://localhost:18081", 18081),
        ("http://10.0.0.4:18081", None),
        ("https://127.0.0.1:18081", None),
        ("http://127.0.0.1:not-a-port", None),
        ("not-a-url", None),
    ],
)
def test_legacy_lemonade_adapter_port_requires_validated_loopback_url(
    adapter_url, expected_port
):
    assert windows_runtime._state_adapter_port(
        {
            "provider": "lemonade",
            "lemonade_host_pid": 503,
            "lemonade_adapter_url": adapter_url,
        },
        "full",
    ) == expected_port


def test_update_attestation_accepts_operator_chunk_contract_but_rejects_identity_mismatch(
    tmp_path, monkeypatch
):
    state = tmp_path / "LES"
    _write_lifecycle_state(state, {**_powershell_lifecycle_state(), "lemonade_host_pid": 503})

    def ready_responses(*, family: str = "Qwen/Qwen3-Embedding-0.6B"):
        def probe(url, timeout=5):
            if url.endswith(":8050/api/version"):
                return {
                    "product_version": "0.30.77",
                    "build_number": 717,
                    "deployed_commit": "f" * 40,
                }
            if url.endswith(":8050/api/health"):
                return {
                    "rag": {"index_contract": {"compatible": True}, "qdrant": {}},
                    "embedding": {
                        "embedding_model": family,
                        "embedding_api_model": "Qwen3-Embedding-0.6B-GGUF",
                        "vector_size": 1024,
                        "chunk_unit": "chars",
                        "chunk_size_effective": 1550,
                        "chunk_overlap_effective": 70,
                    },
                }
            if url.endswith(":18080/api/health"):
                return {
                    "backend": "lemonade",
                    "embed_model": {
                        "path": "Qwen3-Embedding-0.6B-GGUF",
                        "embedding_backend": "llama_cpp",
                        "vector_size": 1024,
                    },
                }
            if "/api/lsr/gesn/" in url:
                return {"resources": [{"code": "1-100-01", "quantity": 1.0}]}
            raise AssertionError(url)

        return probe

    class HealthyUi:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(windows_update_engine.urllib.request, "urlopen", lambda *_args, **_kwargs: HealthyUi())
    monkeypatch.setattr(windows_update_engine, "_post_json_url", lambda *_args, **_kwargs: {"ranked": [{}]})
    monkeypatch.setattr(windows_update_engine, "_pid_running", lambda pid: pid in {501, 502, 503})
    monkeypatch.setattr(windows_update_engine, "_json_url", ready_responses())

    snapshot, failure = windows_update_engine._ready_snapshot(
        expected_commit="f" * 40,
        expected_version="0.30.77",
        expected_build=717,
        state=state,
        health_timeout=15,
    )

    assert failure == ""
    assert snapshot is not None
    assert snapshot["embedding_contract"] == "Qwen/Qwen3-Embedding-0.6B/llama_cpp/1024"

    monkeypatch.setattr(windows_update_engine, "_json_url", ready_responses(family="bge-m3"))
    snapshot, failure = windows_update_engine._ready_snapshot(
        expected_commit="f" * 40,
        expected_version="0.30.77",
        expected_build=717,
        state=state,
        health_timeout=15,
    )

    assert snapshot is None
    assert failure == "lemonade_contract=mismatch"


def test_lemonade_environment_is_exact_and_idempotent_across_restart_evaluation():
    result = _run_provider_environment(
        "lemonade",
        {"LEMONADE_MODEL": "Qwen3.6-8B-GGUF", "EMBED_BACKEND": "ollama"},
    )

    expected = {
        "LEMONADE_BASE_URL": "http://127.0.0.1:13305/api/v1",
        "LEMONADE_MODEL": "Qwen3.6-8B-GGUF",
        "LEMONADE_HOST_PORT": "18080",
        "MLX_URL": "http://127.0.0.1:18080",
        "EMBED_URL_PARSE": "http://127.0.0.1:18080",
        "LEMONADE_EMBED_MODEL": "Qwen3-Embedding-0.6B-GGUF",
        "EMBED_MODEL": "Qwen3-Embedding-0.6B-GGUF",
        # Сметный RAG обращается к тому же адаптеру и обязан называть модель так же.
        "LES_SMETA_NORM_EMBED_MODEL": "Qwen3-Embedding-0.6B-GGUF",
        "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-0.6B",
        "LEMONADE_EMBED_BACKEND": "llama_cpp",
        "EMBED_BACKEND": "llama_cpp",
        "LES_EMBED_PROFILE": "qwen",
        "RAG_VECTOR_SIZE": "1024",
    }
    assert windows_runtime_environment(adapter_port=18080) == {
        key: value for key, value in expected.items() if key != "LEMONADE_MODEL"
    }
    assert result == {"first": expected, "second": expected}


def test_lemonade_provider_preserves_operator_owned_chunk_contract(tmp_path, monkeypatch):
    index_contract = {
        "RAG_CHUNK_UNIT": "chars",
        "RAG_CHUNK_SIZE": "1550",
        "RAG_CHUNK_OVERLAP": "70",
        "RAG_CHUNK_TOKENS": "777",
        "RAG_CHUNK_OVERLAP_TOKENS": "88",
    }

    powershell_result = _run_provider_environment("lemonade", index_contract)
    for state in (powershell_result["first"], powershell_result["second"]):
        assert {key: state[key] for key in index_contract} == index_contract

    monkeypatch.setenv("LES_LLM_PROVIDER", "lemonade")
    monkeypatch.setenv("LEMONADE_MODEL", "Qwen3.6-8B-GGUF")
    for key, value in index_contract.items():
        monkeypatch.setenv(key, value)
    state_root = tmp_path / "state"
    state_root.mkdir()

    python_environment = runtime_environment(tmp_path / "runtime", state_root)

    assert {key: python_environment[key] for key in index_contract} == index_contract


def test_non_lemonade_profile_is_not_rewritten():
    initial = {
        "LEMONADE_MODEL": "unchanged-model",
        "MLX_URL": "http://127.0.0.1:11434",
        "EMBED_BACKEND": "ollama",
        "EMBED_MODEL": "bge-m3:latest",
        "RAG_CHUNK_TOKENS": "777",
    }

    result = _run_provider_environment("ollama", initial)

    for state in (result["first"], result["second"]):
        assert {key: state[key] for key in initial} == initial


def test_explicit_lemonade_backend_wins_over_legacy_windows_ollama_default():
    runtime = _resolve_embedding_runtime(
        "http://127.0.0.1:18080",
        "http://127.0.0.1:18080",
        configured_backend="llama_cpp",
        platform="win32",
    )

    assert runtime == (
        "http://127.0.0.1:18080",
        "llama_cpp",
        "http://127.0.0.1:18080",
        "llama_cpp",
    )


def test_unconfigured_legacy_windows_embedding_still_uses_ollama():
    runtime = _resolve_embedding_runtime(
        "http://127.0.0.1:8080",
        "",
        configured_backend="",
        platform="win32",
    )

    assert runtime == (
        "http://127.0.0.1:11434",
        "ollama",
        "http://127.0.0.1:11434",
        "ollama",
    )
