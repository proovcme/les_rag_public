# LES Products

LES is the integration spine for three product surfaces:

| Product | Path | State |
|---|---|---|
| LES | repository root | Runtime, RAG, installers, API and local data plane. |
| АТЛАС | `products/atlas`, `frontend/cad_bim_viewer`, `standalone/cad_bim_viewer` | Standalone CAD/BIM viewer package. |
| АРТЕЛЬ | `products/artel` | Revit family workflow prototype, API skeleton and legacy add-in source snapshot. |

## Repository Rule

The LES repository may contain product source, contracts, docs and reproducible packaging scripts. It must not contain local runtime data, private corpora, generated indexes, `node_modules`, build outputs, logs, Revit binary distributions or machine-specific settings.

## Product Boundaries

- LES owns retrieval, indexing, local runtime, API contracts and dataset routing.
- АТЛАС owns the WebGL viewer experience and standalone delivery.
- АРТЕЛЬ owns Revit family tasks, catalog, validation workflow and backend orchestration.
- АТЛАС and АРТЕЛЬ call LES APIs; they do not implement a second RAG.

## Release Surfaces

```text
les-*.tar.gz / les-*.zip      LES boxed runtime profiles
atlas-standalone.zip          offline/field viewer package
artel-mvp.zip                 ARTEL backend/UI/OpenAPI hand-test package
```

Build АТЛАС with:

```bash
npm ci --prefix frontend/cad_bim_viewer
npm run build --prefix frontend/cad_bim_viewer
npm run build:standalone --prefix frontend/cad_bim_viewer
uv run python tools/smoke_atlas_standalone.py
uv run python tools/check_atlas_bundle_budget.py
uv run python tools/build_atlas_release.py
```

Build АРТЕЛЬ MVP hand-test package with:

```bash
uv run python tools/build_artel_release.py
```
