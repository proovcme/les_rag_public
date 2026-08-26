# Estimator LSR/VOR Tool Slice Design

> **SUPERSEDED:** This temporary `estimate_*` bridge is not part of the active
> architecture. Use the canonical `build_lsr_workbook` / `build_vor_workbook`
> contracts defined in
> [2026-08-26-canonical-tool-context-memory-update-design.md](2026-08-26-canonical-tool-context-memory-update-design.md).

**Status:** approved direction, implementation pending
**Target:** planned lightweight GitHub patch release `0.28.3`, after full installer/profile/channel release `0.28.2`

## Goal

Expose the existing verified estimate-document application as a small set of
provider-neutral tools that local Qwen 3.5 9B can select explicitly. Preserve the
LES invariant: the model chooses the workflow and professional mapping; code
reads, validates, calculates, checkpoints and writes a clearly marked draft.

This release does not restore the removed specialized smeta chat route and does
not modify `proxy/smeta_core/**`. It adds a thin adapter around
`run_smeta_document_application` and its existing checkpoint/stream contract.
It adds no dependency, bootstrap or native-shell change and therefore must be
published as `les-update.json` + `les-patch.zip`, without `LES-Setup.exe`.

## What is retained from public PR #13

- async `token_sink` propagation through the long estimate application;
- `smeta_step` and `smeta_row` progress in the ordinary chat stream;
- no client retry after any progress has been received;
- a one-hour client read timeout for a local long-running workflow;
- exact attachment intake and an append-only VOR/LSR draft artifact;
- the `dataset_ids is None` boundary fix.

The PR is reference material, not a commit to cherry-pick. Its hidden regex
fallback, automatic estimator-profile activation and unconditional exposure of
workbook tools are explicitly rejected.

## Canonical tools

Only the `estimator` profile may receive these factory capabilities:

1. `estimate_inspect_attachment` (`read`) — resolve one server-owned attachment,
   report type/fingerprint, exact intake summary, supported operations and
   `MISSING` fields. It creates no artifact.
2. `estimate_get_lsr_status` (`read`) — return a compact safe view of the
   checkpoint, accepted-row counts and downloadable artifact references. It does
   not expose the internal audit conversation.
3. `estimate_build_vor_draft` (`draft`) — build an append-only VOR draft from the
   exact intake/specification rows with source provenance. It neither chooses
   norms nor prices work.
4. `estimate_build_lsr_draft` (`draft`) — invoke the existing application adapter,
   resume by attachment/checkpoint identity, stream progress and return a typed
   `priced_draft` result.

Names are ASCII `snake_case`; arguments and results use JSON-schema-compatible
objects. Draft creation is allowed automatically after the model explicitly
calls a tool. Finalization, profile activation, external publication and
destructive replacement remain explicit user actions.

## Selection and profile policy

- No regex or deterministic intercept may manufacture a tool call.
- A model response with no tool call creates no workbook.
- Shortlisting is query-relevant and honors its limit. LSR/VOR tools are not
  pinned for unrelated questions.
- Ordinary `agent`, `search` and `engineer` factory profiles do not receive draft
  tools.
- A fresh database seeds the newest estimator factory revision. On upgrade, LES
  creates at most one proposed estimator revision and never changes the active
  revision. The UI offers an explicit `Применить обновление` action.
- Existing chat bindings remain immutable snapshots until the operator applies a
  revision to that chat.

## Runtime and context contract

The 9B acceptance path exposes at most three relevant tools per selection turn.
The model performs one explicit selection at a time; the existing application
handles bounded five-row batches internally and checkpoints every accepted
batch. Tool results inserted into chat contain only status, counts, `MISSING`,
warnings, checkpoint reference and artifact reference. Full row traces and audit
history remain in durable storage, outside the prompt.

The `0.28.3` slice adds only this narrow compaction boundary. The general
`ContextGovernor`, memory projection and Qwen 9B/35B presets remain owned by
`0.29.0`; the four contracts above must migrate into that canonical registry
without changing names or semantics.

## Streaming, cancellation and retry

- The server forwards `smeta_step` and `smeta_row` through the existing SSE queue.
- While a long tool is awaiting a row, the chat route emits a semantic heartbeat
  every 15 seconds. A heartbeat is progress, not generated answer text.
- Once any heartbeat, `smeta_step` or `smeta_row` arrives, the UI must never retry
  `/api/chat`; retry would duplicate a draft run.
- Stop/disconnect cancels the waiting chat task. The last completed checkpoint and
  original attachment remain reusable; partial artifacts are never presented as
  final.
- `estimate_build_lsr_draft` is retry-safe only through the same attachment and
  checkpoint identity. A new identity starts a new append-only run.

## Result contract

All four tools return `les_tool_result_v1`. A successful LSR result includes:

```json
{
  "status": "ok|partial|missing|error",
  "result": {
    "document_state": "priced_draft",
    "attachment_id": "server-owned id",
    "checkpoint": {"state": "active|complete", "accepted_rows": 0},
    "artifact": {"kind": "xlsx", "download_id": "opaque id"}
  },
  "missing": [],
  "warnings": [],
  "evidence": [],
  "trace": "bounded execution summary"
}
```

`ok` requires a downloadable artifact. `partial` is visibly a draft and carries
the unresolved rows. Filesystem paths and internal audit messages are never sent
to the model or browser.

## Acceptance

The release is accepted only when deterministic tests prove all of the following:

- explicit estimator tool call produces a draft; no call produces none;
- unrelated Agent sessions cannot see or execute draft tools;
- upgrade discovery does not change the active estimator revision or old chats;
- progress suppresses retry, and cancellation preserves a resumable checkpoint;
- resume does not duplicate accepted rows or artifacts;
- compact result stays bounded for 9B;
- the protected quality benchmark still returns 5/5 on Qwen 3.5 9B;
- no file under `proxy/smeta_core/**` changed.
