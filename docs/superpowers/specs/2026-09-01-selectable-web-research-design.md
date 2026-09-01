# Selectable Web Research Design

## Status

Approved direction: LES offers a reliable built-in simple web search and an
optional extended SearXNG + Crawl4AI path. The operator chooses the primary
mode explicitly. The simple path remains the default and the visible fallback.

## Goal

Give the model a dependable public-web research surface without turning LES
code into a second researcher. The model formulates every query, chooses every
page to read, decides when evidence is sufficient and authors the final answer.
LES exposes bounded tools, validates transport and provenance, and reports
degradation without rewriting the model's result.

## Non-goals

- Do not change local dataset RAG, Qdrant retrieval, estimating workflows,
  workbook generation or `proxy/smeta_core/**`.
- Do not crawl every search hit automatically.
- Do not rank, select or summarize pages in application code.
- Do not bundle SearXNG, Crawl4AI, Chromium or Docker into the Windows
  installer.
- Do not add a hidden provider override or silently claim that fallback output
  came from the selected primary mode.
- Do not add a second model turn outside the existing model-owned research
  loop.

## User-visible modes

The configuration surface provides one selector under
`Конфигурация → Инструменты → Веб-поиск`:

1. `Простой` — the current bounded DuckDuckGo HTML adapter. It returns direct
   URLs, titles and snippets and requires no external component.
2. `Расширенный` — SearXNG supplies search results and Crawl4AI can read pages
   selected by the model.

`Простой` is the product default. Changing the selection affects new requests;
an in-flight research loop retains the effective mode captured at request
start.

The same panel shows:

- selected mode;
- effective mode;
- SearXNG and Crawl4AI endpoint values and their configuration source;
- independent health badges for search and page reading;
- whether a restart is required;
- the last visible fallback reason without raw exception text.

The panel reuses `select_field`, `text_field`, `panel`, `section_heading`,
`status_badge` and `render_feedback_state`. It introduces no new visual
primitive. Async health changes use one contextual status message and do not
move keyboard focus.

## Architecture

### Provider-neutral search boundary

`web_search_service` becomes a provider-neutral facade with two adapters:

- `DuckDuckGoSearchAdapter` parses the existing HTML response;
- `SearxngSearchAdapter` calls the configured `/search` endpoint with
  `format=json` and normalizes results into the existing title/snippet/direct
  URL shape.

The public `web_search` tool name and model-facing purpose remain stable. The
tool result adds transport provenance:

- `requested_mode`;
- `effective_mode`;
- `provider`;
- `degraded`;
- `fallback_reason` when applicable.

One call remains bounded to four complete results so the trusted result
envelope stays within its registered budget.

### Separate model-selected page reader

A new read-only tool, `web_read`, accepts exactly one public HTTP(S) URL and a
bounded character limit. In extended mode it asks the configured Crawl4AI
service for readable page content and returns:

- canonical requested URL and final source URL when the service provides it;
- page title;
- bounded Markdown/text;
- truncation state;
- retrieval timestamp;
- warnings and missing reasons;
- source provenance.

`web_read` is not invoked by `web_search`, the chat router or a keyword rule.
Only the model can select a returned URL and request the read. Multiple pages
therefore consume the existing global model research call budget.

The tool is model-visible when the effective profile permits web research and
the selected mode is `extended`. Runtime health does not silently remove it:
an absent reader returns an honest `missing` packet. Existing user profiles
that explicitly contain `web_search` receive `web_read` through one idempotent, versioned
capability migration. Profiles that do not permit `web_search` remain
unchanged. The restrictive Qwen shortlist preserves both web tools when they
are permitted; neither tool is forced or auto-called.

### Explicit fallback

When `Расширенный` is selected and SearXNG is unavailable or its request fails,
the same model-authored query is sent once to the simple adapter. The returned
tool packet is marked `degraded=true`, `effective_mode=simple`, and includes a
human-readable fallback reason. Trace and GUI state say:

`Расширенный поиск недоступен, использован резервный простой.`

Fallback does not create another model step and does not change the query.

If Crawl4AI is unavailable, `web_read` returns `missing` with a clear warning.
LES does not replace full-page evidence with a snippet while claiming the page
was read. The model may continue with search snippets, choose another source or
state that the full page could not be inspected.

### Runtime configuration

The GUI-first runtime registry owns three non-secret factors and one optional
secret:

- `LES_WEB_SEARCH_MODE=simple|extended`, default `simple`;
- `LES_SEARXNG_URL`, empty by default;
- `LES_CRAWL4AI_URL`, empty by default;
- `LES_CRAWL4AI_TOKEN`, empty by default and always masked in API/UI output.

Both endpoint values accept only HTTP(S). They are ordinary editable external
service settings, not `Danger` actions. They show effective value and source.
All four factors apply to the next request without a process restart; an
in-flight loop retains its captured values. The runtime registry updates the
process value and recoverable dotenv copy atomically, and GUI/API both report
`restart_required=false`. No unregistered env factor is allowed.

External services remain user-managed, like the other LES providers. Their
absence never prevents the LES core, local RAG or simple web search from
starting.

## Security boundary

Configured SearXNG and Crawl4AI service endpoints may be loopback or an
operator-owned private-network address. URLs handed to `web_read` are a
different trust class and must be public destinations.

Before sending a page URL to Crawl4AI, LES:

- permits only `http` and `https`;
- rejects embedded credentials and malformed hosts;
- resolves the host and rejects loopback, private, link-local, multicast,
  unspecified and metadata-service addresses;
- rejects `file:`, `data:`, `javascript:` and other schemes;
- applies the same rule after any final URL reported by the reader;
- never sends Crawl4AI hooks, executable JavaScript or arbitrary crawler
  configuration supplied by the model;
- limits one read by deadline, response bytes and returned characters.

The deployment documentation requires Crawl4AI 0.8.5 or newer, keeps hooks
disabled and recommends network egress controls for the sidecar. The adapter
sends only LES-owned fixed crawl options and an optional masked bearer token;
it never forwards model-authored crawler configuration. LES does not
accept a Crawl4AI response as trustworthy merely because the HTTP request
succeeded.

## Failure semantics

All failures remain structured tool results:

- `ok` — usable search results or page content;
- `missing` — no results, page content unavailable or extended reader absent;
- `error` — invalid provider response, unsafe URL, timeout or transport error.

No broad exception swallowing is added. Operator-facing text is Russian;
technical error codes and trace remain available under diagnostics. The final
chat answer is the exact model-authored answer and is never post-processed to
insert prices, citations or conclusions.

## Data and provenance

Search results retain direct URL, domain, title and snippet. Page reads retain
the exact source URL and retrieval timestamp. The answer source map can display
both search-result and read-page sources without presenting a snippet as a
verified page fact.

No crawled page is indexed into a user dataset as part of this feature. Search
and page content are request-scoped evidence only; persistent web ingestion is
a separate future design.

## Packaging and deployment

The LES code uses the existing HTTP client stack and adds no Python package.
SearXNG, Crawl4AI, Chromium images and model weights are not copied into the
application tree or release artifact. The Windows installer therefore has no
material size increase from this feature.

Documentation provides example external service endpoints and health checks,
but LES neither installs nor starts those services. The simple mode remains a
complete rollback: selecting it removes both extended services from the live
request path without changing application files.

## Test strategy

Implementation follows test-first development. Required offline proof:

1. SearXNG JSON normalization preserves direct URLs, snippets and ordering.
2. Search result and trusted-executor budgets stay bounded when a model asks
   for more results.
3. `simple` never calls SearXNG or Crawl4AI.
4. Healthy `extended` search calls SearXNG and reports it as effective.
5. Failed extended search calls the simple adapter once with the unchanged
   model query and reports visible degradation.
6. `web_search` never calls `web_read`.
7. `web_read` reads exactly the model-selected URL and returns bounded content
   with provenance.
8. Unsafe schemes, private destinations, DNS rebinding evidence, oversized
   bodies, redirects/final URLs and timeouts fail closed.
9. Crawl4AI absence returns honest `missing`, not fabricated page content.
10. Existing profiles with `web_search` receive the paired reader exactly
    once; profiles without web access do not change.
11. Runtime factors appear in the GUI-first registry with the same effective
    values, sources and hot-apply semantics used by execution; the Crawl4AI
    token never leaves the masked secret boundary.
12. The configuration UI uses shared primitives, remains keyboard-accessible,
    has no horizontal overflow at 390 px and announces health/fallback status.
13. The model-owned loop can alternate search and page reads while preserving
    the global call/result budgets and the final answer verbatim.
14. Existing DuckDuckGo tests, tool-contract tests, local RAG tests and
    workbook regressions remain green.

Canonical gates remain `make verify` and `make test`.

## Installed live acceptance

The feature is not complete until the exact installed Windows runtime proves
all of these scenarios:

1. In `Простой`, ask the model for current prices of several ordinary building
   materials. Verify model-authored queries, direct links, a complete answer
   and a screenshot.
2. In healthy `Расширенный`, use a different question. Verify SearXNG results,
   at least one page explicitly selected and read by the model, direct source
   provenance and a screenshot.
3. Make SearXNG unavailable while `Расширенный` remains selected. Verify one
   bounded simple fallback, unchanged query and a visible degraded notice.
4. Keep SearXNG healthy and make Crawl4AI unavailable. Verify search still
   works and page reading is honestly reported missing.
5. Submit a URL resolving to loopback/private/link-local space and verify that
   no crawl request is issued.
6. Verify installed `/api/version`, proxy/UI health, local dataset RAG and the
   existing workbook path after the web scenarios.

Acceptance records selected/effective mode, tool calls, source counts,
fallback reason, elapsed time and final answer without editing it.

## Rollback

Operational rollback is immediate: choose `Простой`. Code rollback uses the
normal transactional patch backup. Since the change adds no data migration,
index mutation or bundled service, rollback does not touch user datasets,
Qdrant, chat history or workbook artifacts.

## Documentation impact

The implementation updates:

- `docs/ALGO-tool-harness.md` for tool and loop contracts;
- `docs/MODULE_INDEX.md` for code/doc truth;
- `docs/modules/sovushka-uikit.md` for the configuration surface;
- public/operator setup documentation for optional external services;
- `docs/SOFTWARE_VERSIONS.md` and `docs/RELEASE_LEDGER.md` with the release
  version and accepted runtime evidence.

## External references

- SearXNG Search API: <https://docs.searxng.org/dev/search_api.html>
- Crawl4AI documentation: <https://docs.crawl4ai.com/>
