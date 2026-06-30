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
