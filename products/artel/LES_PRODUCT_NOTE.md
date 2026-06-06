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

Current LES boundary:

- ARTEL backend calls LES `/api/search` for retrieval context.
- Revit add-ins should call ARTEL backend, not LES directly.
- LES should index structured `FamilyLearningCase` records, validation reports and catalog cards rather than raw RFA binaries alone.

