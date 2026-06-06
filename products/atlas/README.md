# АТЛАС

АТЛАС is the LES CAD/BIM viewer product. It has two forms:

- source viewer: `frontend/cad_bim_viewer`;
- boxed standalone runtime: `standalone/cad_bim_viewer`.

The standalone package is designed for a nearly bare workstation: browser, local static server script, bundled JS/CSS, ThatOpen worker, `web-ifc` WASM files and demo JSON. It does not require LES, npm or internet access after packaging.

## Build

```bash
npm ci --prefix frontend/cad_bim_viewer
npm run build --prefix frontend/cad_bim_viewer
npm run build:standalone --prefix frontend/cad_bim_viewer
uv run python tools/smoke_atlas_standalone.py
uv run python tools/build_atlas_release.py
```

The release artifact is written to:

```text
dist/atlas-standalone.zip
```

## Box Contents

The release zip includes:

- `index.html`;
- bundled `assets/index.js` and `assets/index.css`;
- ThatOpen fragment worker;
- `web-ifc` WASM files;
- `models/demo.cad_bim_graph.json`;
- `serve.sh`;
- `serve.ps1`;
- `README.md`;
- generated `ATLAS_MANIFEST.json`.

Ignored private folders such as `standalone/cad_bim_viewer/JSON` and `standalone/cad_bim_viewer/ifc-sample` are intentionally not included.

## Smoke Gate

`tools/smoke_atlas_standalone.py` starts the bundled server, verifies:

- `/` returns the standalone HTML;
- `/api/default-model` finds a demo/default model;
- `assets/index.js`, `assets/index.css`, `fragments/worker.mjs` and the WASM files are present.

Browser-level smoke should still be run before a public release when the viewer UI changes.

