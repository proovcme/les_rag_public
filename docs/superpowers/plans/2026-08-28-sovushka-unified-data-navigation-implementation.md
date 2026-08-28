# Sovushka Unified Data Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace separate Documents, Datasets and Mail destinations with one role-aware Data workspace while keeping mail ingestion alive and exposing Studio/CAD-BIM only as honest unavailable placeholders.

**Architecture:** A new thin `data_workspace` page selects catalog or dataset-detail mode from the canonical `dataset_id` query value. It composes the existing Samovar catalog and Documents reader through explicit parameters instead of copying their API logic. Header and shell own canonical navigation and legacy URL migration; backend collection, retrieval, mail and CAD/BIM code remain unchanged.

**Tech Stack:** Python 3.12+, NiceGUI/Quasar, shared Sovushka UIKit, pytest, `uv`, existing FastAPI APIs

**Spec:** `docs/superpowers/specs/2026-08-28-sovushka-unified-data-navigation-design.md`

## Global Constraints

- Start only after the build 615 Models UI changes are verified and committed, leaving a clean worktree.
- Do not add dependencies or change backend API, retrieval, indexing, document contents, permissions or mail collection behavior.
- Do not edit `frontend/cad_bim_viewer/`, generated CAD/BIM bundles, mail collector code or stored data.
- Canonical routes are `/classic?tab=data` and `/les/classic?tab=data`; preserve a non-empty `dataset_id` when migrating `documents` or `datasets` URLs.
- `Студия · скоро` and `CAD/BIM · скоро` are disabled placeholders and must not construct document panels or timers.
- `Почта` and `Настройка почты` have no production navigation entry; mail pages and APIs remain in the repository.
- Mobile uses sequential catalog -> files -> detail navigation with no page-level horizontal overflow at 390 px.
- Use shared UIKit components and outline icons; tap targets stay at least 44 by 44 px.
- Apply TDD for every behavior change and update module documentation, version and release ledger in the implementation commit that changes behavior.

---

### Task 1: Canonical Data Route and Dormant Product Surfaces

**Files:**
- Create: `sovushka/pages/data_workspace.py`
- Modify: `sovushka/components/header.py`
- Modify: `sovushka_ng.py`
- Test: `tests/test_sovushka_uikit.py`
- Test: `tests/test_static_assets.py`

**Interfaces:**
- Consumes: existing `build_header(...)`, `lazy_tab_panels(...)`, `build_samovar()`, `build_documents(...)`.
- Produces: `build_data_workspace(*, is_admin: bool) -> dict[str, list[object]]`, canonical tab key `data`, compatibility helper `_canonical_workspace_tab(value: str) -> str`.

- [ ] **Step 1: Write failing navigation and compatibility tests**

Add these focused assertions (with the existing test-module imports):

```python
def test_product_navigation_has_one_data_destination_and_dormant_surfaces():
    header = Path("sovushka/components/header.py").read_text(encoding="utf-8")
    assert 'tab_refs["data"] = ui.tab("Данные", icon="o_database")' in header
    assert 'ui.tab("Документы"' not in header
    assert 'ui.tab("Датасеты"' not in header
    assert 'ui.tab("Почта"' not in header
    assert '"CAD/BIM · скоро"' in header
    assert 'aria-label="CAD/BIM — скоро"' in header


def test_legacy_workspace_tabs_resolve_without_building_dormant_pages():
    shell = Path("sovushka_ng.py").read_text(encoding="utf-8")
    assert '"documents": "data"' in shell
    assert '"datasets": "data"' in shell
    assert '"mail": "chat"' in shell
    assert '"studio": "chat"' in shell
    assert '"cad_bim": "chat"' in shell
    assert 'build_documents(surface="studio")' not in shell
    assert 'build_documents(surface="cad_bim")' not in shell
    assert "build_mail()" not in shell
    assert "build_mail_settings()" not in shell
```

Update the current positive mail-navigation assertions in
`tests/test_static_assets.py` to protect the opposite contract: the page
functions remain defined in `sovushka/pages/mail.py`, while the production shell
does not import or construct them.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-nav-red tests/test_sovushka_uikit.py tests/test_static_assets.py
```

Expected: failures for missing `data` tab, still-visible Mail/CAD-BIM tabs and
legacy panels still being constructed.

- [ ] **Step 3: Add the thin workspace and canonical tab helper**

Create `sovushka/pages/data_workspace.py` with the stable public interface:

```python
from __future__ import annotations

from nicegui import context

from sovushka.pages.documents import build_documents
from sovushka.pages.samovar import build_samovar


def requested_dataset_id() -> str:
    try:
        return str(context.client.request.query_params.get("dataset_id") or "").strip()
    except (AttributeError, RuntimeError):
        return ""


def build_data_workspace(*, is_admin: bool) -> dict[str, list[object]]:
    dataset_id = requested_dataset_id()
    if dataset_id:
        build_documents(
            surface="data",
            initial_dataset_id=dataset_id,
            show_dataset_picker=False,
        )
        return {"timers": []}
    return build_samovar(
        can_manage=is_admin,
        open_tab="data",
        workspace_title="Данные",
    )
```

Add the pure shell helper in `sovushka_ng.py`:

```python
def _canonical_workspace_tab(value: str) -> str:
    requested = str(value or "").strip().casefold()
    return {
        "documents": "data",
        "datasets": "data",
        "mail": "chat",
        "studio": "chat",
        "cad_bim": "chat",
        "": "chat",
    }.get(requested, requested)
```

Use `data` as the only working data tab in Classic, call
`build_data_workspace(is_admin=is_admin)`, and remove production imports/builders
for `build_mail`, `build_mail_settings`, Studio and CAD/BIM document surfaces.
Preserve `dataset_id` by changing only the `tab` query value via a server-side
redirect or history replacement; never rebuild the URL from a partial query.

- [ ] **Step 4: Make the header expose Data and unavailable CAD/BIM**

Change `visible_workspace_sections()` to return only product-visible working
keys and placeholders:

```python
return ("chat", "data", "studio", "cad_bim_placeholder", "history")
```

Replace `include_documents`, `include_datasets` and `include_mail` with the
single `include_data: bool = False` argument. Add one live `Данные` tab. Render
CAD/BIM through the same shared disabled-placeholder pattern as Studio, including
the label `CAD/BIM · скоро`, `disable`, an accessible name and the tooltip
`Раздел готовится к выпуску`. Do not add a `cad_bim` tab reference.

Remove both Mail entries and the configuration Datasets entry from desktop tabs,
mobile menu entries and tooltips. Keep `Модели` and the other current
configuration destinations unchanged.

- [ ] **Step 5: Run navigation tests and verify GREEN**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-nav-green tests/test_sovushka_uikit.py tests/test_static_assets.py
```

Expected: all selected tests pass; no production shell source contains a call to
Mail, Studio or CAD/BIM page builders.

- [ ] **Step 6: Record the verified routing checkpoint**

Record the exact passing command and inspect `git diff --check` for the files in
this task. Do not commit yet: repository policy requires behavior, module docs,
version and ledger to land together in the final build 616 commit.

---

### Task 2: Role-Aware Dataset Catalog

**Files:**
- Modify: `sovushka/pages/samovar.py`
- Modify: `sovushka/pages/data_workspace.py`
- Modify: `sovushka/uikit/tokens.py`
- Create: `tests/test_sovushka_samovar.py`
- Test: `tests/test_sovushka_uikit.py`

**Interfaces:**
- Consumes: `build_data_workspace(is_admin=...)` from Task 1 and existing dataset/document APIs.
- Produces: `build_samovar(*, can_manage: bool = True, open_tab: str = "data", workspace_title: str = "Данные") -> dict[str, list[object]]`; pure `_dataset_source_label(row: dict) -> str`.

- [ ] **Step 1: Write failing catalog behavior tests**

Add tests that import the pure labels and inspect the page contract:

```python
def test_mail_collection_is_a_data_source_not_a_destination():
    assert _dataset_source_label({"dataset_kind": "correspondence"}) == "Почта"
    assert _dataset_source_label({"source_type": "imap"}) == "Почта"
    assert _dataset_source_label({"dataset_scope": "system"}) == "Служебные данные"
    assert _dataset_source_label({"dataset_kind": "project"}) == "Проект"


def test_catalog_management_is_role_gated_in_builder_source():
    source = inspect.getsource(build_samovar)
    assert "if can_manage:" in source
    assert 'workspace_title: str = "Данные"' in source
    assert '"tab": open_tab' in source
```

Add a UI contract assertion that the catalog title is `Данные`, the explanatory
copy describes collections and files, and the page still uses shared panels,
status badges and action buttons.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-catalog-red tests/test_sovushka_samovar.py tests/test_sovushka_uikit.py
```

Expected: failures because the catalog has no role or canonical-tab arguments
and does not classify mail collections.

- [ ] **Step 3: Add source labels and canonical open behavior**

Implement the exact pure mapping near the other Samovar helpers:

```python
def _dataset_source_label(row: dict) -> str:
    source = str(row.get("source_type") or "").casefold()
    kind = str(row.get("dataset_kind") or row.get("kind") or "").casefold()
    name = str(row.get("name") or "").upper()
    if source in {"imap", "mail", "outlook"} or kind == "correspondence" or "_MAIL_" in name:
        return "Почта"
    if str(row.get("dataset_scope") or "").casefold() == "system":
        return "Служебные данные"
    return {
        "project": "Проект",
        "norm": "Нормативы",
        "estimate": "Сметы",
        "catalog": "Каталог",
        "cad_bim": "CAD/BIM",
    }.get(kind, "Данные")
```

Carry `dataset_kind`, `source_type` and `dataset_scope` from the dataset API row
into each aggregated catalog row. Replace `_open_files` URL construction with:

```python
ui.navigate.to(f"/classic?{urlencode({'tab': open_tab, 'dataset_id': ds_id})}")
```

Select `/les/classic` when the current request uses the prefixed route, matching
the existing chat navigation pattern.

- [ ] **Step 4: Gate operator mutations without changing API authorization**

Change the public builder signature to the interface above. Always render
search, filters, collection rows, readiness and `Открыть` actions. Render these
only inside `if can_manage:` blocks:

- `Добавить датасет`;
- `Управление индексатором`;
- parse, repair, delete, registry mutation and index-setting actions.

The `can_manage=False` branch must not create the corresponding buttons or
dialogs. Backend permissions remain authoritative.

Rename the visible hero and section copy from the implementation acronym to the
plain product concept `Данные`. Keep source identity as metadata on rows rather
than another navigation layer.

- [ ] **Step 5: Apply focused catalog/mobile styles**

Use the existing `.sov-datasets-*` registry where possible. Add only the missing
classes for a compact source badge and ensure the 390 px rule produces one
column, 44 px controls and no fixed-width dialog or row action overflow. Do not
introduce another color palette or icon family.

- [ ] **Step 6: Run catalog tests and verify GREEN**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-catalog-green tests/test_sovushka_samovar.py tests/test_sovushka_uikit.py
```

Expected: all selected tests pass; source labels do not depend only on color;
operator controls are absent from the ordinary-user contract.

- [ ] **Step 7: Record the verified catalog checkpoint**

Record the passing command and run `git diff --check` for this task's files. Keep
the changes uncommitted until the build 616 documentation and version are ready.

---

### Task 3: Dataset Detail as the Second Data Level

**Files:**
- Modify: `sovushka/pages/documents.py`
- Modify: `sovushka/pages/data_workspace.py`
- Modify: `sovushka/uikit/tokens.py`
- Create: `tests/test_sovushka_documents.py`
- Test: `tests/test_sovushka_uikit.py`

**Interfaces:**
- Consumes: canonical `dataset_id` and `build_data_workspace` from Task 1.
- Produces: `build_documents(*, surface: str = "documents", initial_dataset_id: str = "", show_dataset_picker: bool = True, can_manage: bool = False) -> None`; Data detail surface value `data`.

- [ ] **Step 1: Write failing detail-mode tests**

Add these tests (with `inspect` and the page builder imported):

```python
def test_data_detail_accepts_explicit_dataset_and_hides_duplicate_picker():
    signature = inspect.signature(build_documents)
    assert "initial_dataset_id" in signature.parameters
    assert "show_dataset_picker" in signature.parameters
    assert "can_manage" in signature.parameters
    source = inspect.getsource(build_documents)
    assert 'surface not in {"documents", "data", "studio", "cad_bim"}' in source
    assert 'if show_dataset_picker:' in source
    assert '"Назад ко всем данным"' in source


def test_data_detail_keeps_chat_scope_exact():
    source = inspect.getsource(build_documents)
    assert '"scope": f"ds:{dataset_id}"' in source
    assert '"target_file": file_name' in source
```

Add a contract assertion that uploading and dataset mutation controls are inside
`if can_manage:` while document reading, provenance and `Спросить в чате` remain
available to readers.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-detail-red tests/test_sovushka_documents.py tests/test_sovushka_uikit.py
```

Expected: failures for the missing parameters, missing Data surface and duplicate
dataset picker.

- [ ] **Step 3: Add explicit Data detail parameters**

Change the builder signature exactly as declared above. Resolve the initial
dataset with explicit input first and request context only as compatibility:

```python
initial_dataset = str(initial_dataset_id or "").strip()
if not initial_dataset:
    try:
        initial_dataset = str(context.client.request.query_params.get("dataset_id") or "").strip()
    except (AttributeError, RuntimeError):
        initial_dataset = ""
```

Map `surface="data"` to the existing document-reader mode, not Studio or CAD:

```python
initial_mode = {"documents": "map", "data": "map", "studio": "studio", "cad_bim": "cad"}[surface]
```

For Data, label the page with the selected collection name and `Файлы и
доказательства`. Add a shared quiet action `Назад ко всем данным` that navigates
to the same route prefix with `tab=data` and no `dataset_id`.

- [ ] **Step 4: Remove the duplicate dataset level in embedded detail**

Wrap creation of `datasets_column`, its filters and dataset list in
`if show_dataset_picker:`. When false, build only the files and reader columns,
and add `sov-data-detail--focused` to the workspace. Do not fetch a second
catalog solely for rendering; `_load_datasets()` may still fetch dataset metadata
needed to resolve the selected row and permissions.

Keep the existing file list, original preview, provenance, readiness and exact
chat-scope actions. Do not expose Studio draft controls or CAD inventory in Data.

- [ ] **Step 5: Gate dataset/file mutations in the detail surface**

Reader operations remain visible. Wrap rename, group editing, service-file
upload and integrity repair controls in `if can_manage:`. Pass
`can_manage=is_admin` from `build_data_workspace`.

Do not infer authorization from dataset type. A system dataset may be readable
without being mutable.

- [ ] **Step 6: Add focused desktop and mobile layout rules**

For `.sov-data-detail--focused`:

- desktop `>= 901px`: files column plus document reader, no empty dataset column;
- mobile `<= 900px`: one sequential column; opening a file moves the reader into
  view without horizontal scroll;
- `<= 390px`: no fixed minimum width, breadcrumb and actions wrap, every icon
  action stays 44 px.

Reuse current `.sov-docs-*` classes and change only the focused modifier rules.

- [ ] **Step 7: Run detail tests and verify GREEN**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-detail-green tests/test_sovushka_documents.py tests/test_sovushka_uikit.py
```

Expected: all selected tests pass; Data builds document-reader mode with one
dataset context and no Studio/CAD behavior.

- [ ] **Step 8: Record the verified detail checkpoint**

Record the passing command and run `git diff --check` for this task's files. Keep
the changes uncommitted for the single policy-compliant build 616 commit.

---

### Task 4: Compatibility, Responsive Acceptance and Dormant-Code Proof

**Files:**
- Modify: `sovushka_ng.py`
- Modify: `tests/test_sovushka_uikit.py`
- Modify: `tests/test_static_assets.py`
- Modify: `tests/test_sovushka_chat.py`
- Test: `tests/test_sovushka_data_workspace.py`

**Interfaces:**
- Consumes: `requested_dataset_id()`, `build_data_workspace(...)`, canonical tab helper and role-aware builders from Tasks 1–3.
- Produces: deterministic compatibility tests and acceptance evidence for desktop/mobile navigation.

- [ ] **Step 1: Add failing unit tests for URL migration**

Create `tests/test_sovushka_data_workspace.py` with pure cases:

```python
@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("data", "data"),
        ("documents", "data"),
        ("datasets", "data"),
        ("mail", "chat"),
        ("studio", "chat"),
        ("cad_bim", "chat"),
        ("", "chat"),
    ],
)
def test_canonical_workspace_tab(requested, expected):
    assert _canonical_workspace_tab(requested) == expected
```

Add source-contract tests that a `documents`/`datasets` request retains
`dataset_id`, updates browser history to `tab=data`, and old stored names
`Документы`/`Датасеты` resolve to the Data tab. Assert Mail, Studio and CAD/BIM
never appear in `lazy_tab_panels` builders.

- [ ] **Step 2: Run compatibility tests and verify RED**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-compat-red tests/test_sovushka_data_workspace.py tests/test_sovushka_uikit.py tests/test_static_assets.py tests/test_sovushka_chat.py
```

Expected: at least the empty/stored-value migration cases fail until shell
normalization is complete.

- [ ] **Step 3: Complete deterministic query and stored-state migration**

Normalize query values before target selection. For `documents` or `datasets`,
retain the complete query mapping, replace only `tab`, and issue a canonical
redirect with `urlencode(..., doseq=True)`. Normalize stored labels with:

```python
stored_aliases = {
    "Документы": "Данные",
    "Датасеты": "Данные",
    "Почта": "AI ЧАТ",
    "Студия": "AI ЧАТ",
    "CAD/BIM": "AI ЧАТ",
}
```

After selecting a live tab, store only canonical names. Do not construct a hidden
legacy tab to satisfy old state.

- [ ] **Step 4: Verify dormant mail/CAD contracts without running services**

Run the existing offline mail and packaging contracts that prove code remains
present and buildable:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-dormant tests/test_static_assets.py tests/test_chat_mail_query.py tests/test_converter_email.py tests/test_ezhik_imap_smoke.py tests/test_mail_ingest.py tests/test_mail_profile.py tests/test_mail_push_service.py tests/test_mail_query_service.py tests/test_mail_registry_service.py tests/test_mail_router.py tests/test_mail_threads.py tests/test_outlook_mail_poller.py tests/test_artel_packaging.py tests/test_atlas_packaging.py
```

Do not start mail collection or live Outlook. Expected: all selected offline
tests pass.

- [ ] **Step 5: Run browser acceptance at required breakpoints**

Start a disposable UI instance on port 8151 without restarting production.
Inspect these states through the local browser:

1. 1280 px catalog: one `Данные` destination, no Documents/Datasets/Mail button,
   disabled Studio and CAD/BIM placeholders.
2. 1280 px detail opened from the first collection already visible in the
   read-only catalog: back action, files and reader; no duplicate dataset column.
3. 390 by 844 px catalog: one column, no page overflow, 44 px controls.
4. 390 by 844 px detail: sequential files/detail flow and no horizontal overflow.

Record DOM measurements for `document.documentElement.scrollWidth <= innerWidth`
and accessible names for Data, both placeholders, back and primary actions.
Use an available real dataset only for read-only visual confirmation; absence of
a local corpus is an honest empty-state acceptance, not a reason to create data.

- [ ] **Step 6: Run compatibility tests and verify GREEN**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-compat-green tests/test_sovushka_data_workspace.py tests/test_sovushka_uikit.py tests/test_static_assets.py tests/test_sovushka_chat.py
```

Expected: all selected tests pass and no dead page is built by the production
shell.

- [ ] **Step 7: Record the verified compatibility checkpoint**

Record the browser measurements and passing command. Keep the changes
uncommitted for the final build 616 commit.

---

### Task 5: Documentation, Version and Release Gates

**Files:**
- Modify: `docs/modules/sovushka-uikit.md`
- Modify: `docs/MODULE_INDEX.md`
- Modify: `docs/CODE_MAP.md`
- Modify: `config/version.json`
- Modify: `docs/RELEASE_LEDGER.md`
- Generated/update as required: version-contract files produced by `tools/sync_version_contract.py`

**Interfaces:**
- Consumes: complete behavior from Tasks 1–4.
- Produces: truthful build 616 documentation and release evidence.

- [ ] **Step 1: Update living documentation**

Document the current state, not the implementation event:

- `sovushka-uikit.md`: one Data destination; catalog/detail flow; role boundary;
  Mail hidden while ingestion continues; Studio/CAD placeholders; mobile rules.
- `MODULE_INDEX.md`: point the Sovushka module at
  `sovushka/pages/data_workspace.py`, `samovar.py`, `documents.py` and header
  routing; remove claims that Mail/Documents/Datasets are separate live product
  destinations.
- `CODE_MAP.md`: map canonical Data route and note dormant page code.

- [ ] **Step 2: Bump the release contract**

Set:

```json
{
  "product_version": "0.29.0",
  "build_number": 616,
  "desktop_version": "5.1.616"
}
```

Preserve the other existing version fields. Add one release-ledger entry that
describes the unified Data surface, hidden Mail navigation and CAD/BIM
placeholder without claiming mail ingestion or CAD engines were changed.

- [ ] **Step 3: Synchronize and test version files**

Run:

```powershell
uv run python tools/sync_version_contract.py
uv run python -m pytest -q --basetemp=.test-tmp/data-version tests/test_software_versions.py
```

Expected: synchronization succeeds and version tests pass.

- [ ] **Step 4: Run the focused UI/data/mail gate**

Run:

```powershell
uv run python -m pytest -q --basetemp=.test-tmp/data-focused tests/test_sovushka_data_workspace.py tests/test_sovushka_samovar.py tests/test_sovushka_documents.py tests/test_sovushka_chat.py tests/test_sovushka_uikit.py tests/test_static_assets.py tests/test_chat_mail_query.py tests/test_converter_email.py tests/test_ezhik_imap_smoke.py tests/test_mail_ingest.py tests/test_mail_profile.py tests/test_mail_push_service.py tests/test_mail_query_service.py tests/test_mail_registry_service.py tests/test_mail_router.py tests/test_mail_threads.py tests/test_outlook_mail_poller.py tests/test_software_versions.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Run repository release gates**

Run:

```powershell
make verify
make test
git diff --check
```

On Windows without `make`, execute the exact current `uv` commands from the
corresponding Makefile targets with workspace-local `--basetemp`. Expected:
collection, contract/behavior tests and whitespace check pass.

- [ ] **Step 6: Review the complete branch diff**

Confirm:

- no backend mail collector, retrieval or CAD/BIM engine file changed;
- no dependency or lockfile changed;
- no production Mail/Documents/Datasets live navigation remains;
- build 616 documentation describes only behavior present in code;
- unrelated user changes are not staged.

- [ ] **Step 7: Commit build 616**

Stage the complete implementation and only the documented version surfaces:

```powershell
git add sovushka/pages/data_workspace.py sovushka/pages/samovar.py sovushka/pages/documents.py sovushka/components/header.py sovushka/uikit/tokens.py sovushka_ng.py tests/test_sovushka_data_workspace.py tests/test_sovushka_samovar.py tests/test_sovushka_documents.py tests/test_sovushka_chat.py tests/test_sovushka_uikit.py tests/test_static_assets.py config/version.json docs/MODULE_INDEX.md docs/CODE_MAP.md docs/RELEASE_LEDGER.md docs/modules/sovushka-uikit.md pyproject.toml desktop/tauri/package.json desktop/tauri/package-lock.json desktop/tauri/src-tauri/Cargo.toml desktop/tauri/src-tauri/Cargo.lock desktop/tauri/src-tauri/tauri.conf.json docs/VERSIONING.md docs/SOFTWARE_VERSIONS.md
git diff --cached --check
git commit -m "refactor(ui): unify data workspace"
```

- [ ] **Step 8: Request final code review**

Invoke `superpowers:requesting-code-review` against the complete build 616 diff.
Resolve only evidence-backed findings, rerun affected focused tests plus
`make verify`, and report the exact final commit set and remaining live-runtime
acceptance limits.
