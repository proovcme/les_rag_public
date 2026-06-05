import argparse

from tools import browser_smoke


def test_validate_args_requires_url_scheme():
    args = argparse.Namespace(ui_url="localhost:8051", trusted_local=True, admin_key="")

    assert "Invalid --ui-url" in browser_smoke.validate_args(args)


def test_validate_args_requires_admin_key_outside_trusted_local():
    args = argparse.Namespace(ui_url="https://les.example.com", trusted_local=False, admin_key="")

    assert "admin-key" in browser_smoke.validate_args(args)


def test_validate_args_allows_trusted_local_without_key():
    args = argparse.Namespace(ui_url="http://localhost:8051", trusted_local=True, admin_key="")

    assert browser_smoke.validate_args(args) == ""


def test_text_selector_uses_playwright_text_engine():
    assert browser_smoke._text_selector("AI ЧАТ") == "text=AI ЧАТ"


def test_missing_playwright_message_has_run_hint():
    message = browser_smoke._missing_playwright_message(ModuleNotFoundError("playwright"))

    assert "uv run --with playwright" in message
