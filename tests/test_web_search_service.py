from proxy.services.tool_harness_service import ToolHarness
from proxy.services import web_search_service
from proxy.services.web_research_config_service import WebResearchConfig
from proxy.services.web_search_service import parse_search_results, parse_searxng_results


HTML = """
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fdoc">Документ</a>
  <a class="result__snippet">Короткое описание результата.</a>
</div>
"""


def test_web_search_parser_returns_direct_bounded_sources():
    results = parse_search_results(HTML, limit=1)

    assert results == [
        {
            "title": "Документ",
            "snippet": "Короткое описание результата.",
            "url": "https://example.org/doc",
            "domain": "example.org",
        }
    ]


def test_simple_mode_keeps_current_duckduckgo_request_and_result(monkeypatch):
    calls = []

    class Response:
        text = HTML

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, params):
            calls.append((url, params))
            return Response()

    monkeypatch.setenv("LES_WEB_SEARCH_MODE", "simple")
    monkeypatch.setattr(web_search_service.httpx, "Client", lambda **_kwargs: Client())

    result = web_search_service.search_web("цена цемента", limit=4)

    assert calls == [
        (
            "https://html.duckduckgo.com/html/",
            {"q": "цена цемента", "kl": "ru-ru"},
        )
    ]
    assert [row["url"] for row in result["results"]] == ["https://example.org/doc"]
    assert result["requested_mode"] == "simple"
    assert result["effective_mode"] == "simple"
    assert result["degraded"] is False


def test_web_search_does_not_invoke_page_reader(monkeypatch):
    monkeypatch.setattr(
        web_search_service,
        "search_web",
        lambda query, *, limit: {
            "status": "ok",
            "query": query,
            "results": [],
            "missing": [],
            "requested_mode": "simple",
            "effective_mode": "simple",
            "degraded": False,
        },
    )
    monkeypatch.setattr(
        web_search_service,
        "read_web_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reader called")),
        raising=False,
    )

    result = ToolHarness().call("web_search", {"q": "арматура А500С", "limit": 4})

    assert result["tool"] == "web_search"


def test_parse_searxng_results_preserves_order_and_direct_urls():
    payload = {
        "results": [
            {
                "title": "Поставщик",
                "content": "Цена 600 ₽",
                "url": "https://shop.example/cement",
            },
            {
                "title": "Каталог",
                "content": "Арматура",
                "url": "https://metal.example/a500c",
            },
        ]
    }

    rows = parse_searxng_results(payload, limit=4)

    assert rows == [
        {
            "title": "Поставщик",
            "snippet": "Цена 600 ₽",
            "url": "https://shop.example/cement",
            "domain": "shop.example",
        },
        {
            "title": "Каталог",
            "snippet": "Арматура",
            "url": "https://metal.example/a500c",
            "domain": "metal.example",
        },
    ]


def test_extended_search_uses_searxng_without_touching_query():
    calls = []

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "results": [
                    {
                        "title": "Каталог",
                        "content": "Гипсокартон 12,5 мм",
                        "url": "https://public.example/gkl",
                    }
                ]
            }

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, params):
            calls.append((url, params))
            return Response()

    query = "гипсокартон 12,5 мм цена"
    config = WebResearchConfig("extended", "http://127.0.0.1:8888", "", "")

    result = web_search_service.search_web(
        query,
        limit=4,
        config=config,
        client_factory=lambda **_kwargs: Client(),
    )

    assert calls == [
        (
            "http://127.0.0.1:8888/search",
            {"q": query, "format": "json", "language": "ru"},
        )
    ]
    assert result["provider"] == "searxng"
    assert result["effective_mode"] == "extended"
    assert result["degraded"] is False


def test_extended_failure_falls_back_once_with_unchanged_query():
    calls = []

    class Response:
        text = HTML

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, *, params):
            calls.append((url, params))
            if url.endswith("/search"):
                raise web_search_service.httpx.ConnectError("offline")
            return Response()

    query = "цемент М500 50 кг цена"
    config = WebResearchConfig("extended", "http://127.0.0.1:8888", "", "")

    result = web_search_service.search_web(
        query,
        limit=4,
        config=config,
        client_factory=lambda **_kwargs: Client(),
    )

    assert calls == [
        (
            "http://127.0.0.1:8888/search",
            {"q": query, "format": "json", "language": "ru"},
        ),
        (
            "https://html.duckduckgo.com/html/",
            {"q": query, "kl": "ru-ru"},
        ),
    ]
    assert result["provider"] == "duckduckgo"
    assert result["effective_mode"] == "simple"
    assert result["degraded"] is True
    assert result["fallback_reason"] == (
        "Расширенный поиск недоступен, использован резервный простой."
    )


def test_agent_shortlist_exposes_web_and_read_only_filesystem_tools():
    payload = ToolHarness().shortlist("агент найди в интернете и на компьютере", mode="agent", limit=20)
    names = {tool["name"] for tool in payload["tools"]}

    assert "web_search" in names
    assert "filesystem_search" in names
    registry = ToolHarness().registry()
    web = next(tool for tool in registry["tools"] if tool["name"] == "web_search")
    assert web["side_effects"] == "none"
    assert web["approval_required"] is False


def test_web_tool_bounds_model_requested_results_to_its_result_budget(monkeypatch):
    observed = {}

    def fake_search(query, *, limit, config):
        observed.update(query=query, limit=limit, mode=config.mode)
        return {
            "status": "ok",
            "query": query,
            "results": [
                {
                    "title": f"Источник {index}",
                    "snippet": "Цена указана на странице продавца.",
                    "url": f"https://example.org/{index}",
                    "domain": "example.org",
                }
                for index in range(limit)
            ],
            "missing": [],
        }

    monkeypatch.setattr(web_search_service, "search_web", fake_search)

    result = ToolHarness().call("web_search", {"q": "цена цемента", "limit": 10})

    assert observed == {"query": "цена цемента", "limit": 4, "mode": "simple"}
    assert result["status"] == "ok"
    assert result["execution"]["code"] == "TOOL_OK"
    assert len(result["result"]["results"]) == 4
