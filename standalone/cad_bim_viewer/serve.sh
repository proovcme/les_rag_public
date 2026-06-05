#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 - "${1:-8095}" <<'PY'
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import pathlib
import sys
from urllib.parse import quote

PORT = int(sys.argv[1])
ROOT = pathlib.Path.cwd()
SUPPORTED = {".ifc", ".ifczip", ".json"}

mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/octet-stream", ".ifc")
mimetypes.add_type("application/octet-stream", ".ifczip")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/default-model":
            self.write_default_model()
            return
        super().do_GET()

    def write_default_model(self):
        models_root = ROOT / "models"
        files = []
        if models_root.is_dir():
            files = [item for item in models_root.iterdir() if item.is_file() and item.suffix.lower() in SUPPORTED]
        if not files:
            self.write_json({"found": False, "message": "В папке models нет файлов .ifc, .ifczip или .json."}, 404)
            return
        selected = max(files, key=lambda item: (item.stat().st_mtime, item.name.lower()))
        kind = "json" if selected.suffix.lower() == ".json" else "ifc"
        self.write_json(
            {
                "found": True,
                "name": selected.name,
                "kind": kind,
                "url": f"models/{quote(selected.name)}",
                "updated_at": selected.stat().st_mtime,
                "size": selected.stat().st_size,
            }
        )

    def write_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
print(f"VIZOR Standalone: http://0.0.0.0:{PORT}/")
server.serve_forever()
PY
