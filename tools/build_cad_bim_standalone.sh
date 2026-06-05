#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIEWER="$ROOT/frontend/cad_bim_viewer"
OUT="$ROOT/standalone/cad_bim_viewer"

rm -rf "$OUT"
mkdir -p "$OUT/assets" "$OUT/fragments" "$OUT/web-ifc" "$OUT/models"

cp "$VIEWER/dist/index.html" "$OUT/index.html"
cp "$VIEWER/dist/assets/index.js" "$OUT/assets/index.js"
cp "$VIEWER/dist/assets/index.css" "$OUT/assets/index.css"
cp "$VIEWER/dist/fragments/worker.mjs" "$OUT/fragments/worker.mjs"
cp "$VIEWER/dist/web-ifc/web-ifc.wasm" "$OUT/web-ifc/web-ifc.wasm"
cp "$VIEWER/standalone/serve.sh" "$OUT/serve.sh"
cp "$VIEWER/standalone/serve.ps1" "$OUT/serve.ps1"
chmod +x "$OUT/serve.sh"
cp "$VIEWER/standalone/README.md" "$OUT/README.md"
cp "$VIEWER/standalone/models/"*.json "$OUT/models/"

echo "Standalone CAD/BIM viewer written to $OUT"
