import argparse

from tools import runtime_smoke


def test_expect_status_accepts_expected_code():
    result = runtime_smoke.HttpResult(status=403, body='{"detail":"no"}', elapsed=0.1)

    check = runtime_smoke._expect_status("admin denied", result, [401, 403])

    assert check.ok is True
    assert check.detail == "HTTP 403"


def test_expect_status_reports_unexpected_code_body():
    result = runtime_smoke.HttpResult(status=200, body='{"ok":true}', elapsed=0.1)

    check = runtime_smoke._expect_status("admin denied", result, [401, 403])

    assert check.ok is False
    assert "expected [401, 403]" in check.detail


def test_expect_status_reports_transport_failure():
    result = runtime_smoke.HttpResult(status=0, body="connection refused", elapsed=0.1)

    check = runtime_smoke._expect_status("health", result, [200])

    assert check.ok is False
    assert "connection refused" in check.detail


def test_json_check_requires_keys():
    result = runtime_smoke.HttpResult(status=200, body='{"status":"ok"}', elapsed=0.1)

    check = runtime_smoke._json_check("health", result, [200], ["status", "backend"])

    assert check.ok is False
    assert "backend" in check.detail


def test_question_payload_adds_dataset_filter_only_when_present():
    assert runtime_smoke._question_payload("вопрос") == {"question": "вопрос"}
    assert runtime_smoke._question_payload("вопрос", "NTD") == {
        "question": "вопрос",
        "dataset_filter": "NTD",
    }


def test_parse_args_reads_external_auth_flag_from_env(monkeypatch):
    monkeypatch.setenv("LES_EXPECT_EXTERNAL_AUTH", "true")

    args = runtime_smoke.parse_args([])

    assert isinstance(args, argparse.Namespace)
    assert args.expect_external_auth is True
