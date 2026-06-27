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

- `search_norm`: search the local GESN base for candidate norms.
- `add_position`: add a checked position with quantity/unit constraints.
- calculation gates: applicability, unit compatibility, quantity sanity, price coverage and
  evidence status.

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
