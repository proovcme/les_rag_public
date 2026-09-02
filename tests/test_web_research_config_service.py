from proxy.services.web_research_config_service import (
    WebResearchConfig,
    capture_web_research_config,
    probe_web_research_services,
    public_web_research_config,
    web_research_status,
)


WEB_KEYS = (
    "LES_WEB_SEARCH_MODE",
    "LES_SEARXNG_URL",
    "LES_CRAWL4AI_URL",
    "LES_CRAWL4AI_TOKEN",
)


def test_default_web_research_config_is_simple(monkeypatch):
    for key in WEB_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = capture_web_research_config()

    assert config.mode == "simple"
    assert config.searxng_url == ""
    assert config.crawl4ai_url == ""
    assert config.crawl4ai_token == ""


def test_public_config_masks_crawl_token(monkeypatch):
    monkeypatch.setenv("LES_WEB_SEARCH_MODE", "extended")
    monkeypatch.setenv("LES_CRAWL4AI_TOKEN", "secret-token")

    payload = public_web_research_config(capture_web_research_config())

    assert payload["mode"] == "extended"
    assert payload["crawl4ai_token_set"] is True
    assert "secret-token" not in repr(payload)


def test_invalid_mode_falls_back_to_simple_without_hidden_provider(monkeypatch):
    monkeypatch.setenv("LES_WEB_SEARCH_MODE", "unexpected")

    config = capture_web_research_config()

    assert config.mode == "simple"


def test_status_is_local_only_and_reports_configuration():
    config = WebResearchConfig(
        mode="extended",
        searxng_url="http://search.local",
        crawl4ai_url="http://reader.local",
        crawl4ai_token="secret",
    )

    payload = web_research_status(config)

    assert payload["services"] == {
        "simple": {"status": "available", "provider": "duckduckgo"},
        "searxng": {"status": "configured", "url": "http://search.local"},
        "crawl4ai": {"status": "configured", "url": "http://reader.local"},
    }
    assert "secret" not in repr(payload)


def test_explicit_probe_checks_health_without_submitting_a_crawl():
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class Client:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, **kwargs):
            calls.append(("get", url, kwargs))
            return Response()

        def post(self, *_args, **_kwargs):
            raise AssertionError("probe must never submit a crawl")

    config = WebResearchConfig(
        mode="extended",
        searxng_url="http://search.local",
        crawl4ai_url="http://reader.local",
        crawl4ai_token="secret",
    )

    payload = probe_web_research_services(config, client_factory=Client)

    assert payload["services"]["searxng"]["status"] == "ok"
    assert payload["services"]["crawl4ai"]["status"] == "ok"
    get_calls = [call for call in calls if call[0] == "get"]
    assert get_calls == [
        (
            "get",
            "http://search.local/search",
            {"params": {"q": "LES health", "format": "json", "language": "ru"}},
        ),
        ("get", "http://reader.local/health", {"headers": {"Authorization": "Bearer secret"}}),
    ]
