from proxy.services.tool_harness_service import ToolHarness
from proxy.services import web_search_service
from proxy.services.web_search_service import parse_search_results


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

    def fake_search(query, *, limit):
        observed.update(query=query, limit=limit)
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

    assert observed == {"query": "цена цемента", "limit": 4}
    assert result["status"] == "ok"
    assert result["execution"]["code"] == "TOOL_OK"
    assert len(result["result"]["results"]) == 4
