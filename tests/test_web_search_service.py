from proxy.services.tool_harness_service import ToolHarness
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
