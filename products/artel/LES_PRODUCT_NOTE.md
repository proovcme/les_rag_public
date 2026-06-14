# АРТЕЛЬ In LES

This folder is a curated source snapshot of the ARTEL project brought into the LES repository.

Included:

- static UI prototype in `app/`;
- backend/OpenAPI skeleton in `backend/Agnostis.Api` and `openapi/`;
- ARTEL documentation in `docs/`;
- Codex skill in `skills/agnostis`;
- legacy Revit add-in source under `MyVeras.*`.

Excluded:

- nested `.git` and GitHub Pages workflow state;
- `Dist`;
- `bin`;
- `obj`;
- `.DS_Store`;
- binary build outputs.

Known naming debt:

- The product name is АРТЕЛЬ.
- Several technical paths, namespaces and legacy projects still use `Agnostis`, `Agnosis` or `MyVeras`.
- Rename this mechanically only after the LES/ARTEL integration contracts are stable.

Product boundary (revised 2026-06-14):

- **АРТЕЛЬ is a standalone Windows product and must work fully without LES.** LES
  is an optional enrichment API, not a dependency. See
  [docs/les-integration.md](docs/les-integration.md) for the degradation ladder.
- The deterministic core (FOP resolution, archetype geometry, action-plan
  compiler, archetype classifier) runs offline with no LES and no model. It is
  specified/conformance-tested in Python in the LES repo (`tools/artel_family_*`,
  `tools/artel_archetype_classifier`, golden plans in `conformance/`) and ported
  to C# inside `Agnostis.Api` for the shipped package.
- Revit add-ins call the local ARTEL backend, never LES directly.
- When reachable, ARTEL backend calls LES `/api/search` (best-effort) for
  cross-project retrieval; LES should index `FamilyLearningCase` records,
  validation reports and catalog cards rather than raw RFA binaries alone.

