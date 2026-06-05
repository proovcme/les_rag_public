#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIEWER="$ROOT/frontend/cad_bim_viewer"
OUT="$ROOT/standalone/cad_bim_viewer"

PRESERVE_DIR="$(mktemp -d)"
trap 'rm -rf "$PRESERVE_DIR"' EXIT
if [[ -d "$OUT" ]]; then
  for item in INSTALL_FOR_LOCIA.cmd install_for_locia.ps1 JSON ifc-sample; do
    if [[ -e "$OUT/$item" ]]; then
      cp -R "$OUT/$item" "$PRESERVE_DIR/"
    fi
  done
fi

rm -rf "$OUT"
mkdir -p "$OUT/assets" "$OUT/fragments" "$OUT/web-ifc" "$OUT/models"

JS_ASSET="$(find "$VIEWER/dist/assets" -maxdepth 1 -type f -name 'index-*.js' | head -n 1)"
CSS_ASSET="$(find "$VIEWER/dist/assets" -maxdepth 1 -type f -name 'index-*.css' | head -n 1)"
if [[ -z "$JS_ASSET" || -z "$CSS_ASSET" ]]; then
  echo "Missing Vite index assets in $VIEWER/dist/assets" >&2
  exit 1
fi

cat > "$OUT/index.html" <<'HTML'
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LES CAD/BIM Вьюер</title>
    <link rel="stylesheet" href="assets/index.css" />
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="assets/index.js"></script>
  </body>
</html>
HTML
cp "$JS_ASSET" "$OUT/assets/index.js"
cp "$CSS_ASSET" "$OUT/assets/index.css"
cp "$VIEWER/dist/fragments/worker.mjs" "$OUT/fragments/worker.mjs"
cp "$VIEWER/dist/web-ifc/"*.wasm "$OUT/web-ifc/"
cp "$VIEWER/standalone/serve.sh" "$OUT/serve.sh"
cp "$VIEWER/standalone/serve.ps1" "$OUT/serve.ps1"
chmod +x "$OUT/serve.sh"
cp "$VIEWER/standalone/README.md" "$OUT/README.md"
cp "$VIEWER/standalone/models/"*.json "$OUT/models/"

for item in INSTALL_FOR_LOCIA.cmd install_for_locia.ps1 JSON ifc-sample; do
  if [[ -e "$PRESERVE_DIR/$item" ]]; then
    cp -R "$PRESERVE_DIR/$item" "$OUT/"
  fi
done

echo "Standalone CAD/BIM viewer written to $OUT"
