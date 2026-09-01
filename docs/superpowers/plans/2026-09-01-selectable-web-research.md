# Selectable Web Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicitly selectable simple DuckDuckGo mode and extended SearXNG + model-selected Crawl4AI mode while preserving the currently installed simple search behavior and every non-web LES workflow.

**Architecture:** Keep `web_search` as the stable provider-neutral tool. Capture one immutable web configuration at request start, route search to DuckDuckGo or SearXNG, and add a separate `web_read` tool that reads exactly one model-selected public URL through Crawl4AI. Configuration and health are visible in Sovushka; failures fall back visibly to simple search without changing the model query or final answer.

**Tech Stack:** Python 3.12, FastAPI, httpx, NiceGUI UI kit, pytest, existing LES trusted tool executor; external SearXNG Search API and Crawl4AI REST API; no new package.

**Spec:** `docs/superpowers/specs/2026-09-01-selectable-web-research-design.md`

## Global Constraints

- Preserve the current `simple` DuckDuckGo request and result contract as the default.
- The model authors queries, selects URLs, chooses subsequent calls and writes the final answer.
- Code never crawls all hits, summarizes a page, inserts citations or rewrites the answer.
- Do not modify `proxy/smeta_core/**`, local RAG, Qdrant retrieval, workbook mapping or XLSX calculation.
- No SearXNG, Crawl4AI, Chromium, Docker image or new Python dependency enters the LES installer.
- Runtime factors are GUI-visible, hot-applied to the next request and never silently overridden.
- `web_read` accepts only public HTTP(S) destinations and one URL per model call.
- The installed runtime is not changed until focused tests, `make verify`, `make test`, simple-mode live acceptance and rollback preparation pass.
- Public publication requires a separate explicit owner command.

---

### Task 1: Freeze the working simple-search baseline

**Files:**
- Modify: `tests/test_web_search_service.py`
- Modify: `tests/test_tool_harness_service.py`

**Interfaces:**
- Consumes: current `search_web(query, limit, timeout_sec)` and `ToolHarness.call("web_search", ...)`.
- Produces: regression tests that fail if the existing simple request, four-hit budget, direct URLs or model-owned call behavior changes.

- [ ] **Step 1: Add an exact simple-mode request regression test**

```python
def test_simple_mode_keeps_current_duckduckgo_request_and_result(monkeypatch):
    calls = []

    class Response:
        text = HTML
        def raise_for_status(self):
            return None

    class Client:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def get(self, url, *, params):
            calls.append((url, params))
            return Response()

    monkeypatch.setenv("LES_WEB_SEARCH_MODE", "simple")
    monkeypatch.setattr(web_search_service.httpx, "Client", lambda **_: Client())
    result = web_search_service.search_web("цена цемента", limit=4)

    assert calls == [("https://html.duckduckgo.com/html/", {"q": "цена цемента", "kl": "ru-ru"})]
    assert [row["url"] for row in result["results"]] == ["https://example.org/doc"]
    assert result["requested_mode"] == "simple"
    assert result["effective_mode"] == "simple"
    assert result["degraded"] is False
```

- [ ] **Step 2: Add a no-reader/no-forcing regression test**

```python
def test_web_search_does_not_invoke_page_reader(monkeypatch):
    monkeypatch.setattr(web_search_service, "search_web", lambda query, *, limit: {
        "status": "ok", "query": query, "results": [], "missing": [],
        "requested_mode": "simple", "effective_mode": "simple", "degraded": False,
    })
    monkeypatch.setattr(web_search_service, "read_web_page", lambda *_a, **_k: pytest.fail("reader called"), raising=False)
    result = ToolHarness().call("web_search", {"q": "арматура А500С", "limit": 4})
    assert result["tool"] == "web_search"
```

- [ ] **Step 3: Run the new tests and verify RED only for the new metadata contract**

Run:

```powershell
uv run pytest -q tests/test_web_search_service.py tests/test_tool_harness_service.py --basetemp=.test-tmp/web-baseline
```

Expected: the exact existing request assertions pass; new mode metadata assertions fail because the provider-neutral configuration is not implemented. If the existing request assertions fail, stop and reconcile the baseline before writing production code.

- [ ] **Step 4: Record the pre-change live control without deploying anything**

Run the installed 0.30.42 simple web request used in the previous acceptance and save only its response/trace identifiers under ignored `storage/acceptance/`. Confirm version `0.30.42`, build `682`, commit `ab5146b2fb196878d7e85fe79ab78290974273e6`.

- [ ] **Step 5: Commit the baseline tests**

```powershell
git add tests/test_web_search_service.py tests/test_tool_harness_service.py
git commit -m "test(web): lock simple search baseline"
```

---

### Task 2: Add one immutable, GUI-first web configuration snapshot

**Files:**
- Create: `proxy/services/web_research_config_service.py`
- Modify: `proxy/services/runtime_config_registry_service.py`
- Create: `tests/test_web_research_config_service.py`
- Modify: `tests/test_runtime_config_registry_service.py`

**Interfaces:**
- Produces: `WebResearchConfig`, `capture_web_research_config()`, `public_web_research_config()`, and registered factors `LES_WEB_SEARCH_MODE`, `LES_SEARXNG_URL`, `LES_CRAWL4AI_URL`, `LES_CRAWL4AI_TOKEN`.
- Consumes later: search adapter, page reader, settings status API and chat request capture.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_default_web_research_config_is_simple(monkeypatch):
    WEB_KEYS = (
        "LES_WEB_SEARCH_MODE", "LES_SEARXNG_URL",
        "LES_CRAWL4AI_URL", "LES_CRAWL4AI_TOKEN",
    )
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
    assert payload["crawl4ai_token_set"] is True
    assert "secret-token" not in repr(payload)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
uv run pytest -q tests/test_web_research_config_service.py tests/test_runtime_config_registry_service.py --basetemp=.test-tmp/web-config
```

Expected: import/function failures for the missing configuration service.

- [ ] **Step 3: Implement the immutable configuration contract**

```python
@dataclass(frozen=True)
class WebResearchConfig:
    mode: Literal["simple", "extended"]
    searxng_url: str
    crawl4ai_url: str
    crawl4ai_token: str


def capture_web_research_config(environ: Mapping[str, str] | None = None) -> WebResearchConfig:
    source = os.environ if environ is None else environ
    mode = str(source.get("LES_WEB_SEARCH_MODE", "simple")).strip().casefold()
    if mode not in {"simple", "extended"}:
        mode = "simple"
    return WebResearchConfig(
        mode=cast(Literal["simple", "extended"], mode),
        searxng_url=_normalized_service_url(source.get("LES_SEARXNG_URL", "")),
        crawl4ai_url=_normalized_service_url(source.get("LES_CRAWL4AI_URL", "")),
        crawl4ai_token=str(source.get("LES_CRAWL4AI_TOKEN", "")).strip(),
    )
```

- [ ] **Step 4: Register human labels, URL validation and hot-apply semantics**

Add `_FACTOR_PRESENTATION` entries for the three visible controls and masked token. Validate both URL keys in `update_factors()` using the same HTTP(S) rule as `QDRANT_URL`. Keep all four outside `_RESTART_PREFIXES` and `_RESTART_KEYS`, so the returned rows explicitly carry `restart_required=false`. The existing `TOKEN` secret marker must mask `LES_CRAWL4AI_TOKEN`.

- [ ] **Step 5: Run configuration tests GREEN**

```powershell
uv run pytest -q tests/test_web_research_config_service.py tests/test_runtime_config_registry_service.py --basetemp=.test-tmp/web-config
```

- [ ] **Step 6: Commit configuration boundary**

```powershell
git add proxy/services/web_research_config_service.py proxy/services/runtime_config_registry_service.py tests/test_web_research_config_service.py tests/test_runtime_config_registry_service.py
git commit -m "feat(web): add selectable research configuration"
```

---

### Task 3: Add SearXNG behind the stable `web_search` facade

**Files:**
- Modify: `proxy/services/web_search_service.py`
- Modify: `tests/test_web_search_service.py`

**Interfaces:**
- Consumes: `WebResearchConfig` captured at request start.
- Preserves: `parse_search_results()` and simple DuckDuckGo request.
- Produces: `parse_searxng_results(payload, limit)`, `search_web(..., config=...)`, provider/fallback metadata.

- [ ] **Step 1: Write failing SearXNG normalization and healthy-path tests**

```python
def test_parse_searxng_results_preserves_order_and_direct_urls():
    payload = {"results": [
        {"title": "Поставщик", "content": "Цена 600 ₽", "url": "https://shop.example/cement"},
        {"title": "Каталог", "content": "Арматура", "url": "https://metal.example/a500c"},
    ]}
    rows = parse_searxng_results(payload, limit=4)
    assert rows == [
        {"title": "Поставщик", "snippet": "Цена 600 ₽", "url": "https://shop.example/cement", "domain": "shop.example"},
        {"title": "Каталог", "snippet": "Арматура", "url": "https://metal.example/a500c", "domain": "metal.example"},
    ]


def test_extended_search_uses_searxng_without_touching_query(fake_http):
    config = WebResearchConfig("extended", "http://127.0.0.1:8888", "", "")
    result = search_web("гипсокартон 12,5 мм цена", limit=4, config=config, client_factory=fake_http)
    assert fake_http.request.params["q"] == "гипсокартон 12,5 мм цена"
    assert fake_http.request.params["format"] == "json"
    assert result["provider"] == "searxng"
    assert result["effective_mode"] == "extended"
    assert result["degraded"] is False
```

- [ ] **Step 2: Write the failing visible-fallback test**

```python
def test_extended_failure_falls_back_once_with_unchanged_query(fake_searx_failure, fake_ddg):
    query = "цемент М500 50 кг цена"
    config = WebResearchConfig("extended", "http://127.0.0.1:8888", "", "")
    result = search_web(query, limit=4, config=config, client_factory=combined_client)
    assert fake_searx_failure.queries == [query]
    assert fake_ddg.queries == [query]
    assert result["effective_mode"] == "simple"
    assert result["degraded"] is True
    assert result["fallback_reason"] == "Расширенный поиск недоступен, использован резервный простой."
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest -q tests/test_web_search_service.py --basetemp=.test-tmp/web-search-provider
```

- [ ] **Step 4: Implement the smallest provider routing**

Keep `_search_duckduckgo()` as the existing request body. Add `_search_searxng()` using `GET {base}/search` with `q`, `format=json`, `language=ru` and the existing bounded timeout. Catch only provider parsing/HTTP failures around the extended attempt, then call simple exactly once. Do not catch programming errors or mutate the query.

- [ ] **Step 5: Verify search limits and GREEN**

```powershell
uv run pytest -q tests/test_web_search_service.py tests/test_http_client_policy.py --basetemp=.test-tmp/web-search-provider
```

- [ ] **Step 6: Commit the search provider**

```powershell
git add proxy/services/web_search_service.py tests/test_web_search_service.py
git commit -m "feat(web): add bounded SearXNG provider"
```

---

### Task 4: Add the public-URL Crawl4AI reader

**Files:**
- Create: `proxy/services/web_page_reader_service.py`
- Create: `tests/test_web_page_reader_service.py`

**Interfaces:**
- Produces: `validate_public_web_url()`, `read_web_page(url, max_chars, config, ...)`.
- Consumes later: the `web_read` tool handler.
- Result: `status`, requested/final URL, title, bounded text, truncation, retrieved timestamp, warnings and missing reasons.

- [ ] **Step 1: Write failing unsafe-destination tests**

```python
@pytest.fixture
def public_resolver():
    return lambda host, port, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))
    ]


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://127.0.0.1/admin",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/private",
    "http://[::1]/",
    "https://user:pass@example.com/",
])
def test_reader_rejects_non_public_destinations_before_http(url, no_http, resolver):
    with pytest.raises(UnsafeWebUrl):
        validate_public_web_url(url, resolver=resolver)
    assert no_http.calls == []
```

- [ ] **Step 2: Write failing exact-URL and budget tests**

```python
def test_reader_sends_only_the_model_selected_url_and_fixed_options(fake_crawl4ai, public_resolver):
    selected_url = "https://public.example/material"
    config = WebResearchConfig("extended", "http://127.0.0.1:8888", "http://127.0.0.1:11235", "")
    result = read_web_page(selected_url, max_chars=4000, config=config, resolver=public_resolver, client_factory=fake_crawl4ai)
    assert fake_crawl4ai.urls == [selected_url]
    assert "hooks" not in fake_crawl4ai.payload
    assert "javascript" not in repr(fake_crawl4ai.payload).casefold()
    assert result["text"] == ("Материал " * 1000)[:4000]
    assert result["text_truncated"] is True
    assert result["sources"][0]["url"] == selected_url
```

Define `fake_crawl4ai` in the same test file as a recording context-manager
client. Its `post()` stores the exact JSON body and returns a fixed documented
response containing `{"success": true, "results": [{"url": selected_url,
"title": "Материал", "markdown": {"raw_markdown": "Материал " * 1000}}]}`.
The fixture exposes recorded `urls`, `payload` and request count for assertions.

- [ ] **Step 3: Write failing missing-reader and unsafe-final-URL tests**

Assert an empty/unhealthy Crawl4AI configuration returns `missing`; assert a response reporting a private final URL returns `error` and no page text.

- [ ] **Step 4: Verify RED**

```powershell
uv run pytest -q tests/test_web_page_reader_service.py --basetemp=.test-tmp/web-reader
```

- [ ] **Step 5: Implement URL validation and a fixed Crawl4AI request**

Use `urllib.parse`, `socket.getaddrinfo` and `ipaddress`. Reject every resolved address where `is_global` is false. Send a fixed `/crawl` payload containing one URL, headless browser, non-streaming output and no hooks/LLM extraction. Add `Authorization: Bearer …` only from the masked operator secret. Accept only documented result containers and markdown/text fields; unknown response shapes return `error`.

- [ ] **Step 6: Enforce transport budgets**

Use no redirects when addressing the configured service, a bounded timeout, bounded response bytes and `max_chars` clamped to `4000`. Validate a reported final URL with the same public-destination policy before exposing content.

- [ ] **Step 7: Run GREEN**

```powershell
uv run pytest -q tests/test_web_page_reader_service.py tests/test_model_connection_security_service.py --basetemp=.test-tmp/web-reader
```

- [ ] **Step 8: Commit the reader**

```powershell
git add proxy/services/web_page_reader_service.py tests/test_web_page_reader_service.py
git commit -m "feat(web): add bounded model-selected page reader"
```

---

### Task 5: Expose `web_read` without changing model ownership

**Files:**
- Modify: `proxy/services/tool_harness_service.py`
- Modify: `proxy/services/chat_profile_service.py`
- Modify: `tests/test_web_search_service.py`
- Modify: `tests/test_tool_harness_service.py`
- Modify: `tests/test_tool_registry_service.py`
- Modify: `tests/test_chat_profile_service.py`
- Modify: `tests/test_workbook_tool_contracts.py`

**Interfaces:**
- Produces: registered read-only `web_read` tool with args `url`, `max_chars`.
- Preserves: existing `web_search` name, four-hit budget and Qwen restrictive shortlist.
- Adds: effective paired capability only when an immutable profile already permits `web_search`.

- [ ] **Step 1: Write failing registry and shortlist tests**

```python
def test_agent_shortlist_keeps_both_web_tools_in_model_order():
    allowed = ["filesystem_search", "web_search", "web_read", "filesystem_read_text"]
    result = ToolHarness().shortlist("актуальные цены", mode="agent", allowed_tools=allowed, limit=5)
    assert [item["name"] for item in result["tools"]][:2] == ["web_search", "web_read"]
```

Assert `web_read` has effect `read`, scope `public_web`, required `url`, maximum result budget compatible with a 4000-character page, and `decision_required_from_model=true`.

- [ ] **Step 2: Write failing immutable-profile compatibility tests**

```python
def test_effective_profile_pairs_reader_only_with_explicit_web_search():
    stored = {"mode": "agent", "tools": ["web_search", "filesystem_search"]}
    effective = effective_profile_snapshot(stored)
    assert effective["tools"] == ["web_search", "web_read", "filesystem_search"]
    assert stored["tools"] == ["web_search", "filesystem_search"]


def test_profile_without_web_search_does_not_gain_reader():
    assert effective_profile_snapshot({"mode": "agent", "tools": ["filesystem_search"]})["tools"] == ["filesystem_search"]
```

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest -q tests/test_tool_registry_service.py tests/test_tool_harness_service.py tests/test_chat_profile_service.py tests/test_workbook_tool_contracts.py --basetemp=.test-tmp/web-tools
```

- [ ] **Step 4: Register `web_read` and its handler**

Add required schema mapping `"web_read": ["url"]`, priority immediately after `web_search`, and `_tool_web_read()` that passes exactly `url` and a clamped `max_chars` to `read_web_page()`. Do not call this handler from `_tool_web_search()`.

- [ ] **Step 5: Add the effective paired-capability bridge**

In `effective_profile_snapshot()`, insert `web_read` immediately after `web_search` only when it is absent. Do not update stored `tools_json`, `snapshot_json` or existing session bindings. In the chat trace record `effective_capability_bridges=["paired_web_capability_v1"]` when this bridge changes the effective tool list.

- [ ] **Step 6: Run GREEN and the workbook contract guard**

```powershell
uv run pytest -q tests/test_web_search_service.py tests/test_tool_registry_service.py tests/test_tool_harness_service.py tests/test_chat_profile_service.py tests/test_workbook_tool_contracts.py --basetemp=.test-tmp/web-tools
```

- [ ] **Step 7: Commit the tool boundary**

```powershell
git add proxy/services/tool_harness_service.py proxy/services/chat_profile_service.py tests/test_web_search_service.py tests/test_tool_harness_service.py tests/test_tool_registry_service.py tests/test_chat_profile_service.py tests/test_workbook_tool_contracts.py
git commit -m "feat(agent): expose model-selected web page reads"
```

---

### Task 6: Prove the chat loop does not become an orchestrator

**Files:**
- Modify: `proxy/services/chat_evidence_application_service.py`
- Modify: `tests/test_chat_evidence_application_service.py`

**Interfaces:**
- Consumes: the existing model-owned research loop and effective profile snapshot.
- Produces: request-start config capture and trace fields; no new model turn or automatic tool call.

- [ ] **Step 1: Write a failing multi-round ownership test**

Construct model responses that call `web_search`, then select one returned URL with `web_read`, then return a final plain-text answer. Define `MODEL_FINAL_TEXT` as a literal Russian answer in the test. Assert exact call order, page provenance in `source_map`, and that the visible/stored answers equal the final model text byte-for-byte.

```python
assert selected_tools == ["web_search", "web_read"]
assert executed_urls == ["https://public.example/material"]
assert response["answer"].encode("utf-8") == MODEL_FINAL_TEXT.encode("utf-8")
assert history_rows[0]["answer"].encode("utf-8") == MODEL_FINAL_TEXT.encode("utf-8")
assert response["source_map"][0]["url"] == "https://public.example/material"
```

- [ ] **Step 2: Write a failing no-auto-read test**

Have the model call only `web_search` and then answer. Assert no `web_read` handler invocation, even though results contain four URLs.

- [ ] **Step 3: Write a failing global-budget test**

Have the model alternate search/read beyond `LES_CHAT_TOOL_MAX_CALLS`. Assert the existing global budget stops execution and trace reports `calls_budget`; it must not reset between search and reads.

- [ ] **Step 4: Verify RED**

```powershell
uv run pytest -q tests/test_chat_evidence_application_service.py -k "web_search or web_read or calls_budget" --basetemp=.test-tmp/web-chat
```

- [ ] **Step 5: Add only request-scoped plumbing**

Capture `WebResearchConfig` once before building the runtime tool executor and construct `harness(web_config=captured_config)`. `ToolHarness.__init__()` registers closures for `_tool_web_search(args, config=...)` and `_tool_web_read(args, config=...)`; non-chat callers default to a fresh captured config. Add requested/effective mode, provider, degradation and fallback reason to `retrieval_trace.tool_loop`; do not add selection logic or a second loop.

- [ ] **Step 6: Verify GREEN plus the existing model-result integrity tests**

```powershell
uv run pytest -q tests/test_chat_evidence_application_service.py tests/test_chat_harness_format.py --basetemp=.test-tmp/web-chat
```

- [ ] **Step 7: Commit chat plumbing**

```powershell
git add proxy/services/chat_evidence_application_service.py tests/test_chat_evidence_application_service.py
git commit -m "feat(chat): carry selectable web evidence unchanged"
```

---

### Task 7: Add status API and the Sovushka selector

**Files:**
- Modify: `proxy/services/web_research_config_service.py`
- Modify: `proxy/routers/settings.py`
- Modify: `sovushka/pages/diag.py`
- Modify: `tests/test_web_research_config_service.py`
- Create: `tests/test_web_research_settings.py`
- Modify: `tests/test_diag_platform.py`
- Modify: `tests/test_sovushka_uikit.py`

**Interfaces:**
- Produces: `GET /api/settings/web-research`, `POST /api/settings/web-research/probe` and one configuration panel.
- Reuses: generic guarded runtime-registry update for saving values and shared UI primitives.

- [ ] **Step 1: Write failing status and secret-boundary tests**

```python
def test_web_research_status_never_returns_token(api, monkeypatch):
    monkeypatch.setenv("LES_CRAWL4AI_TOKEN", "secret-token")
    payload = api.get("/api/settings/web-research").json()
    assert payload["config"]["crawl4ai_token_set"] is True
    assert "secret-token" not in repr(payload)


def test_probe_reports_search_and_reader_independently(api):
    payload = api.post("/api/settings/web-research/probe").json()
    assert set(payload["services"]) == {"simple", "searxng", "crawl4ai"}
```

- [ ] **Step 2: Write failing UI contract tests**

Assert the page contains Russian labels `Веб-поиск`, `Простой`, `Расширенный`, `Фактически используется`, `Проверить веб-поиск`, uses `select_field`, `text_field`, `status_badge`, `render_feedback_state`, and does not add page-local color/typography styles for this panel.

- [ ] **Step 3: Verify RED**

```powershell
uv run pytest -q tests/test_web_research_settings.py tests/test_diag_platform.py tests/test_sovushka_uikit.py --basetemp=.test-tmp/web-ui
```

- [ ] **Step 4: Implement bounded status/probe service**

Return current selected/effective mode, endpoint presence, masked token state, last observed fallback and separate short-timeout health states. A normal GET must not start a crawl. The explicit probe may call SearXNG search health and Crawl4AI `/health`, but it must never submit a page URL.

- [ ] **Step 5: Build the panel with existing primitives**

Place it before `Все параметры среды`. Save mode/URLs/token through `/api/settings/runtime-registry`; reload the panel after success. Announce one contextual loading/success/error state without moving focus. At 390 px, fields stack vertically and no new permanent sidebar appears.

- [ ] **Step 6: Run UI tests GREEN**

```powershell
uv run pytest -q tests/test_web_research_config_service.py tests/test_web_research_settings.py tests/test_diag_platform.py tests/test_sovushka_uikit.py tests/test_static_assets.py --basetemp=.test-tmp/web-ui
```

- [ ] **Step 7: Commit API and UI**

```powershell
git add proxy/services/web_research_config_service.py proxy/routers/settings.py sovushka/pages/diag.py tests/test_web_research_config_service.py tests/test_web_research_settings.py tests/test_diag_platform.py tests/test_sovushka_uikit.py
git commit -m "feat(ui): configure simple and extended web search"
```

---

### Task 8: Add a real acceptance probe and operational documentation

**Files:**
- Create: `tools/web_research_live_acceptance.py`
- Create: `tests/test_web_research_live_acceptance.py`
- Modify: `docs/ALGO-tool-harness.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/public/windows-troubleshooting.md`
- Modify: `docs/TEST_INVENTORY.md`

**Interfaces:**
- Produces: a read-only acceptance CLI that verifies actual chat trace and sources but never changes configuration or manufactures a passing result.

- [ ] **Step 1: Write failing receipt-validation tests**

```python
def test_acceptance_rejects_search_only_when_extended_read_is_required():
    with pytest.raises(AcceptanceFailure, match="web_read"):
        validate_receipt(EXTENDED_RESPONSE_WITH_ONLY_SEARCH, expected_mode="extended", require_read=True)


def test_acceptance_requires_visible_degradation_for_fallback():
    with pytest.raises(AcceptanceFailure, match="fallback_reason"):
        validate_receipt(FALLBACK_RESPONSE_WITHOUT_REASON, expected_mode="simple", require_degraded=True)
```

- [ ] **Step 2: Verify RED, then implement the read-only CLI**

The CLI accepts proxy URL, mode expectation, prompt, `--require-read` and `--require-degraded`. It posts one chat request, validates `retrieval_trace.tool_loop`, counts direct web sources, hashes the unchanged answer and writes a JSON receipt under an explicitly supplied output directory. It never edits `.env`, profiles or runtime services.

- [ ] **Step 3: Run probe tests GREEN**

```powershell
uv run pytest -q tests/test_web_research_live_acceptance.py --basetemp=.test-tmp/web-acceptance
```

- [ ] **Step 4: Update canonical documentation in the same change**

Document both tools, provider choice, visible fallback, optional external-service setup, Crawl4AI `>=0.8.5`, masked token, no-bundle rule, security boundary and exact live commands. Mark the module row code/doc status accurately.

- [ ] **Step 5: Commit acceptance and docs**

```powershell
git add tools/web_research_live_acceptance.py tests/test_web_research_live_acceptance.py docs/ALGO-tool-harness.md docs/MODULE_INDEX.md docs/modules/sovushka-uikit.md docs/public/windows-troubleshooting.md docs/TEST_INVENTORY.md
git commit -m "docs(web): add live selectable-search acceptance"
```

---

### Task 9: Version, structural verification and development live acceptance

**Files:**
- Modify: `config/version.json`
- Modify: files updated by `tools/sync_version_contract.py`
- Modify: `docs/SOFTWARE_VERSIONS.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: generated runtime map files from `tools/code_runtime_map.py`

**Interfaces:**
- Produces: product version `0.31.0`, build `683`, synchronized desktop/runtime identity and an unreleased ledger entry.

- [ ] **Step 1: Bump and synchronize version**

Set `product_version` to `0.31.0`, `build_number` to `683` and `desktop_version` to `5.1.683` in `config/version.json`; update every generated consumer through the repository synchronizers rather than editing those consumers manually.

```powershell
uv run python tools/sync_version_contract.py
uv run python tools/code_runtime_map.py
```

- [ ] **Step 2: Run the focused web and UI suite**

```powershell
uv run pytest -q tests/test_web_search_service.py tests/test_web_page_reader_service.py tests/test_web_research_config_service.py tests/test_web_research_settings.py tests/test_tool_harness_service.py tests/test_tool_registry_service.py tests/test_chat_profile_service.py tests/test_chat_evidence_application_service.py tests/test_sovushka_uikit.py --basetemp=.test-tmp/web-focused
```

- [ ] **Step 3: Run architecture and canonical gates**

```powershell
make architecture-gate
make verify
make test
```

Expected: no architecture rule, collected test or behavior test failure. Do not weaken, skip or remove a failing gate.

- [ ] **Step 4: Prove simple mode first in the isolated dev proxy**

Use a new building-material prompt, require direct sources, and compare requested/effective mode, query text, source count and answer preservation against the baseline. If simple differs unexpectedly, stop before extended testing.

- [ ] **Step 5: Prove healthy extended mode**

Point the dev proxy at operator-owned SearXNG and Crawl4AI services. Use a different prompt. Require model-authored search calls, at least one model-selected `web_read`, direct sources and a complete unchanged answer.

- [ ] **Step 6: Prove both degradation paths**

Make only SearXNG unavailable and verify one visible simple fallback with the unchanged query. Restore it, make only Crawl4AI unavailable and verify search remains usable while the reader returns honest `missing`.

- [ ] **Step 7: Re-check non-web invariants**

Run one ordinary local-dataset RAG question and the existing workbook regression tests. Confirm no `proxy/smeta_core/**` diff and no index/data mutation.

- [ ] **Step 8: Commit versioned candidate**

```powershell
git add config/version.json docs/SOFTWARE_VERSIONS.md docs/RELEASE_LEDGER.md
git add pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json
git add desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json
git add docs/VERSIONING.md docs/CODE_RUNTIME_MAP.md docs/generated/code_runtime_map.json
git commit -m "chore(release): prepare selectable web research candidate"
```

Before committing, compare `git status --short` with this explicit list and do not stage unrelated working-tree changes.

---

### Task 10: Installed Windows acceptance without public publication

**Files:**
- No source changes unless installed acceptance finds a reproducible defect; any defect starts a new failing-test cycle in the owning task.
- Outputs: ignored receipts and screenshots under `storage/acceptance/web-research-0.31.0/`.

**Interfaces:**
- Consumes: exact committed patch candidate and existing transactional Windows updater.
- Produces: installed evidence or a rollback; it does not create a public release.

- [ ] **Step 1: Verify patch scope before installation**

Run the patch classifier/dry-run against installed `0.30.42/682`. Require no data, Qdrant, smeta-core, workbook-core, bootstrap or installer payload changes. Prepare the exact transactional backup path.

- [ ] **Step 2: Install the exact candidate transactionally**

Use the existing checked-in updater path. Verify target commit, version/build, replaced-file list, Qdrant readiness, local RAG readiness and `user_data_untouched=true`. Roll back immediately if any invariant fails.

- [ ] **Step 3: Run installed simple acceptance first**

Select `Простой` in Sovushka. Run a fresh materials query through the actual UI/API. Save trace receipt and screenshot showing `0.31.0 · 683`, simple effective mode, direct sources and complete answer.

- [ ] **Step 4: Run installed extended acceptance**

Select `Расширенный`, probe both services, run a different query and save a screenshot showing successful SearXNG search and at least one model-selected Crawl4AI page read.

- [ ] **Step 5: Run installed fallback and isolation scenarios**

Verify visible SearXNG fallback, honest Crawl4AI missing state, one ordinary non-web RAG query and one XLSX build using existing regression fixtures. Confirm formulas/artifact still open and no web tool is called in non-web scenarios.

- [ ] **Step 6: Decide candidate status**

If every receipt is green, mark the ledger candidate `installed-accepted, unpublished` and retain rollback. If any scenario fails, roll back to `0.30.42/682`, preserve the failure receipt, add a reproducing test and return to the owning task. Do not publish from this plan.

---

## Final review checklist

- [ ] `git diff --check` clean.
- [ ] No changes under `proxy/smeta_core/**`, user data, Qdrant data or workbook calculation code.
- [ ] Simple mode remains default and passes exact request/result regression.
- [ ] Extended mode requires explicit selection and never auto-crawls search hits.
- [ ] Model final answer is preserved exactly in response and history.
- [ ] Secret token is masked in every API/UI/trace surface.
- [ ] Unsafe URL tests fail closed before Crawl4AI receives a request.
- [ ] GUI shows selected/effective mode, health and visible fallback using shared primitives.
- [ ] Focused tests, architecture gate, `make verify` and `make test` pass.
- [ ] Dev live acceptance passes before installed mutation.
- [ ] Installed simple, extended, fallback, RAG and XLSX scenarios pass with screenshots.
- [ ] Public release remains unperformed until the owner explicitly requests it.
