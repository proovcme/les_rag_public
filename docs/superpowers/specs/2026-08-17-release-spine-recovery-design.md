# LES Release Spine Recovery Design

**Status:** approved design for local review; implementation has not started.

**Decision owner:** Oleg
**Decision date:** 2026-08-17
**Canonical repository:** private `proovcme/les_rag`
**Canonical branch:** private `main` after controlled consolidation
**Public repository role:** release mirror of owner-accepted private release tags

## Goal

Turn the existing LES code into one reproducible multiplatform release line without losing the
current local work, weakening the evidence contract, or allowing the estimating module to own the
general product architecture.

The target product is a local evidence/RAG platform with:

- contract-versioned named dense and BM25 sparse vectors with Qdrant-native RRF;
- deterministic hierarchy, common reranking, parent/context expansion and exact evidence;
- project-scoped datasets, mailboxes and advisory memory;
- document classification, structural navigation, source viewing and controlled Office tools;
- IMAP and Outlook intake;
- a usable NiceGUI/Tauri interface;
- EXE and DMG installation plus explicit Git release and bounded VPS update paths;
- professional modules, including estimating, attached through explicit boundaries.

For this recovery, “learning” means evidence-gated project memory and confirmed precedents. Model
fine-tuning or autonomous weight updates are not part of the release-spine work.

## Current evidence

The audit on 2026-08-17 established these facts:

- private `origin/main` is `0.27.39` at `f3ee7fd`;
- the local checkout is based on a divergent branch with 7 local-only commits and is 17 commits
  behind private `main`;
- the working tree contains 95 tracked changes and 36 untracked files, including advanced RAG,
  document, UI and estimating work;
- public `main` is `0.25.0`, while public `release/0.27.35` is `0.27.85`;
- private PRs form a stack, but PR #14 is a sibling of the later #11-#13 line rather than its
  successor;
- PR #13 and PR #14 are divergent and overlap in version and estimating update files;
- private and public default branches are not protected and the inspected PRs have no approval;
- static version, lock, diff and publication checks pass, but the current broad test profile is not
  a trustworthy product-release proof;
- the local Legion runtime was not running during the audit, so no live acceptance was claimed.

This document treats code as the source of truth and the existing release narratives as evidence to
be reconciled, not as authority by themselves.

## Non-goals

The recovery does not:

- delete or reindex user datasets, Qdrant state, MetaDB, storage, mail or project data;
- restart or deploy a live runtime while Git history is being reconstructed;
- add dependencies;
- redesign the estimating algorithms or change model-owned estimating decisions;
- activate RAPTOR or ColBERT by default before their acceptance gate passes;
- publish, force-push, merge, tag or release without a separate owner acceptance;
- preserve every historical test merely because it exists;
- choose a new Windows Qdrant packaging strategy. The effective packaging from the selected
  canonical code is preserved and exposed in GUI diagnostics; changing Docker versus native
  Qdrant is a separate product decision.

## Release architecture

### 1. Platform spine

The platform spine owns version identity, persistent-state boundaries, runtime configuration,
process ownership, installer behavior, update/rollback and diagnostics. It must not depend on a
professional module.

Its release contract is:

- one `config/version.json` identity;
- one clean, pushed private commit;
- state separated from replaceable application files;
- effective paths, ports, providers and restart requirements visible in the GUI;
- recoverable update with an evidence file describing base commit, target commit, hashes and
  rollback result;
- no release asset publication until the installed application reaches terminal readiness.

### 2. Evidence core

The evidence core owns dataset intake, parsing state, the contract-clean Qdrant generation, lexical
projection, retrieval and source identity.

Its mandatory retrieval sequence is:

```text
explicit project/dataset/document scope
  -> named dense + BM25 sparse native RRF
  -> global evidence retained
  -> deterministic navigation and descendant RRF
  -> common reranker
  -> parent/context expansion
  -> exact source evidence
  -> model synthesis
  -> citation/evidence check
```

Hierarchy may narrow a descendant leg but may never hide the global evidence leg. A missing or
incompatible index contract fails closed and is visible to the operator. Successful documents are
not silently reindexed by recovery logic.

RAPTOR and ColBERT remain optional layers between hierarchy and the common reranker. They require
separate generations, bounded timeouts, circuit breakers, truthful trace and a fallback to the
mandatory native-RRF path. Their failure cannot make the core unavailable.

### 3. Knowledge-work layer

The knowledge-work layer owns document type/passport extraction, document and table registries,
exact readers, the local viewer and controlled DOCX/XLSX draft creation. It consumes source
identity from the evidence core and never invents a professional conclusion.

Office tools must:

- preserve originals;
- use exact source or registry identity;
- return provenance, missing fields and warnings;
- create append-only drafts with manifest and SHA-256;
- require explicit user confirmation before publishing an edited artifact.

### 4. Project context

A project is the explicit boundary that joins several ordinary datasets, one or more mailbox
datasets and project memory. Scope resolution returns the exact dataset IDs. Mailboxes remain
separate private datasets and are attached to a project through the same project-to-dataset link as
other sources.

Memory is advisory and project-scoped. Only evidence-gated facts or explicitly confirmed
precedents can be recalled. Memory is never evidence, never crosses projects and never chooses an
estimating norm.

### 5. User interface

The interface exposes the state of the preceding layers instead of duplicating their logic. The
minimum primary surfaces are Chat, Documents/Studio, Mail, Projects and Configuration/Diagnostics.

The UI must show:

- selected project, datasets, documents and mailbox scope;
- file readiness and parse/index blockers;
- effective retrieval pipeline and optional-stage status;
- clickable exact sources and document preview;
- memory mode and project boundary;
- installer/update status, restart requirements and rollback result;
- human-readable errors while preserving machine codes in trace.

### 6. Professional modules

Estimating and other professional modules consume the platform through explicit scope, tool,
evidence, memory and artifact ports. They may add their own datasets, typed stores, workflows and
acceptance gates, but they must not:

- change the general RAG contract;
- block ordinary project/document/mail chat when the module is unavailable;
- control the common product version independently;
- write professional visible finals from deterministic fallback code;
- leak their system datasets into ordinary project retrieval.

The core release and estimating-module acceptance are reported separately. A distribution may
contain the module only when its status is truthful; failure of its optional resources degrades that
module, not the platform spine.

## Git recovery design

### Phase A: immutable recovery evidence

Before any branch, reset, checkout, rebase or cherry-pick operation, create a recovery package
outside the repository. It contains:

- `git status --porcelain=v1`;
- current HEAD and all relevant local/remote refs;
- binary tracked diff from HEAD;
- an archive of only the 36 reported untracked source files;
- SHA-256 for every archived file and the diff;
- a manifest listing excluded secret/runtime/data roots;
- a successful restore probe into a temporary directory.

The package is not a release and is never copied to the public repository.

### Phase B: isolated canonical worktree

Create an isolated worktree and recovery branch from the fetched private `origin/main`. The current
dirty checkout remains untouched as a read-only source until the new line passes acceptance.

No bulk merge of the dirty checkout is allowed. Changes are replayed by behavior slice, with a clean
status and a reviewable diff after every slice.

### Phase C: ordered consolidation

Apply work in this order:

1. platform state, runtime ownership, version and installer/update fixes already accepted on private
   `main`;
2. mandatory RAG contract, catalog integrity, resumable indexing and source identity;
3. projects, mail, memory, document explorer, viewer and Office tool boundaries;
4. shared UI and GUI-first runtime diagnostics;
5. optional RAPTOR/ColBERT control plane and generations, disabled until accepted;
6. estimating adapter and owner-approved estimating fixes.

Each slice includes its focused acceptance evidence, module documentation, version only when a
release boundary is reached, and release-ledger update. Intermediate recovery commits do not invent
new public product versions.

### Phase D: private PR reconciliation

Do not merge the current stacked PRs directly. Inventory each commit from private PR #5 through
#14 against the consolidated tree and classify it as:

- already present;
- required and replayed;
- superseded by a verified implementation;
- estimating-only and deferred;
- rejected with a recorded reason.

PR #14 must be replayed after the accepted #11-#13 changes that it currently lacks. Conflicting
version-only edits are regenerated from the final `config/version.json`, not manually merged.

After owner review, obsolete PRs are closed with a pointer to the canonical replacement commit.

### Phase E: public release mirror

The public repository is produced only from an owner-accepted private release commit through an
explicit export manifest. The export removes private/runtime/data/secrets and records the private
source commit, public tree hash and artifact hashes.

Public history is preserved: no force-push is required. A release branch receives the exported tree
as a reviewable commit and reaches public `main` only through owner review. The same accepted source
identity builds the public tag, EXE, DMG, checksums and update manifests.

## Acceptance design

The release proof is a bounded product matrix, not a repository-wide pytest count. Unit tests remain
useful beneath it, but cannot substitute for these scenarios.

### Core offline contract gate

- version surfaces agree;
- tracked source contains no forbidden state or high-signal secrets;
- dependency lock is unchanged or explicitly approved;
- named dense and sparse vector schema is enforced;
- hierarchy preserves global evidence;
- project and memory isolation contracts hold;
- update allowlists, hashes and rollback contracts hold;
- code compiles and focused contract tests terminate within declared time budgets.

### Real-corpus evidence gate

Using a small owner-approved corpus containing PDF, DOCX, XLSX and EML:

1. create two document datasets and one mailbox dataset;
2. attach all three to one project;
3. inspect file type, structure and readiness in the UI;
4. ask one exact-file question and one cross-dataset project question;
5. prove named dense+sparse native RRF in the request trace;
6. prove hierarchy did not remove the global evidence leg;
7. open every cited source at the exact document/page or structured row;
8. record a confirmed project-memory fact, restart and recall it only in that project;
9. verify the same fact is absent from another project;
10. disconnect an optional RAPTOR/ColBERT layer and prove native-RRF fallback remains available.

### Windows installed gate

- install the built EXE into an isolated application root and isolated persistent state;
- reach terminal readiness and `/api/version` with the exact expected identity;
- execute the real-corpus evidence gate;
- exercise Outlook discovery/intake when classic Outlook is available;
- apply one compatible update and one deliberately failing update;
- prove automatic rollback and preservation of project, mail, memory and RAG state;
- uninstall application files without deleting persistent user state unless explicitly requested.

### macOS installed gate

- verify signature and DMG structure;
- install the app into an isolated root and start the packaged runtime;
- reach terminal readiness and exact `/api/version`;
- execute the same real-corpus evidence gate with the declared macOS provider profile;
- apply and roll back one compatible update;
- prove application replacement does not overwrite persistent state.

### Professional-module gate

The estimating module runs its owner-approved benchmark separately. Its result reports module
readiness but cannot turn a passing core gate into a false platform failure. Changes to protected
estimating behavior require the explicit benchmark from `AGENTS.md`.

## Failure handling

- Any operation that would overwrite the dirty checkout stops before mutation.
- A recovery manifest hash mismatch stops consolidation.
- A commit whose behavior cannot be attributed to a product slice is deferred, not merged.
- Index incompatibility yields a visible blocker and a sibling-generation path; it never triggers a
  silent in-place migration.
- Optional retrieval-stage failure records the stage and falls back to mandatory native RRF.
- Installer or updater failure preserves logs, restores the previous application tree and leaves
  persistent state untouched.
- Public export mismatch stops before tag or artifact publication.

## Completion criteria

Recovery is complete only when:

- private `main` is the sole documented source of truth;
- the canonical checkout is clean and all retained local changes have a disposition;
- the private PR stack is merged, superseded or deferred with recorded reasons;
- one version identity matches source, desktop packages, installers and update manifests;
- core offline, real-corpus, Windows installed and macOS installed gates are green;
- optional advanced RAG stages report truthful readiness and safe fallback;
- the estimating module is isolated and has its own status;
- public `main` and the public tag derive from the accepted private release manifest;
- EXE, DMG, checksums and rollback evidence are preserved;
- no user data, runtime state or secret entered either Git repository.

## Implementation boundary

This design authorizes preparation of a detailed implementation plan only after owner review. It
does not authorize commit, push, PR mutation, merge, tag, runtime restart, deployment or release.
