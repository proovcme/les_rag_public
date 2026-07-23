# Legacy: object-estimate layer

> **Status since 0.24.0.20: retired from the product route.**
> User-facing Smeta mode must not enter this layer.
>
> Current principle: **модель первична и сама раскладывает объект, харнесс только даёт инструменты**.
> The working route is `estimate_harness_service.run_estimate_harness()`:
> the model proposes work items, the harness exposes `search_norm` / `add_position`,
> and code checks norm applicability, units, quantities, prices and evidence.

## Why This Page Exists

This document is now a tombstone for the older object-estimate experiment, not an instruction.
It remains only so historical tests, release notes and rollback discussions have a stable link.
Do not extend this layer for new object estimates.

## Product Route

Explicit `mode=smeta` resolves to `estimate_harness`.

The user question is passed with the current chat context. The model decides how to decompose the
object. The harness does not invent a house, a porch, a pile field, a roof or any other ready-made
scope. It only provides tools:

- `search_norm`: search the local GESN base for candidate norms and call the shared
  `candidate_selection_service` to return `candidate_selection_v1` with an explainable shortlist,
  score gap, top reasons and an action (`bind_top_candidate` only for a clear applicable leader;
  otherwise the model must choose from the shortlist or ask for missing data).
- `add_position`: add a checked position with quantity/unit constraints.
- calculation gates: applicability, unit compatibility, quantity sanity, price coverage and
  evidence status.

Since 0.24.0.101 the batch harness follows that contract explicitly: if `search_norm` returns an
ambiguous shortlist, it asks the model for a compact JSON choice over the returned `norm_code`
values (or an `ask_user` question). The harness rejects codes outside the shortlist and never falls
through to the first applicable candidate on its own. Only after this model choice does
`add_position` run the calculator gates.

Since 0.24.0.102 `work_family` and `element_type` are also owned by the model. The harness no
longer rewrites them from text regexes before `search_norm`; it only normalizes mechanical aliases
for action and unit. Text-based mismatches may appear as non-binding `intent_hints` in the trace,
but they are not used as search or calculation inputs.

Since 0.24.0.103 the older stepwise `{tool,args}` estimate loop is no longer an execution path.
The product route has one model contract: `smeta_work_plan_v1`. If a model emits an old tool-call,
the harness asks it to repair the same intent into the batch JSON contract; it does not run a second
prompt or a parallel estimator protocol.

Since 0.24.0.104 the batch tool contract is deliberately thin: it describes only the JSON transport
shape and allowed machine ids. Estimator behavior belongs to `config/prompts/smeta_estimator_role.json`
and `skills/smeta/SKILL.md`. The role-pack now tells the model how to treat nested BOR/BOM structures
such as "quantity for 1 item" under a parent count, and how to avoid double-counting a parent assembly
line together with its detailed child work rows. Object-area extraction also refuses to use arbitrary
work-row areas like `0.07 м2/шт` as object geometry; only explicit object/building/total-area wording
can create `object_area_m2`.

Since 0.24.0.105 raw numeric extraction and calculator slots are separated. `parse_params()` may find
direct quantities (`volume_m3`, `area_m2`, `mass_t`, `piece_count`) in the question, file text or VOR
snippets; the harness exposes them as `quantity_candidates` with provenance. Outside a narrow direct
work request ("calculate this work with this quantity"), those direct quantities are not global
calculator inputs. The estimator model must bind the right candidate into the `slots` of a specific
work item. Geometry/applicability parameters such as depth, wall thickness, wall height/length,
pile count and soil group may still flow as safe global slots.

Since 0.24.0.106 the chat orchestration gives the model-owned work-plan a larger dynamic completion
budget for long TZ/BOR/attachment contexts and passes the same harness question to the visible
estimator comment. The comment layer receives only a compact excerpt and is forbidden, then
post-filtered, from claiming that a file or VOR is truncated unless that is present in the calculation
payload. This prevents the visible layer from asking for "continuation of the TZ" just because it saw
only the beginning of a long attachment.

Since 0.24.0.107 a fully blocked harness is no longer allowed to be the visible smeta answer. If
`add_position`/norm binding rejects every work item and no computed row exists, the same model gets the
full harness question plus a compact "blocked harness advisory" and writes the visible estimator answer
itself: work/quantity schedule, what is supply/material, what needs GESN/FGIS/KAC/quote/region, and the
next practical step. The blocked harness remains trace/artifact evidence; it is not presented as the
main answer.

Since 0.24.0.108 explicit Smeta mode starts from the opposite end: the estimator model answers directly
from the full question, attachment context and smeta skill, without first running the code harness. The
old harness stays available as a fallback and future calculator/provenance layer, but it no longer
pre-filters whether the visible answer may exist. This is controlled by `LES_SMETA_DIRECT_MODEL_FIRST`
(default on for explicit Smeta, off for auto-routed work estimates).

Since 0.24.0.109 direct Smeta mode also gets a compact RAG packet when the operator selected a dataset,
project scope or target file: top retrieved chunks, source map and navigation memory. This packet is
context for the estimator model, not a deterministic answer; the harness still does not pre-filter the
visible estimate.

Since 0.24.0.110 that RAG packet is guarded by explicit scope. An attachment-only estimate must not let
query classification infer a generic TABLE/broad corpus and mix unrelated RAG fragments into the model
answer. If the operator only attaches an XLSX/DOCX/PDF, the attachment itself is the input; RAG joins
only after a dataset/project scope is selected.

Since 0.24.0.113 the short-lived table calculator context was removed from direct Smeta. Attached
tables are again passed to the estimator model as source text, not as a code-built intermediate layer.
The spec-to-VOR bridge is model behavior, not code behavior:

- VOR rows define works and quantities.
- Specification rows define materials, equipment, packaging, mass, supplier/price notes and supply
  constraints.
- If the user gives only a specification, the model should first propose/build a VOR and then explain
  how to estimate it.
- Nested "for one item" rows must be multiplied by the parent quantity.
- Parent assembly rows must not be double-counted when detailed child work/material rows already
  describe the scope.

If the model cannot produce enough checked positions, the answer must say what is missing. It must
not substitute a prewritten object composition.

## Code Boundaries

- Current route: `proxy/services/estimate_harness_service.py`
- Mode/profile mapping: `proxy/services/profile_resolver.py`
- Chat entry point: `proxy/routers/chat.py`
- Removed experiment: `proxy/services/object_estimate_service.py`
- Removed data file: `config/domain/object_templates.yaml`

Shared arithmetic helpers that were still useful to the harness moved to
`proxy/services/estimate_math_service.py`.

## Regression Guard

The important regression is simple: phrases like “дай смету на дом 150 м2” must not be captured by
the old deterministic object-estimate channel. In explicit Smeta mode they go to the model-first
harness; in auto routing they do not select a retired object-estimate tool.
