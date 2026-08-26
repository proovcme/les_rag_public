# Private Trust Fixes Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the reviewed behaviors from private PR5/7/9/10/12/14–18 onto the public `v0.28.2` lineage as focused trust fixes without importing unrelated history, protected smeta behavior or extension/native-runtime changes.

**Architecture:** Index identity/attestation and ingestion/provenance are two ordered slices; loopback proxy isolation, Windows path truth and lossless search degradation are independent narrow commits. Each behavior is reimplemented against current public code, tested locally, documented and reviewed before the next slice begins.

**Tech Stack:** Python 3.12, Qdrant client, SQLite, FastAPI, pytest, uv, Make.

**Spec:** `docs/superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md`

## Global Constraints

- Base is commit `4f4539d0`, whose ancestor is public `v0.28.2` at `e8ccad2b`.
- Private branches are evidence sources, not merge units. Do not merge a PR branch or bulk cherry-pick its version/docs/lock files.
- Do not copy PR6, PR8, PR11 or private PR13.
- Do not modify `proxy/smeta_core/**`; specifically skip PR10's `proxy/smeta_core/norm_browser.py` change and every private PR13 core change.
- Do not add dependencies, reindex user data, access private corpora or start services.
- RAG remains one contract-versioned named dense + BM25 sparse collection with native RRF, optional lossless reranking and parent/context expansion.
- Retrieval/index code may verify identity and integrity; it may not add domain boosts or professional decisions.
- Every task updates its module documentation and `docs/MODULE_INDEX.md`, increments `build_number` once, runs `make version-sync`, and records exact source commits plus exclusions in `docs/RELEASE_LEDGER.md` in the same commit.

---

### Task 1: Adapt PR5 served embedder identity verification

**Source commits:** `704edad5`, `ecfdb703`.

**Files:**
- Modify: `tools/build_rag_contract_sibling.py`
- Modify: `tests/test_build_rag_contract_sibling.py`
- Modify: `tools/platform_release_gate.py`
- Modify: `tests/test_test_profiles.py`
- Modify: `docs/ALGO-rag-best-practices.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: configured embedding recipe, served runtime health/metadata and expected vector size.
- Produces: `verify_embedding_runtime_identity(...) -> dict[str, Any]` and fail-closed sibling-build readiness.

- [ ] **Step 1: Write failing identity tests**

```python
def test_same_dimension_wrong_served_recipe_fails():
    result = verify_embedding_runtime_identity(
        configured_recipe={"model": "bge-m3", "pooling": "cls", "normalize": True},
        served_recipe={"model": "other", "pooling": "cls", "normalize": True},
        expected_vector_size=1024, observed_vector_size=1024,
    )
    assert result["ok"] is False
    assert result["code"] == "EMBEDDER_IDENTITY_MISMATCH"


def test_missing_served_recipe_fails_closed():
    assert verify_embedding_runtime_identity(configured_recipe=recipe(), served_recipe=None,
                                              expected_vector_size=1024,
                                              observed_vector_size=1024)["code"] == "EMBEDDER_IDENTITY_UNPROVEN"
```

- [ ] **Step 2: Run and confirm the current dimension-only behavior fails**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr5 tests/test_build_rag_contract_sibling.py`

- [ ] **Step 3: Adapt the two source functions without copying release churn**

Port the behavior of `_served_identity()` and `verify_embedding_runtime_identity()` from the source commits. Compare canonical model/recipe identity, vector size, pooling and normalization where the server exposes them. Never infer identity from dimension alone.

- [ ] **Step 4: Run focused and platform-profile tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr5 tests/test_build_rag_contract_sibling.py tests/test_test_profiles.py
make architecture-gate
```

- [ ] **Step 5: Update version/docs and commit**

Commit: `fix(rag): verify served embedding recipe identity`.

### Task 2: Adapt PR9 offline index attestation

**Source commits:** `88e98b18`, `004d4f0e`, `9f060786`, `d685d4c5`, `94717609`, `b284bfff`.

**Files:**
- Create: `backend/index_contract_attestation.py`
- Create: `tools/rag_index_contract_attest.py`
- Modify: `backend/rag_config.py`
- Modify: `backend/qdrant_adapter.py`
- Modify: `proxy/services/version_service.py`
- Modify: `tests/test_rag_index_attestation.py`
- Modify: `tests/test_qdrant_collection_layout.py`
- Modify: `tests/test_qdrant_adapter_parse.py`
- Modify: `tests/test_rag_config.py`
- Modify: `Makefile`
- Modify: `docs/ALGO-rag-best-practices.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: collection schema/config, sampled point digests, required payload contract and generation identity.
- Produces: `attest_collection()`, `persist_attestation()`, `validate_runtime_attestation()` and a read-only readiness result.

- [ ] **Step 1: Write failing attestation tests**

```python
def test_dense_readiness_requires_valid_attestation(tmp_path, fake_collection):
    status = validate_runtime_attestation(fake_collection, path=tmp_path / "missing.json")
    assert status.ok is False
    assert status.code == "INDEX_ATTESTATION_MISSING"


def test_attestation_binds_dense_sparse_rrf_and_generation(attestation):
    changed = replace(attestation, generation_id="other")
    assert validate_runtime_attestation(report=changed).code == "INDEX_GENERATION_MISMATCH"
```

- [ ] **Step 2: Run and confirm missing module/behavior**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr9 tests/test_rag_index_attestation.py tests/test_qdrant_collection_layout.py`

- [ ] **Step 3: Adapt the attestation module with current contract names**

Keep `collection_schema_snapshot`, `attestation_content_digest`, `attest_collection`, `persist_attestation` and `validate_runtime_attestation`. The report binds collection name, contract version, named dense vector, named BM25 sparse vector, native RRF expectation, embedding recipe identity, generation ID, required payload fields and deterministic sampled-record digests.

- [ ] **Step 4: Gate dense retrieval and expose redacted status**

`backend/qdrant_adapter.py` may return explicit unavailable/degraded readiness before retrieval when attestation is missing/stale/invalid. It must not silently fall back to an unattested dense index or copy legacy dense vectors.

- [ ] **Step 5: Run focused tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr9 tests/test_rag_index_attestation.py tests/test_qdrant_collection_layout.py tests/test_qdrant_adapter_parse.py tests/test_rag_config.py tests/test_version_api.py
make architecture-gate
```

- [ ] **Step 6: Update version/docs and commit**

Commit: `feat(rag): require offline index attestation`.

### Task 3: Adapt PR15 hierarchy identity and PR18 mutation timing

**Source commits:** PR15 `1b8b53c2`; PR18 `9593913c`, `a2796f6b`, `a984b75e`.

**Files:**
- Modify: `backend/qdrant_adapter.py`
- Modify: `backend/rag_hierarchy.py`
- Modify: `tools/build_rag_contract_sibling.py`
- Modify: `tests/test_rag_hierarchy.py`
- Modify: `tests/test_qdrant_adapter_parse.py`
- Modify: `tests/test_qdrant_collection_layout.py`
- Modify: `tests/test_external_index.py`
- Modify: `docs/ALGO-rag-best-practices.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: source document identity, hierarchy level/path and parse mutation boundary.
- Produces: stable unique point identities and correct attestation revocation timing.

- [ ] **Step 1: Write failing identity/timing tests**

```python
def test_parent_and_leaf_with_same_text_have_distinct_ids():
    assert hierarchy_point_id(doc="d1", level="parent", path=(1,), text="same") != \
           hierarchy_point_id(doc="d1", level="leaf", path=(1, 1), text="same")


def test_failure_before_first_mutation_keeps_valid_attestation(adapter):
    adapter.parse_document(source=missing_source())
    assert adapter.attestation_status().ok is True
```

- [ ] **Step 2: Run and confirm current behavior fails at least one assertion**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr15-18 tests/test_rag_hierarchy.py tests/test_qdrant_adapter_parse.py`

- [ ] **Step 3: Adapt structural identity**

Point identity includes contract version, dataset/document identity, node level, hierarchy path/ordinal and content digest. It remains deterministic across identical rebuilds and distinct across nodes with identical prose.

- [ ] **Step 4: Move attestation revocation to the first actual mutation**

Validation/admission/conversion failures before delete/upsert preserve a valid attestation. Revoke immediately before the first successful mutation attempt; every later mutation/error path remains fail closed until a new attestation is published.

- [ ] **Step 5: Run focused tests and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr15-18 tests/test_rag_hierarchy.py tests/test_qdrant_adapter_parse.py tests/test_qdrant_collection_layout.py tests/test_external_index.py tests/test_rag_index_attestation.py
make architecture-gate
```

Commit: `fix(rag): bind hierarchy identity and mutation attestation` after version/docs update.

### Task 4: Adapt PR10 loopback proxy isolation

**Source commits:** `dbf73691`, `e3f84c66`, `5800c55c`, `67b7adc5`.

**Files:**
- Create: `backend/loopback_http_policy.py`
- Create: `tests/test_loopback_http_policy.py`
- Modify: `backend/qdrant_adapter.py`
- Modify: `lemonade_host.py`
- Modify: `proxy/routers/runtime.py`
- Modify: `proxy/services/rag_readiness_service.py`
- Modify: `tools/activate_qdrant_generation.py`
- Modify: `tools/build_rag_contract_sibling.py`
- Modify: `tools/rag_index_contract_attest.py`
- Modify: `tests/test_embed_client_proxy_policy.py`
- Modify: `tests/test_qdrant_client_proxy_policy.py`
- Modify: `tests/test_lemonade_host.py`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: parsed target URL.
- Produces: `httpx_client_kwargs(url)`, `qdrant_client_kwargs(url)` and consistent `trust_env=False` for loopback only.

- [ ] **Step 1: Write failing proxy-policy tests**

```python
@pytest.mark.parametrize("url", ["http://127.0.0.1:6333", "http://localhost:11434", "http://[::1]:8080"])
def test_loopback_ignores_desktop_proxy(url):
    assert httpx_client_kwargs(url)["trust_env"] is False


def test_remote_url_keeps_explicit_default_policy():
    assert httpx_client_kwargs("https://provider.example") == {}
```

- [ ] **Step 2: Run and confirm current clients inherit proxy variables**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr10 tests/test_loopback_http_policy.py tests/test_embed_client_proxy_policy.py tests/test_qdrant_client_proxy_policy.py`

- [ ] **Step 3: Implement and apply the common policy**

Treat only resolved `localhost`, `127.0.0.0/8` and `::1` as loopback. Apply to answer-model, embedding and Qdrant clients in scoped files. Do not copy the source change under `proxy/smeta_core/**`.

- [ ] **Step 4: Run focused tests and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr10 tests/test_loopback_http_policy.py tests/test_embed_client_proxy_policy.py tests/test_qdrant_client_proxy_policy.py tests/test_lemonade_host.py tests/test_qdrant_adapter_parse.py
make architecture-gate
```

Commit: `fix(runtime): isolate loopback clients from proxy environment` after version/docs update.

### Task 5: Adapt PR7 truthful required OCR

**Source commits:** `4b819aff`, `74b15c64`, `c3e17cf3`, `8f802b79`, `84cbfdc4`, `bebf2b80`.

**Files:**
- Modify: `backend/converter.py`
- Modify: `backend/ocr_parser.py`
- Modify: `backend/qdrant_adapter.py`
- Modify: `tests/test_converter_corrupt_pdf.py`
- Modify: `tests/test_converter_process_isolation.py`
- Modify: `tests/test_converter_scanned_pdf_ocr.py`
- Modify: `tests/test_format_pipelines.py`
- Modify: `tests/test_parse_pipeline_w14.py`
- Modify: `tests/test_qdrant_adapter_parse.py`
- Modify: `tests/test_tesseract_ocr.py`
- Modify: `docs/ALGO-pdf-ingestion.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: PDF classification, configured OCR requirement and parser output.
- Produces: `OCRRequiredError`, `OCRProcessingError` and fail-closed parse status with no placeholder evidence.

- [ ] **Step 1: Write failing OCR truth tests**

```python
def test_required_ocr_unavailable_returns_error_not_placeholder(scanned_pdf, no_ocr):
    with pytest.raises(OCRRequiredError):
        convert_to_markdown_for_indexing(scanned_pdf)


def test_page_markers_only_are_not_evidence(scanned_pdf, ocr_returns="<!-- page 1 -->"):
    with pytest.raises(OCRProcessingError):
        convert_to_markdown_for_indexing(scanned_pdf)
```

- [ ] **Step 2: Run and confirm current behavior admits at least one false-success path**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr7 tests/test_converter_scanned_pdf_ocr.py tests/test_parse_pipeline_w14.py tests/test_tesseract_ocr.py`

- [ ] **Step 3: Adapt required-OCR classification and errors**

Required OCR must succeed with substantive page text. Corrupt/invalid PDFs, unavailable required engines, empty/page-marker-only OCR and late required-OCR transitions end in a typed parse error before Qdrant mutation. Optional OCR degradation remains explicit and never emits placeholder chunks.

- [ ] **Step 4: Run focused conversion/parse tests and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr7 tests/test_converter_corrupt_pdf.py tests/test_converter_process_isolation.py tests/test_converter_scanned_pdf_ocr.py tests/test_format_pipelines.py tests/test_parse_pipeline_w14.py tests/test_qdrant_adapter_parse.py tests/test_tesseract_ocr.py
make architecture-gate
```

Commit: `fix(ingestion): fail closed when required OCR is unavailable` after version/docs update.

### Task 6: Adapt PR12 per-file ownership and PR17 end-to-end provenance

**Source commits:** PR12 `777a9efc`, `9bb005d3`, `485eabaf`, `b11535fb`, `2a4c9a2e`, `c704f772`, `6aa0046c`, `77c48cb3`, `e3041eac`; PR17 `d7ac043a`, `66358fee`.

**Files:**
- Create: `backend/provenance.py`
- Create: `backend/ingestion_ownership.py`
- Modify: `backend/parquet_writer.py`
- Modify: `backend/qdrant_adapter.py`
- Modify: `proxy/services/lexical_index_service.py`
- Modify: `proxy/services/source_adapters.py`
- Modify: `proxy/services/project_summary_service.py`
- Modify: `proxy/services/pp87_composition_service.py`
- Modify: `tests/test_provenance_restore.py`
- Modify: `tests/test_ingestion_ownership.py`
- Modify: `tests/test_lexical_pdf_provenance.py`
- Modify: `tests/test_lexical_index_service.py`
- Modify: `tests/test_project_summary_inventory.py`
- Modify: `tests/test_parse_pipeline_w14.py`
- Modify: `tests/test_qdrant_adapter_parse.py`
- Modify: `docs/CODE_MAP.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: source file identity, page/sheet/row/bbox locators, output bytes and dataset/file key.
- Produces: versioned provenance records, `file_ingestion_lock()` and consumer-visible `source_ref`.

- [ ] **Step 1: Write failing ownership/provenance tests**

```python
def test_same_file_cannot_enter_replace_window_twice(tmp_path):
    with file_ingestion_lock("ds", "file.pdf", root=tmp_path):
        with pytest.raises(IngestionBusy):
            with file_ingestion_lock("ds", "file.pdf", root=tmp_path):
                pass


def test_page_sheet_row_bbox_reaches_consumer(source_record):
    payload = consumer_payload(source_record)
    assert payload["source_ref"]["page"] == 4
    assert payload["source_ref"]["sheet"] == "ВОР"
    assert payload["source_ref"]["row"] == 12
    assert payload["source_ref"]["bbox"] == [10, 20, 30, 40]
```

- [ ] **Step 2: Run and confirm missing ownership/provenance behavior**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr12-17 tests/test_ingestion_ownership.py tests/test_provenance_restore.py tests/test_lexical_pdf_provenance.py`

- [ ] **Step 3: Implement versioned provenance and lock the whole replace window**

Use `SourceIdentity`, `ProvenanceLocator`, `build_provenance_record`, `flat_payload`, `audit_provenance` and `file_ingestion_lock` interfaces from the reviewed commits. Ownership begins before delete and ends after Qdrant, lexical index and checkpoint state agree. A competing parse returns typed busy/deferred status.

- [ ] **Step 4: Carry exact locators to consumers**

Qdrant payload, lexical records, source adapters and summary/inventory consumers preserve real source hashes and locators. Internal filesystem paths never appear in browser/model payloads; `source_ref` uses source identity plus page/sheet/row/bbox.

- [ ] **Step 5: Run focused suites and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr12-17 tests/test_ingestion_ownership.py tests/test_provenance_restore.py tests/test_lexical_pdf_provenance.py tests/test_lexical_index_service.py tests/test_project_summary_inventory.py tests/test_parse_pipeline_w14.py tests/test_qdrant_adapter_parse.py
make architecture-gate
```

Commit: `feat(ingestion): preserve per-file ownership and provenance` after version/docs update.

### Task 7: Adapt PR14 resolved Windows state paths

**Source commits:** `e027cf7d`, `8462097a`, `52df5a09`, `b8e72188` (behavior only; omit unrelated smeta changes).

**Files:**
- Modify: `backend/filesystem_policy.py`
- Modify: `tests/test_filesystem_policy.py`
- Modify: `proxy/services/fgis_price_fetch_service.py`
- Modify: `proxy/services/fgis_price_service.py`
- Modify: `proxy/services/fsem_machinist_service.py`
- Modify: `tools/build_smeta_service_rag.py`
- Modify: `tools/build_smeta_structured_base.py`
- Modify: `tools/fgis_full_update.py`
- Modify: `tools/gesn_import.py`
- Modify: `tools/gesn_unify_base.py`
- Modify: `tools/gesn_update_from_fgis.py`
- Modify: `tests/test_fgis_price_service.py`
- Modify: `tests/test_fsem_machinist_service.py`
- Modify: `tests/test_prices_router_batch.py`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: configured application/state path.
- Produces: `real_location(path) -> Path`, `ensure_directory(path) -> Path` and truthful existence checks.

- [ ] **Step 1: Write failing path-resolution tests**

```python
def test_existing_junction_target_is_not_reported_absent(tmp_path, junction_factory):
    target = tmp_path / "state-target"
    target.mkdir()
    link = junction_factory(tmp_path / "state-link", target)
    assert real_location(link) == target.resolve()
    assert state_available(link) is True
```

Include Windows paths with Cyrillic, spaces and quotes using filesystem APIs, not shell-concatenated commands.

- [ ] **Step 2: Run and confirm current early-existence check fails on the link case**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr14 tests/test_filesystem_policy.py`

- [ ] **Step 3: Adapt the two path helpers and narrow consumers**

Resolve the effective location before `exists()`/creation/absence decisions. Preserve user-configured display path separately from the effective resolved path. Do not copy changes under `proxy/smeta_core/**`.

- [ ] **Step 4: Run focused tests and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr14 tests/test_filesystem_policy.py
make architecture-gate
```

Commit: `fix(windows): resolve state paths before absence checks` after version/docs update.

### Task 8: Adapt PR16 lossless `/api/search` reranker degradation

**Source commits:** `3d84950b`, `1aa49e56`.

**Files:**
- Modify: `proxy/services/retrieval_service.py`
- Modify: `proxy/routers/datasets.py`
- Modify: `tests/test_retrieval_service.py`
- Modify: `tests/test_datasets_router.py`
- Modify: `tests/test_onboard_reranker.py`
- Modify: `docs/ALGO-rag-best-practices.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`

**Interfaces:**
- Consumes: native-RRF candidate list and optional reranker result/error.
- Produces: available evidence plus explicit degradation and actual resolved scope.

- [ ] **Step 1: Write failing lossless degradation tests**

```python
@pytest.mark.asyncio
async def test_reranker_failure_keeps_native_rrf_evidence(fake_backend):
    result = await retrieve_chat_chunks(fake_backend, reranker=raising_reranker())
    assert result.chunks == fake_backend.native_rrf_chunks
    assert result.trace.reranker_status == "degraded"


def test_search_reports_actual_scope(client):
    response = client.get("/api/search", params={"q": "x", "dataset": "missing"}).json()
    assert response["scope"]["resolved_dataset_ids"] == []
```

- [ ] **Step 2: Run and confirm current reranker path can erase or misreport evidence**

Run: `uv run python -m pytest -q --basetemp=.test-tmp/pr16 tests/test_retrieval_service.py tests/test_datasets_router.py tests/test_onboard_reranker.py`

- [ ] **Step 3: Adapt the lossless policy**

Native-RRF results are authoritative available evidence. Optional reranker success may reorder them; unavailable/error/empty reranker output returns the original order with typed degradation. It may not replace the list with empty results. `/api/search` reports requested and resolved scope separately.

- [ ] **Step 4: Run focused tests and commit**

```text
uv run python -m pytest -q --basetemp=.test-tmp/pr16 tests/test_retrieval_service.py tests/test_datasets_router.py tests/test_onboard_reranker.py
make architecture-gate
```

Commit: `fix(search): preserve native RRF on reranker degradation` after version/docs update.

### Task 9: Close the private-intake gate and release classification

**Files:**
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/TEST_INVENTORY.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/RELEASE_LEDGER.md`
- Modify: `tests/test_release_classification.py`
- Modify: `tests/test_github_patch_release.py`

**Interfaces:**
- Consumes: Tasks 1–8 and the lightweight update classifier.
- Produces: exact proof that the update contains no dependency, installer, native runtime or destructive migration change.

- [ ] **Step 1: Add release-boundary assertions**

```python
def test_0290_trust_fixes_remain_patch_safe(classifier):
    report = classifier.classify(committed_change_set())
    assert report.native_runtime_changed is False
    assert report.dependency_lock_changed is False
    assert report.destructive_migration is False
    assert report.channel == "lightweight_github_update"


def test_pr6_native_qdrant_change_requires_installer(classifier):
    assert classifier.classify({"installers/windows/qdrant.exe"}).channel == "full_installer"
```

- [ ] **Step 2: Run all trust-focused tests**

```text
uv run python -m pytest -q --basetemp=.test-tmp/trust-final tests/test_build_rag_contract_sibling.py tests/test_rag_index_attestation.py tests/test_rag_hierarchy.py tests/test_qdrant_collection_layout.py tests/test_qdrant_adapter_parse.py tests/test_loopback_http_policy.py tests/test_embed_client_proxy_policy.py tests/test_qdrant_client_proxy_policy.py tests/test_converter_scanned_pdf_ocr.py tests/test_parse_pipeline_w14.py tests/test_ingestion_ownership.py tests/test_provenance_restore.py tests/test_lexical_pdf_provenance.py tests/test_filesystem_policy.py tests/test_retrieval_service.py tests/test_datasets_router.py tests/test_release_classification.py tests/test_github_patch_release.py
```

- [ ] **Step 3: Run canonical gates**

```text
make architecture-gate
make verify
make test
git diff --check
```

- [ ] **Step 4: Record exact inclusions and exclusions**

The ledger lists each adapted source commit and states: PR6 separate installer; PR8/11 separate extension line; private PR13 excluded; `proxy/smeta_core/**` unchanged; no user corpus/reindex used.

- [ ] **Step 5: Commit the verified checkpoint**

Commit: `docs(release): record adapted trust-fix gate`.
