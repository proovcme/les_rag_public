import base64
import argparse
import subprocess
import urllib.error
from contextlib import contextmanager

from tools import run_artel_legion_revit_validation as runner


def test_parse_json_object_skips_powershell_noise():
    payload = runner.parse_json_object(
        "info: before\r\n"
        "{\n"
        '  "status": "interactive",\n'
        '  "lockScreen": false\n'
        "}\n"
        "trailing"
    )

    assert payload == {"status": "interactive", "lockScreen": False}


def test_quote_helpers_for_windows_paths():
    assert runner.ps_single_quote(r"C:\Users\Oleg\it's.rfa") == r"'C:\Users\Oleg\it''s.rfa'"
    assert (
        runner.remote_script(r"C:\Users\Oleg\AppData\Local\Temp\artel-current-autorun", "run.ps1")
        == r"C:\Users\Oleg\AppData\Local\Temp\artel-current-autorun\run.ps1"
    )
    assert runner.windows_path_for_scp(r"C:\Users\Oleg\AppData\file.json") == "C:/Users/Oleg/AppData/file.json"


def test_diagnose_legion_uses_remote_script(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=None):
        calls.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"locked","lockScreen":true}', stderr="")

    monkeypatch.setattr(runner, "run_command", fake_run)

    diagnosis = runner.diagnose_legion("legion", r"C:\remote", 12)

    assert diagnosis["status"] == "locked"
    command, timeout = calls[0]
    assert timeout == 12
    assert command[:7] == [
        "ssh",
        "legion",
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
    ]
    decoded = base64.b64decode(command[7]).decode("utf-16le")
    assert decoded == r"& 'C:\remote\diagnose-family-factory-revit-session.ps1'"


def test_copy_report_uses_scp_windows_path(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, *, timeout=None):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "run_command", fake_run)

    copied = runner.copy_report("legion", r"C:\Users\Oleg\AppData\Roaming\ARTEL\validation_1.json", tmp_path)

    assert copied == tmp_path / "validation_1.json"
    assert calls == [
        [
            "scp",
            "legion:C:/Users/Oleg/AppData/Roaming/ARTEL/validation_1.json",
            str(tmp_path / "validation_1.json"),
        ]
    ]


def test_check_artel_backend_accepts_ok_health(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status":"ok"}'

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:5057/health"
        assert timeout == 2
        return FakeResponse()

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)

    health = runner.check_artel_backend("http://127.0.0.1:5057", timeout=2)

    assert health == {
        "ok": True,
        "url": "http://127.0.0.1:5057/health",
        "response": {"status": "ok"},
    }


def test_check_artel_backend_reports_connection_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)

    health = runner.check_artel_backend("http://127.0.0.1:5057", timeout=2)

    assert health["ok"] is False
    assert health["url"] == "http://127.0.0.1:5057/health"
    assert "connection refused" in health["error"]


def test_revit_artel_url_uses_legion_localhost_for_remote_backend():
    args = argparse.Namespace(
        use_legion_artel_backend=True,
        legion_artel_backend_url="http://127.0.0.1:5057",
        artel_url="http://127.0.0.1:15057",
    )

    assert runner.revit_artel_url(args) == "http://127.0.0.1:5057"


def test_start_legion_backend_command_uses_encoded_powershell():
    args = argparse.Namespace(
        ssh_host="legion",
        legion_artel_backend_dll=(
            r"C:\Users\Oleg\AppData\Local\Temp\artel-backend-persist"
            r"\backend\Agnostis.Api\bin\Release\net8.0\Agnostis.Api.dll"
        ),
        legion_artel_backend_data_dir=r"C:\Users\Oleg\AppData\Local\Temp\artel-backend-persist\runtime-data",
        legion_artel_backend_url="http://127.0.0.1:5057",
    )

    command = runner.start_legion_backend_command(args)

    assert command[:7] == [
        "ssh",
        "legion",
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
    ]
    decoded = base64.b64decode(command[7]).decode("utf-16le")
    assert "$env:ARTEL_DATA_DIR='C:\\Users\\Oleg\\AppData\\Local\\Temp\\artel-backend-persist\\runtime-data'" in decoded
    assert "$env:ASPNETCORE_URLS='http://127.0.0.1:5057'" in decoded
    assert "dotnet 'C:\\Users\\Oleg\\AppData\\Local\\Temp\\artel-backend-persist" in decoded


def test_start_tunnel_command_uses_local_and_remote_ports():
    args = argparse.Namespace(ssh_host="legion", legion_artel_local_port=15057, legion_artel_remote_port=5057)

    assert runner.start_tunnel_command(args) == [
        "ssh",
        "-N",
        "-L",
        "15057:127.0.0.1:5057",
        "legion",
    ]


def test_backend_only_smoke_skips_revit_diagnosis(monkeypatch, capsys):
    @contextmanager
    def fake_backend(args, summary):
        summary["legion_artel_backend"] = {"local_url": args.artel_url}
        yield

    def fail_diagnose(*args, **kwargs):
        raise AssertionError("diagnose must not run for backend-only smoke")

    monkeypatch.setattr(runner, "legion_artel_backend", fake_backend)
    monkeypatch.setattr(runner, "diagnose_legion", fail_diagnose)
    monkeypatch.setattr(
        runner,
        "check_artel_backend",
        lambda artel_url, *, timeout: {"ok": True, "url": artel_url.rstrip("/") + "/health", "response": {"status": "ok"}},
    )
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--backend-only-smoke"])

    assert runner.main() == 0
    assert '"status": "ok"' in capsys.readouterr().out


def test_legion_backend_pids_parses_numeric_stdout(monkeypatch):
    args = argparse.Namespace(ssh_host="legion", legion_artel_backend_dll=r"C:\tmp\Agnostis.Api.dll")

    def fake_run(command, *, timeout=None):
        return subprocess.CompletedProcess(command, 0, stdout="41816\nnot-a-pid\n42\n", stderr="")

    monkeypatch.setattr(runner, "run_command", fake_run)

    assert runner.legion_backend_pids(args) == {42, 41816}


def test_stop_legion_backend_pids_uses_only_given_pids(monkeypatch):
    calls = []
    args = argparse.Namespace(ssh_host="legion")

    def fake_run(command, *, timeout=None):
        calls.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runner, "run_command", fake_run)

    runner.stop_legion_backend_pids(args, {41816, 42})

    command, timeout = calls[0]
    assert timeout == 15
    decoded = base64.b64decode(command[7]).decode("utf-16le")
    assert "@(42,41816)" in decoded
    assert "Stop-Process -Id $processId" in decoded
