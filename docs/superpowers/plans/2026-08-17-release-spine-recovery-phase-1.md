# LES Release Spine Recovery Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this
> plan inline. Subagent execution is not authorized for this task. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Preserve every local source change, establish an isolated canonical worktree from private
`origin/main`, and produce an evidence-backed disposition inventory for the dirty tree and private
PR stack without changing runtime or publishing Git state.

**Architecture:** The current dirty checkout remains a read-only recovery source. A checksummed
package outside the repository proves that tracked and untracked source can be restored. All
consolidation work happens in a separate worktree based on the fetched private `origin/main`.

**Tech Stack:** Git, GitHub CLI, PowerShell 7, Python 3.12 through the existing uv environment.

## Global Constraints

- Do not commit, push, open or mutate PRs, merge, tag, deploy, restart services or release.
- Do not delete, move or read `.env`, credentials, `data/`, `storage/`, `RAG_Content/`, logs or
  runtime archives.
- Do not modify `proxy/smeta_core/**` or estimating behavior in Phase 1.
- Do not run a full reindex or mutate Qdrant/MetaDB.
- Preserve the current checkout exactly after the recovery package is created.
- Replace the normal commit step with a checksummed local checkpoint because repository policy
  explicitly defers commits until owner acceptance.
- Treat the existing broad pytest suite as diagnostic inventory, not release proof.

---

### Task 1: Capture immutable recovery evidence

**Files:**

- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\manifest.json`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\tracked.patch`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\untracked\...`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\refs.txt`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\status.txt`

**Interfaces:**

- Consumes: current checkout at `C:\Users\Oleg\les_rag`.
- Produces: a source-only, SHA-256-verified recovery package and a restore-probe result.

- [ ] **Step 1: Resolve and validate the recovery target**

Resolve `C:\Users\Oleg\les_rag_recovery\2026-08-17` and assert it is outside
`C:\Users\Oleg\les_rag`. Refuse to continue if the target already contains a manifest whose
source HEAD or status differs from the current checkout.

- [ ] **Step 2: Record status and refs**

Record `git status --porcelain=v1`, current HEAD, branch, `origin/main`, public refs and all private
PR head/base SHAs relevant to PR #5-#14. Do not record environment variables or Git credentials.

- [ ] **Step 3: Export the tracked binary diff**

Run:

```powershell
git diff --binary --full-index HEAD --output <recovery-root>\tracked.patch
```

Verify that `git apply --check --binary` accepts the patch against a temporary worktree at the
current HEAD.

- [ ] **Step 4: Copy only Git-reported untracked source files**

Use `git ls-files --others --exclude-standard` as the complete allowlist. Refuse any path under
`.env`, `data`, `storage`, `RAG_Content`, `logs`, `.venv`, `dist`, `local_private_archive` or an
exporter artifact directory. Copy the remaining paths with their repository-relative structure.

- [ ] **Step 5: Create the SHA-256 manifest**

The manifest records source root, HEAD, branch, timestamp, tracked patch hash, every untracked file
path/hash/size, excluded roots, tracked/untracked counts and the restore-probe verdict.

- [ ] **Step 6: Verify the package**

Recompute every hash and compare the package inventory with fresh Git status. Expected result:
`verified=true`, 95 tracked status entries, 37 untracked status entries, 38 untracked source files,
and no forbidden path. Porcelain status collapses the two approved files under `docs/superpowers/`
into one directory entry; `git ls-files --others --exclude-standard` remains the authoritative
38-file inventory.

- [ ] **Step 7: Checkpoint without commit**

Write `checkpoint-phase-1-recovery.json` beside the manifest with the manifest SHA-256 and exact
verification result. Do not create a Git commit.

### Task 2: Create the isolated canonical worktree

**Files:**

- Create directory: `C:\Users\Oleg\les_rag\.worktrees\release-spine-recovery`
- Branch: `codex/release-spine-recovery`

**Interfaces:**

- Consumes: fetched private `origin/main` at `f3ee7fd4f40d58980c0346f621efdfc480fd6c39` or a newer
  SHA discovered before worktree creation.
- Produces: clean isolated worktree with no source changes.

- [ ] **Step 1: Detect existing isolation**

Compare `git rev-parse --git-dir` and `git rev-parse --git-common-dir`, and confirm the current
checkout is not a submodule.

- [ ] **Step 2: Validate worktree location**

Check whether `.worktrees` is ignored. If it is not ignored, stop: repository policy forbids an
uncommitted `.gitignore` workaround in the dirty source checkout. In that case use the external
directory `C:\Users\Oleg\les_rag_worktrees\release-spine-recovery` after validating its absolute
path.

- [ ] **Step 3: Refresh private main without modifying source files**

Run `git fetch origin main`, record the fetched SHA and ensure it is an ancestor or deliberate
successor of the audited `f3ee7fd` baseline.

- [ ] **Step 4: Create the worktree and branch**

Run `git worktree add <validated-path> -b codex/release-spine-recovery origin/main`. If the branch
or path already exists, inspect it and reuse it only when HEAD equals the fetched canonical SHA and
the worktree is clean.

- [ ] **Step 5: Verify clean baseline**

Run from the new worktree:

```powershell
git status --short --branch
git diff --check
C:\Users\Oleg\les_rag\.venv\Scripts\python.exe tools\sync_version_contract.py --check
C:\Users\Oleg\les_rag\.venv\Scripts\python.exe -m compileall -q backend proxy sovushka tools sovushka_ng.py proxy_server.py mlx_host.py
C:\Users\Oleg\les_rag\.venv\Scripts\python.exe tools\publication_check.py
```

Expected: clean branch, synchronized version, successful compilation and publication check.

- [ ] **Step 6: Checkpoint without commit**

Write `checkpoint-phase-1-worktree.json` in the external recovery package with worktree path, branch,
HEAD and check results.

### Task 3: Inventory local commits and dirty changes by product slice

**Files:**

- Create in canonical worktree: `docs/release/RELEASE_SPINE_RECOVERY_INVENTORY.md`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\dirty-numstat.tsv`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\dirty-files.txt`

**Interfaces:**

- Consumes: recovery manifest, local-only commits and dirty diff.
- Produces: one disposition row for every changed/untracked path and every local-only commit.

- [ ] **Step 1: Export mechanical inventories**

Record `git diff --numstat HEAD`, `git diff --name-status HEAD`, untracked names and the seven
local-only commit summaries.

- [ ] **Step 2: Classify product slices**

Assign every path to exactly one slice:

```text
platform
rag-core
project-mail-memory-documents
ui
advanced-rag-optional
smeta-module
tests-docs-version
```

- [ ] **Step 3: Identify cross-slice files**

Mark files such as `proxy/app.py`, `proxy/routers/chat.py`, `Makefile`, version surfaces and release
docs as integration files. They are replayed after their leaf services, not copied first.

- [ ] **Step 4: Record initial disposition**

Use only these statuses: `replay`, `already-in-main`, `defer-smeta`, `superseded`, `integration-last`,
or `needs-owner-decision`. Include source commit/path and reason for every row.

- [ ] **Step 5: Verify coverage**

Compare the inventory against the recovery manifest. Expected: no missing or duplicate path and all
seven local-only commits represented.

### Task 4: Inventory private PR #5-#14 against canonical main

**Files:**

- Modify in canonical worktree: `docs/release/RELEASE_SPINE_RECOVERY_INVENTORY.md`
- Create outside repository: `C:\Users\Oleg\les_rag_recovery\2026-08-17\private-pr-5-14.json`

**Interfaces:**

- Consumes: GitHub PR metadata, commits, changed files and canonical main.
- Produces: one disposition for every PR commit without merging any PR.

- [ ] **Step 1: Fetch structured PR evidence**

For each PR #5-#14 record base/head, commit SHAs, changed files, checks, review state and mergeability.

- [ ] **Step 2: Reconstruct topology**

Document the linear #5-#10 chain, the #11-#13 continuation and the sibling #14 branch. Record the
exact common ancestor and version collision.

- [ ] **Step 3: Compare behavior against canonical and dirty source**

Classify each commit as `already-in-main`, `required-replay`, `superseded`, `defer-smeta` or
`rejected`. Version-only commits inherit the disposition of their behavior commit and are never
replayed independently.

- [ ] **Step 4: Verify complete PR coverage**

Expected: every commit from every PR has one disposition, and PR #14 is ordered after accepted
#11-#13 behavior.

### Task 5: Define the next bounded consolidation plans

**Files:**

- Create: `docs/superpowers/plans/2026-08-17-release-spine-rag-core.md`
- Create: `docs/superpowers/plans/2026-08-17-release-spine-project-context.md`
- Create: `docs/superpowers/plans/2026-08-17-release-spine-ui-platform.md`
- Create: `docs/superpowers/plans/2026-08-17-release-spine-smeta-adapter.md`

**Interfaces:**

- Consumes: the verified recovery and disposition inventories.
- Produces: four independently reviewable implementation plans with exact files and acceptance
  scenarios.

- [ ] **Step 1: Write the mandatory RAG-core plan**

Cover contract-clean named dense+sparse native RRF, hierarchy, catalog integrity, resumable parse,
source identity and optional RAPTOR/ColBERT fallback.

- [ ] **Step 2: Write the project-context plan**

Cover projects, multiple datasets, mailbox datasets, project memory, document explorer/viewer and
Office tools.

- [ ] **Step 3: Write the UI/platform plan**

Cover GUI-first configuration, installers, Git/VPS updater, rollback and Windows/macOS installed
acceptance.

- [ ] **Step 4: Write the estimating-adapter plan**

Restrict this plan to isolation and port integration. Any protected estimating behavior remains
deferred until explicit benchmark authorization.

- [ ] **Step 5: Self-review all plans**

Check exact file coverage, interface consistency, absence of placeholders and separation of core
release versus professional-module acceptance.

## Phase 1 completion

Phase 1 is complete when the recovery package verifies, the isolated worktree is clean, every local
change and PR commit has a disposition, and the next four plans are reviewable. No commit or remote
mutation is part of Phase 1.
