import base64
import subprocess

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
