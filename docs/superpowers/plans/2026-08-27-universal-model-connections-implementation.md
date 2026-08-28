# Universal Model Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace provider-name branches in ordinary LES chat with an immutable global registry of safe, capability-verified OpenAI-compatible model connections.

**Architecture:** SQLite stores append-only connection revisions, capability snapshots and explicit answer/embeddings/fallback bindings. A resolver combines the exact revision, secret reference, verified endpoint and ContextGovernor capacity into one immutable runtime object consumed by a provider-neutral transport; engine-specific management stays behind a separate extension registry.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, httpx, NiceGUI, pytest, existing LES ContextGovernor/runtime registry/version tooling.

**Spec:** `docs/superpowers/specs/2026-08-27-universal-model-connections-design.md`

## Global Constraints

- Execute in a fresh linked worktree created with `superpowers:using-git-worktrees` from the plan commit; the current workbook RED tests and `uv.lock` modification remain untouched in their existing worktree.
- Do not modify `proxy/smeta_core/**`, estimator algorithms, smeta mappings, norms, calculations, forms or smeta product defaults.
- Do not replace, clear or bypass notebook memory, typed advisory-memory projection, ContextGovernor, Tool Registry, Capability Broker or Trusted Executor.
- Ordinary inference uses OpenAI-compatible Chat Completions; Responses and server-owned tools are optional and never silently selected.
- Each model turn still exposes at most one canonical tool call; capability probes and `shadow` mode add zero model calls to a user request. Shadow sends no second model request.
- Secrets are never stored in SQLite, returned by APIs, printed in logs or included in diagnostics. Only `secret_ref` and `configured|missing|not_required` are public.
- Local HTTP is allowed only under the explicit locality policy. Remote connections require HTTPS. Redirects are disabled and connected peers are revalidated.
- Fallback uses only the exact connection bound to `local_fallback`; no model list, provider scan or implicit MLX switch remains in ordinary chat.
- Existing provider environment values remain rollback inputs and are not deleted, overwritten or copied into SQLite.
- Do not add dependencies. Use the bundled `httpx`, SQLite and standard-library URL/IP tools.
- Before Task 9, read `skills/sovushka-ui/SKILL.md` and `docs/modules/sovushka-uikit.md`; reuse existing components and tokens.
- Every implementation task increments `build_number` once, changes `desktop_version` to `5.1.<build>`, runs `uv run python tools/sync_version_contract.py`, updates `docs/RELEASE_LEDGER.md`, and commits only that task's files.
- Use `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-N tests/test_name.py` on Windows, with the task number and exact test file substituted.
- Live engines and services are not restarted during Tasks 1-10. Task 11 creates the owner-gated live acceptance command but does not promote, deploy or publish.

## File Structure

- `proxy/services/model_connection_contracts.py` — immutable enums and value objects shared by store, resolver, transport and API.
- `proxy/services/model_connection_registry_service.py` — append-only SQLite revisions, capability snapshots and atomic role bindings.
- `proxy/services/model_connection_security_service.py` — URL canonicalization, locality/IP policy and connected-peer checks.
- `proxy/services/model_secret_service.py` — environment-backed secret references and masked write-only replacement.
- `proxy/services/model_capability_service.py` — bounded explicit probes and evidence snapshots.
- `proxy/services/model_connection_resolver_service.py` — legacy import, role resolution, rollout comparison and explicit fallback selection.
- `proxy/services/openai_compatible_transport_service.py` — the only ordinary chat/embeddings OpenAI-compatible HTTP transport.
- `proxy/services/model_engine_extension_service.py` — isolated optional engine-management registry.
- `proxy/routers/model_connections.py` — authenticated safe CRUD, test, role-binding and extension endpoints.
- `sovushka/pages/model_connections.py` — administrator-facing connection registry.
- `tools/model_connection_live_acceptance.py` — opt-in exact-engine acceptance receipt generator.
- Focused tests mirror each service and router; `tests/test_architecture_gate.py` prevents provider branches from returning.

---

### Task 1: Immutable connection revisions and role bindings

**Build:** 604

**Files:**
- Create: `proxy/services/model_connection_contracts.py`
- Create: `proxy/services/model_connection_registry_service.py`
- Create: `tests/test_model_connection_registry_service.py`
- Modify: `config/version.json`
- Modify by sync: `pyproject.toml`, `desktop/tauri/package.json`, `desktop/tauri/package-lock.json`, `desktop/tauri/src-tauri/Cargo.toml`, `desktop/tauri/src-tauri/Cargo.lock`, `desktop/tauri/src-tauri/tauri.conf.json`, `docs/SOFTWARE_VERSIONS.md`, `docs/VERSIONING.md`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `backend.rag_config.rag_meta_db_path() -> str`.
- Produces: `ConnectionLocality`, `ConnectionRole`, `CapabilityName`, `CapabilityState`, `ModelConnectionRevision`, `CapabilitySnapshot`, `RoleBinding`, and `ModelConnectionRegistry` methods used by every later task.

- [ ] **Step 1: Write failing immutable-store tests**

```python
def test_edit_creates_revision_and_keeps_old_snapshot(tmp_path):
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    first = registry.create_connection(
        display_name="Local Qwen",
        base_url="http://127.0.0.1:1919/v1",
        model_id="qwen3.6:35b",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=30_000,
        secret_ref=None,
        extension_type="freetoken",
        actor="admin:test",
    )
    second = registry.revise_connection(
        first.connection_id,
        expected_revision_id=first.revision_id,
        model_id="qwen3.6:35b-fixed",
        actor="admin:test",
    )
    assert second.revision_no == 2
    assert registry.get_revision(first.revision_id).model_id == "qwen3.6:35b"
    assert registry.get_connection(first.connection_id).revision_id == second.revision_id


def test_role_binding_is_atomic_and_points_to_exact_revision(tmp_path):
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = make_connection(registry)
    binding = registry.bind_role(
        ConnectionRole.ANSWER,
        revision.revision_id,
        expected_binding_revision=None,
        actor="admin:test",
    )
    assert binding.connection_revision_id == revision.revision_id
    assert registry.get_role_binding(ConnectionRole.ANSWER) == binding
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-1 tests/test_model_connection_registry_service.py`

Expected: collection fails because `proxy.services.model_connection_contracts` and `ModelConnectionRegistry` do not exist.

- [ ] **Step 3: Define frozen contracts**

```python
class ConnectionLocality(str, Enum):
    LOOPBACK = "loopback"
    PRIVATE_NETWORK = "private_network"
    REMOTE = "remote"


class ConnectionRole(str, Enum):
    ANSWER = "answer"
    EMBEDDINGS = "embeddings"
    LOCAL_FALLBACK = "local_fallback"


@dataclass(frozen=True)
class ModelConnectionRevision:
    connection_id: str
    revision_id: str
    revision_no: int
    display_name: str
    protocol: str
    base_url: str
    model_id: str
    locality: ConnectionLocality
    requested_context_tokens: int | None
    secret_ref: str | None
    extension_type: str | None
    enabled: bool
    created_at: str
    created_by: str
```

Define `CapabilityName`, `CapabilityState`, `CapabilityObservation`, `CapabilitySnapshot`, `RoleBinding` and immutable `transport_options: Mapping[str, str]` in the same file. `transport_options["max_output_field"]` accepts only `max_tokens` or `max_completion_tokens`. Reject any protocol other than `openai_compatible`; validate non-empty IDs/names/models and positive context values at construction boundaries.

- [ ] **Step 4: Implement append-only SQLite storage**

Create tables `les_model_connection_revisions`, `les_model_connection_heads`, `les_model_capability_snapshots`, `les_model_role_bindings` and `les_model_connection_audit`. Use `BEGIN IMMEDIATE` for compare-and-swap revision and binding updates. `revise_connection()` copies omitted fields from the current revision; `disable_connection()` creates a disabled revision; no update or delete touches an old revision row.

Expose these exact public operations: `ModelConnectionRegistry(db_path: str | Path | None = None)`, `create_connection(display_name, base_url, model_id, locality, requested_context_tokens, secret_ref, extension_type, actor) -> ModelConnectionRevision`, `revise_connection(connection_id, expected_revision_id, actor, **changes) -> ModelConnectionRevision`, `disable_connection(connection_id, expected_revision_id, actor) -> ModelConnectionRevision`, `get_connection(connection_id)`, `get_revision(revision_id)`, `list_connections(include_disabled=False)`, `bind_role(role, connection_revision_id, expected_binding_revision, actor) -> RoleBinding`, `get_role_binding(role)`, `save_capability_snapshot(snapshot, actor)` and `latest_capability_snapshot(connection_revision_id)`. No provider-name field is accepted.

- [ ] **Step 5: Run focused tests**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-1 tests/test_model_connection_registry_service.py`

Expected: all tests pass, including stale compare-and-swap rejection, disabled binding rejection, unique display names and capability round-trip.

- [ ] **Step 6: Update version and ledger, then commit**

Set build 604 in `config/version.json`, run `uv run python tools/sync_version_contract.py`, add the immutable-registry checkpoint to the ledger, then run:

```powershell
git add proxy/services/model_connection_contracts.py proxy/services/model_connection_registry_service.py tests/test_model_connection_registry_service.py config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/RELEASE_LEDGER.md
git commit -m "feat(models): add immutable connection registry"
```

### Task 2: Endpoint policy and secret references

**Build:** 605

**Files:**
- Create: `proxy/services/model_connection_security_service.py`
- Create: `proxy/services/model_secret_service.py`
- Create: `tests/test_model_connection_security_service.py`
- Create: `tests/test_model_secret_service.py`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `ConnectionLocality` from Task 1.
- Produces: `ValidatedEndpoint`, `validate_endpoint()`, `validate_connected_peer()`, `EnvironmentSecretStore`, `SecretValue` and `EnvironmentSecretStore.status()`.

- [ ] **Step 1: Write failing endpoint-policy tests**

```python
@pytest.mark.parametrize("url", [
    "http://user:pass@example.com/v1",
    "https://example.com/v1#fragment",
    "http://169.254.169.254/latest/meta-data",
])
def test_rejects_credentials_fragments_and_metadata(url):
    with pytest.raises(ConnectionSecurityError):
        validate_endpoint(url, ConnectionLocality.REMOTE, resolver=fixed_resolver("169.254.169.254"))


def test_remote_requires_https():
    with pytest.raises(ConnectionSecurityError, match="REMOTE_HTTPS_REQUIRED"):
        validate_endpoint("http://models.example/v1", ConnectionLocality.REMOTE,
                          resolver=fixed_resolver("203.0.113.10"))
```

Also cover loopback HTTP acceptance, private HTTP requiring `allow_private_http=True`, mixed safe/unsafe DNS answers rejection, cloud-metadata and link-local SSRF rejection, query/fragment normalization, response peer mismatch and redirect rejection.

- [ ] **Step 2: Write failing secret tests**

```python
def test_secret_value_never_appears_in_repr_or_status(tmp_path):
    store = EnvironmentSecretStore(tmp_path / ".env", environ={})
    ref = "env:LES_MODEL_CONNECTION_C1_API_KEY"
    store.replace(ref, "top-secret", actor="admin:test")
    value = store.resolve(ref)
    assert value.reveal() == "top-secret"
    assert "top-secret" not in repr(value)
    assert store.status(ref) == "configured"
```

Cover missing refs, invalid namespaces, newline rejection, atomic replacement and redacted audit output.

- [ ] **Step 3: Run both files and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-2 tests/test_model_connection_security_service.py tests/test_model_secret_service.py`

Expected: collection fails for the two missing services.

- [ ] **Step 4: Implement URL and peer validation**

Implement frozen `ValidatedEndpoint(canonical_base_url, locality, host, port, allowed_addresses)`. Expose `validate_endpoint(base_url, locality, resolver=system_resolver, allow_private_http=False) -> ValidatedEndpoint` and `validate_connected_peer(response, endpoint) -> None`.

Reject redirects before reading bodies. For real HTTP transports, extract `server_addr` from `response.extensions["network_stream"]`; fail closed for remote/private endpoints if peer evidence is absent. Test transports pass an explicit peer verifier fixture rather than weakening production checks.

- [ ] **Step 5: Implement environment-backed secret storage**

Accept only refs matching `env:LES_MODEL_CONNECTION_[A-Z0-9_]+_API_KEY` plus a fixed migration allowlist (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `OLLAMA_API_KEY`, `LEMONADE_API_KEY`, `FREETOKEN_API_KEY`). Persist with an atomic same-directory temporary file and replacement. Return `SecretValue` with `repr=False` and a single `reveal()` boundary used only by transport construction.

- [ ] **Step 6: Run focused tests and commit build 605**

Run both test files, then update version surfaces and ledger. Commit:

```powershell
git add proxy/services/model_connection_security_service.py proxy/services/model_secret_service.py tests/test_model_connection_security_service.py tests/test_model_secret_service.py config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/RELEASE_LEDGER.md
git commit -m "feat(models): guard endpoints and secret references"
```

### Task 3: Capability evidence and bounded probes

**Build:** 606

**Files:**
- Create: `proxy/services/model_capability_service.py`
- Create: `tests/test_model_capability_service.py`
- Modify: `proxy/services/model_connection_registry_service.py`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: registry revisions, secret resolver and validated endpoint.
- Produces: `CapabilityProbe.probe(revision, requested) -> CapabilitySnapshot` and `require_capabilities(snapshot, required, now) -> None`.

- [ ] **Step 1: Write failing capability tests with `httpx.MockTransport`**

```python
@pytest.mark.asyncio
async def test_probe_records_supported_unsupported_unknown_with_evidence():
    probe = CapabilityProbe(client=mock_client({
        ("GET", "/v1/models"): (200, {"data": [{"id": "qwen"}]}),
        ("POST", "/v1/chat/completions"): (200, chat_response("ok")),
        ("POST", "/v1/responses"): (404, {"error": "missing"}),
    }), peer_verifier=noop_test_peer_verifier)
    snapshot = await probe.probe(connection(), requested={
        CapabilityName.MODELS, CapabilityName.CHAT_COMPLETIONS, CapabilityName.RESPONSES,
    })
    assert snapshot.state(CapabilityName.CHAT_COMPLETIONS) is CapabilityState.SUPPORTED
    assert snapshot.state(CapabilityName.RESPONSES) is CapabilityState.UNSUPPORTED
    assert snapshot.observation(CapabilityName.EMBEDDINGS).state is CapabilityState.UNKNOWN
    assert snapshot.observation(CapabilityName.CHAT_COMPLETIONS).evidence_source == "probe"
```

Add cases proving that a template default cannot authorize tool calling, stale evidence fails a required-capability check, response bodies are capped and a probe never follows redirects.

- [ ] **Step 2: Run the test and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-3 tests/test_model_capability_service.py`

Expected: collection fails because `CapabilityProbe` is missing.

- [ ] **Step 3: Implement explicit probes**

Use endpoint builders that preserve `/v1` and `/api/v1`. Probe only capabilities explicitly requested by the administrator or role requirement. Use `GET /models`, minimal non-streaming and streaming Chat Completions, minimal client-tool schema, JSON Schema response format, stateless `POST /responses`, embeddings, token-count and rerank endpoints. Record status code, endpoint name and safe normalized reason; never retain output text.

Set default freshness to 24 hours, with `observed_at` and `expires_at` in UTC. Store one immutable snapshot through `ModelConnectionRegistry.save_capability_snapshot()`.

- [ ] **Step 4: Run focused tests and commit build 606**

Run the capability and registry tests, update version surfaces and ledger, then commit:

```powershell
git add proxy/services/model_capability_service.py proxy/services/model_connection_registry_service.py tests/test_model_capability_service.py tests/test_model_connection_registry_service.py config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/RELEASE_LEDGER.md
git commit -m "feat(models): record verified connection capabilities"
```

### Task 4: Legacy import, role resolution and explicit fallback

**Build:** 607

**Files:**
- Create: `proxy/services/model_connection_resolver_service.py`
- Create: `tests/test_model_connection_resolver_service.py`
- Modify: `proxy/services/llm_transport_profile_service.py`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: Tasks 1-3 and `resolve_transport_execution_profile()`.
- Produces: `ResolvedModelConnection`, `LegacyConnectionImporter.import_effective()`, `ModelConnectionResolver.resolve()` and `ModelConnectionResolver.resolve_fallback()`.

- [ ] **Step 1: Write failing migration and resolver tests**

```python
def test_legacy_freetoken_import_references_secret_without_copying_it(tmp_path):
    env = {
        "LES_LLM_PROVIDER": "freetoken",
        "FREETOKEN_BASE_URL": "http://127.0.0.1:1919/v1",
        "FREETOKEN_MODEL": "qwen-35b",
        "FREETOKEN_API_KEY": "must-not-enter-sqlite",
    }
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    imported = LegacyConnectionImporter(registry, env).import_effective(actor="migration")
    assert imported.secret_ref == "env:FREETOKEN_API_KEY"
    assert b"must-not-enter-sqlite" not in (tmp_path / "meta.db").read_bytes()


def test_fallback_resolves_only_explicit_bound_revision(tmp_path):
    registry, resolver, primary, fallback = configured_registry(tmp_path)
    assert resolver.resolve(ConnectionRole.ANSWER).revision_id == primary.revision_id
    assert resolver.resolve_fallback(primary.revision_id).revision_id == fallback.revision_id
```

Add table-driven migration parity for MLX, OpenAI/OpenAI-compatible, OpenRouter, Ollama, Lemonade and FreeToken. Assert deterministic import IDs, idempotency, no env mutation, explicit locality and no capability promotion from provider name.

- [ ] **Step 2: Run the test and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-4 tests/test_model_connection_resolver_service.py`

Expected: collection fails because the resolver service is missing.

- [ ] **Step 3: Implement immutable resolution**

```python
@dataclass(frozen=True)
class ResolvedModelConnection:
    connection_id: str
    revision_id: str
    display_name: str
    base_url: str
    model_id: str
    locality: ConnectionLocality
    requested_context_tokens: int | None
    effective_preset: ModelExecutionPreset
    capability_snapshot: CapabilitySnapshot
    endpoint: ValidatedEndpoint
    secret_ref: str | None
    extension_type: str | None
```

Expose `ModelConnectionResolver.resolve(role, required_capabilities=frozenset()) -> ResolvedModelConnection` and `resolve_fallback(failed_revision_id, required_capabilities=frozenset()) -> ResolvedModelConnection`. Resolution creates and stores the `ValidatedEndpoint` shown above so transport cannot reconstruct or weaken locality policy.

Require `CHAT_COMPLETIONS` for answer and fallback roles, `EMBEDDINGS` for embeddings. Disabled revisions, stale evidence, missing secrets and unsafe endpoints fail with stable typed codes. Resolve ContextGovernor preset from model identity, requested context and observed backend capacity; remove provider-name locality and FreeToken-only context inference from the new path while leaving the legacy compatibility functions intact for rollback.

- [ ] **Step 4: Implement deterministic legacy import**

Keep the provider-name mapping entirely in `LegacyConnectionImporter`. Templates create ordinary `openai_compatible` revisions. Bind only the formerly effective answer connection; create the MLX legacy revision as `local_fallback` only when old configuration actually used that fallback. Do not bind an embeddings connection without an explicit existing embedding endpoint/model.

- [ ] **Step 5: Run focused tests and commit build 607**

Run resolver, registry, security, capability and transport-profile tests; update version surfaces and ledger; commit:

```powershell
git add proxy/services/model_connection_resolver_service.py proxy/services/llm_transport_profile_service.py tests/test_model_connection_resolver_service.py config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/RELEASE_LEDGER.md
git commit -m "feat(models): resolve roles and legacy connections"
```

### Task 5: One OpenAI-compatible transport

**Build:** 608

**Files:**
- Create: `proxy/services/openai_compatible_transport_service.py`
- Create: `tests/test_openai_compatible_transport_service.py`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `ResolvedModelConnection`, `SecretValue`, endpoint policy and capability snapshots.
- Produces: `InferenceRequest`, `InferenceResponse`, `EmbeddingResponse`, `OpenAICompatibleTransport.complete()`, `.stream()` and `.embed()`.

- [ ] **Step 1: Write failing transport tests**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("display_name", ["FreeToken", "Ollama", "Lemonade", "MLX", "Renamed"])
async def test_transport_behavior_does_not_depend_on_display_name(display_name):
    transport, requests = transport_with_mock_response(chat_response("Готово"))
    result = await transport.complete(
        resolved_connection(display_name=display_name),
        InferenceRequest(messages=({"role": "user", "content": "test"},), max_output_tokens=64),
    )
    assert result.text == "Готово"
    assert requests[0].url.path.endswith("/v1/chat/completions")
```

Add streaming delta normalization, embeddings order preservation, authorization header, `max_tokens` versus `max_completion_tokens` from `capability_snapshot.transport_options["max_output_field"]`, structured tool calls, timeout, body cap, redirect and connected-peer checks. Assert `inspect.getsource(OpenAICompatibleTransport)` contains no engine names.

- [ ] **Step 2: Run the test and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-5 tests/test_openai_compatible_transport_service.py`

Expected: collection fails because the transport service is missing.

- [ ] **Step 3: Implement the transport**

```python
@dataclass(frozen=True)
class InferenceRequest:
    messages: Sequence[Mapping[str, Any]]
    max_output_tokens: int
    temperature: float | None = None
    tools: Sequence[Mapping[str, Any]] = ()
    response_format: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class InferenceResponse:
    text: str
    tool_calls: Sequence[Mapping[str, Any]]
    finish_reason: str
    usage: Mapping[str, int]


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: Sequence[Sequence[float]]
    model_id: str
    usage: Mapping[str, int]
```

Expose `OpenAICompatibleTransport.complete(connection, request) -> InferenceResponse`, async `OpenAICompatibleTransport.stream(connection, request) -> AsyncIterator[InferenceEvent]`, and `OpenAICompatibleTransport.embed(connection, inputs: Sequence[str]) -> EmbeddingResponse`.

Build headers after resolving the secret, use `follow_redirects=False`, validate the connected peer before reading content, cap error bodies, normalize `content|reasoning|reasoning_content`, and expose raw engine text only as normalized model output. Request variations depend solely on capability observations carried by the resolved connection.

- [ ] **Step 4: Run focused tests and commit build 608**

Run the transport, security, secret and capability tests; update version surfaces and ledger; commit:

```powershell
git add proxy/services/openai_compatible_transport_service.py tests/test_openai_compatible_transport_service.py config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md docs/RELEASE_LEDGER.md
git commit -m "feat(models): add provider-neutral inference transport"
```

### Task 6: Embeddings role integration

**Build:** 609

**Files:**
- Modify: `backend/qdrant_adapter.py`
- Modify: `backend/inference/providers.py`
- Create: `tests/test_model_connection_embeddings_integration.py`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: `ConnectionRole.EMBEDDINGS`, `ModelConnectionResolver`, `OpenAICompatibleTransport.embed()` and the existing `EmbedClient` public behavior.
- Produces: production dense embedding calls resolved through the exact global embeddings binding in active mode, with legacy rollback preserved.

- [ ] **Step 1: Write failing embedding integration tests**

```python
def test_active_embed_client_uses_exact_embeddings_binding(monkeypatch):
    resolved, transport = install_embedding_connection(monkeypatch, vectors=[[0.1, 0.2]])
    client = EmbedClient(connection_mode="active")
    assert client.get_text_embedding("duct") == [0.1, 0.2]
    assert transport.revision_calls == [resolved.revision_id]


def test_shadow_embedding_uses_legacy_once_and_never_calls_candidate(monkeypatch):
    legacy, candidate = install_shadow_embedding_paths(monkeypatch)
    client = EmbedClient(connection_mode="shadow")
    client.get_text_embedding("valve")
    assert legacy.call_count == 1
    assert candidate.resolve_count == 1
    assert candidate.transport_count == 0
```

Add cases for missing/stale `EMBEDDINGS` capability, preserved batch order/dimension, no answer-role substitution and no fallback to the answer or local-fallback connection.

- [ ] **Step 2: Run the test and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-6 tests/test_model_connection_embeddings_integration.py`

Expected: active mode cannot resolve the embeddings role because `EmbedClient` still constructs the MLX URL directly.

- [ ] **Step 3: Adapt `EmbedClient` without changing retrieval semantics**

Keep the existing vector normalization, dimensional checks, batching and public method names. Add an injected resolver/transport boundary. `legacy` uses the existing configured URL. `shadow` resolves and compares safe facts but performs exactly one legacy embedding request. `active` requires the exact `embeddings` binding and `EMBEDDINGS` capability, then uses `OpenAICompatibleTransport.embed()`.

Do not change dense+sparse indexing, named collection contracts, native RRF, reranking, parent expansion, embedding dimensions or dataset selection. Do not use answer or fallback bindings when embeddings resolution fails.

- [ ] **Step 4: Run embedding/retrieval regression tests and commit build 609**

Run the new integration test plus the existing focused `EmbedClient`, provider and mandatory-RRF contract tests identified in `docs/TEST_INVENTORY.md`. Update version surfaces and ledger; commit with `git commit -m "refactor(embeddings): use bound model connection"`.

### Task 7: Ordinary chat migration with zero-call shadow

**Build:** 610

**Files:**
- Modify: `proxy/routers/chat.py`
- Modify: `proxy/services/canonical_route_service.py`
- Modify: `proxy/services/agent_router_service.py`
- Modify: `backend/inference/routing.py`
- Modify: `tests/test_canonical_route_service.py`
- Create: `tests/test_model_connection_chat_integration.py`
- Modify: `tests/test_architecture_gate.py`
- Modify: the architecture-gate implementation identified by `tests/test_architecture_gate.py`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: resolver and transport from Tasks 4-5 plus existing canonical `legacy|shadow|active` decision.
- Produces: ordinary chat bound to one immutable connection revision and one explicit fallback.

- [ ] **Step 1: Write failing end-to-end chat tests**

```python
@pytest.mark.asyncio
async def test_shadow_compares_resolution_without_second_model_call(monkeypatch):
    calls = install_counting_legacy_model(monkeypatch, answer="legacy answer")
    shadow = install_shadow_connection_resolver(monkeypatch)
    result = await run_plain_chat("Прочитай файл")
    assert result["answer"] == "legacy answer"
    assert calls.count == 1
    assert shadow.resolve_count == 1
    assert shadow.transport_count == 0


@pytest.mark.asyncio
async def test_active_uses_only_bound_fallback_and_records_revision(monkeypatch):
    primary, fallback, transport = install_active_connections(monkeypatch, primary_status=503)
    result = await run_plain_chat("Ответь по источникам")
    assert transport.revision_calls == [primary.revision_id, fallback.revision_id]
    assert result["model_connection"]["revision_id"] == fallback.revision_id
    assert result["model_connection"]["fallback_used"] is True
```

Add cases for missing fallback, cloud/local consent based on `ConnectionLocality`, notebook-memory parity, ContextGovernor packet parity, streaming, attachment-only chat and one canonical tool decision.

- [ ] **Step 2: Extend the architecture gate and confirm RED**

Make the gate reject engine-name comparisons and direct model HTTP calls inside ordinary chat/runtime modules. Allow provider-name mapping only in `model_connection_resolver_service.LegacyConnectionImporter` and explicit adapter registration only in `model_engine_extension_service`.

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-7 tests/test_architecture_gate.py tests/test_model_connection_chat_integration.py`

Expected: failures identify current branches in `_llm_runtime()`, `_cloud_body_for_model()`, native Ollama branches and implicit fallback lists.

- [ ] **Step 3: Route ordinary calls through resolver and transport**

Replace `LlmRuntime` use in ordinary free, RAG, attachment, selector and answer paths with `ResolvedModelConnection`. Keep a narrowly named `LegacyLlmRuntimeAdapter` inside the rollback path. `shadow` resolves and compares safe fields but calls only the legacy adapter. `active` sends the governed packet through `OpenAICompatibleTransport`.

Remove ordinary-chat engine-name conditionals, `_ollama_native_complete` use, `cloud_fallback_models()` model chains and implicit `_mlx_runtime()` fallback. Do not edit `proxy/services/smeta_chat_adapter_service.py`; any protected/legacy smeta entry remains on its compatibility path and is not evidence for this task.

Reject `ChatRequest.provider_config` in installed mode with `SESSION_PROVIDER_OVERRIDE_DISABLED`; do not persist or convert the supplied key. Remove the public per-request override from ordinary installed UI payloads. A separately configured demo mode may continue only through the legacy rollback adapter and cannot be active registry behavior.

- [ ] **Step 4: Preserve governor, memory and one-call contracts**

Pass `connection.effective_preset` into the existing ContextGovernor. Populate cloud consent and memory routing from `connection.locality`, not a provider name. Include safe `connection_id`, `revision_id`, `display_name`, `model_id`, `locality` and `fallback_used` in trace/final payload; exclude URL and secret reference from ordinary-user payloads.

- [ ] **Step 5: Run focused chat gates and commit build 610**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/model-connections-7 tests/test_model_connection_chat_integration.py tests/test_canonical_route_service.py tests/test_openai_compatible_transport_service.py tests/test_model_preset_workflow_parity.py tests/test_architecture_gate.py
```

Update version surfaces and ledger; commit only the listed implementation/test/docs files with `git commit -m "refactor(chat): use bound model connections"`.

### Task 8: Authenticated model-connections API

**Build:** 611

**Files:**
- Create: `proxy/routers/model_connections.py`
- Modify: `proxy/app.py`
- Create: `tests/test_model_connections_router.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: registry, security, secrets, probe and resolver services.
- Produces: `/api/model-connections` administrator API and `/api/model-connections/effective` safe user view.

- [ ] **Step 1: Write failing API authorization and redaction tests**

```python
def test_user_can_read_effective_safe_connection_but_not_registry(client, user_headers):
    assert client.get("/api/model-connections", headers=user_headers).status_code == 403
    response = client.get("/api/model-connections/effective", headers=user_headers)
    assert response.status_code == 200
    payload = response.json()
    assert "secret_ref" not in json.dumps(payload)
    assert "base_url" not in payload


def test_admin_create_test_bind_disable_is_revision_safe(client, admin_headers):
    created = client.post("/api/model-connections", headers=admin_headers, json=valid_connection()).json()
    tested = client.post(f"/api/model-connections/{created['connection_id']}/test",
                         headers=admin_headers, json={"revision_id": created["revision_id"]})
    assert tested.status_code == 200
    bound = client.put("/api/model-connections/roles/answer", headers=admin_headers,
                       json={"connection_revision_id": created["revision_id"],
                             "expected_binding_revision": None})
    assert bound.status_code == 200
```

Cover stale revision 409, unsafe URL 422, masked secret replacement, no raw upstream body, explicit capability selection and disabled bound revision behavior.

- [ ] **Step 2: Run the router test and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-8 tests/test_model_connections_router.py`

Expected: `/api/model-connections` is absent.

- [ ] **Step 3: Implement exact endpoints**

```text
GET    /api/model-connections
GET    /api/model-connections/templates
POST   /api/model-connections
POST   /api/model-connections/{connection_id}/revisions
POST   /api/model-connections/{connection_id}/disable
POST   /api/model-connections/{connection_id}/secret
POST   /api/model-connections/{connection_id}/test
PUT    /api/model-connections/roles/{role}
GET    /api/model-connections/effective
```

All writes, templates and full-list reads depend on `require_admin`; effective safe read depends on `require_user`. Derive actor from the authenticated holder/role. Return only Pydantic public projections. The create endpoint generates `env:LES_MODEL_CONNECTION_<NORMALIZED_ID>_API_KEY` when a masked secret is supplied; clients never choose an arbitrary secret reference. The templates endpoint returns only field defaults for FreeToken, Ollama, Lemonade, MLX, LM Studio, llama.cpp and generic OpenAI-compatible connections. The test endpoint accepts an exact revision and requested capability list, validates the endpoint, runs the bounded probe and stores the immutable snapshot.

- [ ] **Step 4: Register router and update module maps**

Import and include the router in `proxy/app.py`. Add the model-connections service/router/test entry points to `docs/MODULE_INDEX.md` and `docs/CODE_MAP.md`, marking runtime integration implemented only where Task 7 proves it.

- [ ] **Step 5: Run focused API tests and commit build 611**

Run router, security, secret, capability and registry tests; update version surfaces and ledger; commit with `git commit -m "feat(api): manage model connections safely"`.

### Task 9: GUI-first administrator registry

**Build:** 612

**Files:**
- Create: `sovushka/pages/model_connections.py`
- Modify: `sovushka/components/header.py`
- Modify: `sovushka_ng.py`
- Modify: `sovushka/uikit/tokens.py` only if no existing semantic class covers a required state
- Create: `tests/test_sovushka_model_connections.py`
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: Task 8 API and existing `panel`, `status_badge`, feedback, dialog and form components.
- Produces: `build_model_connections()` configuration surface.

- [ ] **Step 1: Read the mandatory UI sources**

Read the complete `skills/sovushka-ui/SKILL.md`, then the relevant registry/layout sections of `docs/modules/sovushka-uikit.md`. Record the reused component names in the task commit message body; do not introduce a parallel card or badge system.

- [ ] **Step 2: Write failing UI contract tests**

```python
def test_model_connections_page_uses_safe_registry_actions():
    source = inspect.getsource(build_model_connections)
    for label in ("Подключения моделей", "Проверить", "Назначить", "Отключить"):
        assert label in source
    assert 'type="password"' in source
    assert "api_key" not in source
    assert "secret_ref" not in source


def test_configuration_navigation_has_model_connections_tab():
    header = inspect.getsource(build_header)
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    assert 'ui.tab("Модели"' in header
    assert "build_model_connections" in shell
```

Also test human locality labels, requested/effective/source text, restart indication, non-color-only health, mobile-safe classes and explicit confirmation for remote/private HTTP and disabling a bound revision.

- [ ] **Step 3: Run UI tests and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-9 tests/test_sovushka_model_connections.py`

Expected: import or assertion failure because the page and tab do not exist.

- [ ] **Step 4: Build the registry page**

Render one vertical configuration surface: safe summary row, role bindings, connection list and a create/edit dialog. Show display name, model, locality, enabled/health state, capability freshness, requested → effective context with source, secret state and restart fact. Actions are create from blank/template, copy, test selected capabilities, replace masked secret, assign role and disable.

Templates prefill FreeToken, Ollama, Lemonade, MLX, LM Studio, llama.cpp and generic OpenAI-compatible values but save no provider behavior. Danger confirmation shows the exact endpoint/locality or bound role being changed. Ordinary error text uses typed safe API messages.

- [ ] **Step 5: Wire navigation and remove installed per-provider controls**

Add `Модели` to configuration tabs and lazy page construction in `sovushka_ng.py`. Replace the installed-mode FreeToken/Ollama/Lemonade/OpenAI fields in the header settings dialog with a link to `Конфигурация → Модели`; keep unrelated mail and bootstrap settings unchanged. Do not modify smeta settings or smeta labels in this task.

- [ ] **Step 6: Run UI and API tests, update docs, commit build 612**

Run the new UI test plus existing header/UI-kit/runtime-registry tests. Update the UI-kit module doc and module index, version surfaces and ledger; commit with `git commit -m "feat(ui): manage global model connections"`.

### Task 10: Isolated engine extensions

**Build:** 613

**Files:**
- Create: `proxy/services/model_engine_extension_service.py`
- Create: `tests/test_model_engine_extension_service.py`
- Modify: `proxy/services/freetoken_cache_profile_service.py` only to expose its existing operation through a typed adapter; do not change cache calculations
- Modify: `proxy/routers/model_connections.py`
- Modify: `tests/test_model_connections_router.py`
- Modify: `docs/CODE_MAP.md`
- Modify: version surfaces and `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: exact connection revision, endpoint policy and existing FreeToken/MLX management endpoints.
- Produces: `EngineExtensionRegistry`, `EngineExtension`, typed `status()` and explicitly approved `execute()` operations.

- [ ] **Step 1: Write failing isolation tests**

```python
def test_inference_transport_cannot_access_engine_extensions():
    signature = inspect.signature(OpenAICompatibleTransport.__init__)
    assert "extension_registry" not in signature.parameters


@pytest.mark.asyncio
async def test_extension_selected_by_explicit_type_not_display_name():
    registry = EngineExtensionRegistry()
    registry.register("mlx", FakeExtension("mlx"))
    connection = resolved_connection(display_name="FreeToken", extension_type="mlx")
    assert (await registry.status(connection))["extension_type"] == "mlx"
```

Add tests that a missing extension leaves inference usable, unknown operations fail closed, FreeToken cache status preserves current calculations, MLX status is read-only, and mutating/unload operations require an exact durable approval reference.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-10 tests/test_model_engine_extension_service.py`

Expected: collection fails because the extension registry does not exist.

- [ ] **Step 3: Implement the extension boundary**

Define `EngineExtension` with async `status(connection) -> Mapping[str, Any]` and `execute(connection, operation, arguments, approval_ref) -> Mapping[str, Any]`. Define `EngineExtensionRegistry.register(extension_type, extension)`, async `status(connection)` and async `execute(connection, operation, arguments, approval_ref)` with duplicate-registration and unknown-extension rejection.

Register read-only FreeToken cache status and MLX health/memory/model status adapters. Preserve Ollama and Lemonade extension identifiers as unregistered/unsupported until a concrete operation is implemented and tested. Do not expose Lemonade Omni or any server-owned tool action.

- [ ] **Step 4: Add administrator extension endpoint**

Add `GET /api/model-connections/{connection_id}/extension/status`. Do not add a mutating endpoint in this release; the approval-aware protocol is tested for future use, while the public router remains read-only.

- [ ] **Step 5: Run focused tests and commit build 613**

Run extension, router, transport and existing FreeToken cache tests. Update code map, version surfaces and ledger; commit with `git commit -m "feat(models): isolate engine management extensions"`.

### Task 11: Closing gates, exact live acceptance command and workbook handoff

**Build:** 614

**Files:**
- Create: `tools/model_connection_live_acceptance.py`
- Create: `tests/test_model_connection_live_acceptance.py`
- Modify: `Makefile`
- Modify: `tests/test_architecture_gate.py`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `docs/superpowers/plans/2026-08-26-canonical-workbook-artifacts-implementation.md`
- Modify: version surfaces

**Interfaces:**
- Consumes: the complete model-connection subsystem.
- Produces: hermetic permanent gate coverage, an owner-gated paired live receipt and an explicit workbook-plan dependency on `ResolvedModelConnection`.

- [ ] **Step 1: Write failing receipt tests**

```python
def test_receipt_binds_exact_commit_build_revision_snapshot_and_model():
    receipt = build_receipt(
        source_commit="abc123", build_number=614,
        connection_revision_id="conn:c1:r2", capability_snapshot_id="cap:s1",
        preset_id="qwen-9b-restrictive", observed_model_identity="qwen3.5:9b",
        cases=(passing_case("chat"), passing_case("stream")),
    )
    assert receipt["passed"] is True
    assert len(receipt["acceptance_sha256"]) == 64
    assert "answer_text" not in receipt


def test_synthetic_or_mock_transport_cannot_issue_passing_receipt():
    with pytest.raises(ValueError, match="LIVE_EVIDENCE_REQUIRED"):
        build_receipt(
            source_commit="abc123", build_number=614,
            connection_revision_id="conn:c1:r2", capability_snapshot_id="cap:s1",
            preset_id="qwen-9b-restrictive", observed_model_identity="qwen3.5:9b",
            cases=(passing_case("chat"),), transport_kind="mock",
        )
```

- [ ] **Step 2: Run the receipt test and confirm RED**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/model-connections-11 tests/test_model_connection_live_acceptance.py`

Expected: failure because the acceptance tool is missing.

- [ ] **Step 3: Implement the owner-gated acceptance CLI**

The command accepts exact connection revision IDs for 9B and 35B, reads no plaintext secrets from arguments, resolves through the registry, and checks models/chat/stream/client-tools/context enforcement plus explicit fallback provenance when configured. It stores only pass/fail case hashes, timings, exact commit/build/revision/snapshot/preset/model identity and the aggregate SHA-256 receipt. It refuses test transports, fixture endpoints and unobserved model identity.

Add `make test-model-connections-live` as an opt-in target not included in `make verify` or `make test`. The target never changes `LES_CANONICAL_AGENT_ROUTE_MODE`; promotion remains a separate explicit administrator action.

- [ ] **Step 4: Make hermetic gates permanent**

Add all new non-live model-connection tests to the canonical current gate. Extend the architecture gate so future provider-name branches, secret serialization, implicit fallback chains and direct ordinary-chat model HTTP calls fail collection.

- [ ] **Step 5: Update canonical docs and workbook dependency**

Document the implemented request path, safe GUI/API factors, rollback and test locations. In the workbook plan, make provider projection consume `ResolvedModelConnection` and `OpenAICompatibleTransport`; forbid new FreeToken/Ollama/Lemonade/MLX branches. Do not alter workbook contracts or the two paused RED artifact tests.

- [ ] **Step 6: Set build 614 and run closing verification**

Set build 614 in `config/version.json`, run the version synchronizer, update the ledger with the pending checkpoint, then run in order:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/model-connections-final tests/test_model_connection_registry_service.py tests/test_model_connection_security_service.py tests/test_model_secret_service.py tests/test_model_capability_service.py tests/test_model_connection_resolver_service.py tests/test_openai_compatible_transport_service.py tests/test_model_connection_chat_integration.py tests/test_model_connections_router.py tests/test_sovushka_model_connections.py tests/test_model_engine_extension_service.py tests/test_model_connection_live_acceptance.py tests/test_architecture_gate.py
uv run python tools/sync_version_contract.py --check
make test
make verify
git diff --check
```

Expected: focused suite passes, version drift is empty, current behavior gate passes, verify collects the same canonical set, and diff check is clean. If `make` is unavailable, execute the exact commands from the corresponding Makefile targets with workspace-local `--basetemp`.

- [ ] **Step 7: Commit build 614**

Replace the pending ledger counts with exact fresh gate counts. Commit:

```powershell
git add tools/model_connection_live_acceptance.py tests/test_model_connection_live_acceptance.py Makefile tests/test_architecture_gate.py docs/TEST_INVENTORY.md docs/CURRENT_ARCHITECTURE.md docs/MODULE_INDEX.md docs/CODE_MAP.md docs/RELEASE_LEDGER.md docs/superpowers/plans/2026-08-26-canonical-workbook-artifacts-implementation.md config/version.json pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/SOFTWARE_VERSIONS.md docs/VERSIONING.md
git commit -m "test(models): close universal connection gates"
```

- [ ] **Step 8: Review before live use**

Use `superpowers:requesting-code-review`. Resolve every Critical/Important finding with `superpowers:receiving-code-review`, rerun the affected focused suite and closing gates, and commit review fixes separately. Report live acceptance as not run unless the owner explicitly authorizes access to the configured engines. Do not activate, deploy or publish.
