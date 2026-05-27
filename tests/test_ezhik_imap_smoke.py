import json

from tools import ezhik_imap_smoke as smoke


def test_imap_smoke_skips_when_credentials_missing(monkeypatch, capsys):
    def fake_request(method, url, *, api_key="", payload=None, timeout=30.0):
        assert method == "GET"
        assert url.endswith("/api/mail/status")
        return smoke.HttpResult(
            200,
            {
                "status": "not_created",
                "dataset_name": "MAIL_Index",
                "imap": {"enabled": False},
            },
        )

    monkeypatch.setattr(smoke, "request_json", fake_request)
    monkeypatch.setattr("sys.argv", ["ezhik_imap_smoke.py", "--proxy-url", "http://proxy"])

    assert smoke.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped"
    assert payload["checks"][0]["imap_enabled"] is False


def test_imap_smoke_imports_when_configured(monkeypatch, capsys):
    calls = []

    def fake_request(method, url, *, api_key="", payload=None, timeout=30.0):
        calls.append((method, url, payload))
        if method == "GET":
            return smoke.HttpResult(
                200,
                {
                    "status": "ready",
                    "dataset_name": "MAIL_Index",
                    "imap": {"enabled": True, "host": "imap.example.com", "folders": ["INBOX"]},
                },
            )
        return smoke.HttpResult(
            200,
            {
                "status": "registered",
                "dataset_name": "MAIL_Index",
                "files": 1,
                "parse_started": False,
                "parse_blocked": "",
            },
        )

    monkeypatch.setattr(smoke, "request_json", fake_request)
    monkeypatch.setattr("sys.argv", ["ezhik_imap_smoke.py", "--proxy-url", "http://proxy", "--max-messages", "3"])

    assert smoke.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert calls[1][2] == {"max_messages": 3, "parse": False}
