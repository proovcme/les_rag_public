import importlib.util
from pathlib import Path

from proxy.services.etm_price_service import EtmConfig


def _load_smoke():
    spec = importlib.util.spec_from_file_location(
        "etm_live_smoke",
        Path("tools/etm_live_smoke.py"),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_etm_live_smoke_fail_closed_without_credentials(monkeypatch):
    monkeypatch.delenv("LES_ETM_LOGIN", raising=False)
    monkeypatch.delenv("LES_ETM_PASSWORD", raising=False)
    smoke = _load_smoke()

    report = smoke.run_smoke()

    assert report["ok"] is False
    assert report["configured"] is False
    assert report["reason"] == "etm_not_configured"


def test_etm_live_smoke_redacts_credentials_and_session(monkeypatch):
    smoke = _load_smoke()
    monkeypatch.setenv("LES_ETM_LOGIN", "operator-login")
    monkeypatch.setenv("LES_ETM_PASSWORD", "top-secret")

    redacted = smoke._redact({
        "login": "operator-login",
        "password": "top-secret",
        "session": "abc",
        "nested": {"session-id": "abc", "ok": True},
    })

    blob = str(redacted)
    assert "top-secret" not in blob
    assert "operator-login" not in blob
    assert "session" not in redacted
    assert "session-id" not in redacted["nested"]
    assert redacted["nested"]["ok"] is True


def test_etm_live_smoke_reports_browse_and_price(monkeypatch):
    smoke = _load_smoke()
    monkeypatch.setenv("LES_ETM_LOGIN", "operator")
    monkeypatch.setenv("LES_ETM_PASSWORD", "top-secret")

    class _FakeClient:
        def __init__(self, config: EtmConfig) -> None:
            assert config.login == "operator"

        def authenticate(self) -> bool:
            return True

        def browse_goods(self, query, limit=5):
            return {
                "count": 1,
                "candidates": [{
                    "gdscode": query,
                    "name": "Пост кнопочный",
                    "art": "ET054487",
                    "unit": "шт",
                }],
            }

        def collect_quotes(self, items):
            return {
                "found": 1,
                "price_field": "pricewnds",
                "rows": [{"reason": ""}],
                "quotes": [{"price": 122.0, "source_kind": "supplier_api"}],
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "proxy.services.etm_price_service.EtmPriceClient",
        _FakeClient,
    )
    report = smoke.run_smoke(code="9536092")

    assert report["ok"] is True
    assert report["login"] is True
    assert report["browse"]["count"] == 1
    assert report["price"]["found"] is True
    assert report["price"]["source_kind"] == "supplier_api"
    assert "top-secret" not in str(report)
