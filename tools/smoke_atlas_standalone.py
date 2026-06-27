"""Smoke-test the boxed ATLAS standalone folder."""

from __future__ import annotations

import argparse
import contextlib
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "standalone" / "cad_bim_viewer"
STATIC_PATHS = (
    "/",
    "/assets/index.js",
    "/assets/index.css",
    "/fragments/worker.mjs",
    "/web-ifc/web-ifc.wasm",
    "/web-ifc/web-ifc-mt.wasm",
    "/web-ifc/web-ifc-node.wasm",
)


def find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get(url: str, timeout: float = 5.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read()


def wait_until_ready(base_url: str, deadline: float) -> None:
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            get(base_url)
            return
        except Exception as exc:  # noqa: BLE001 - surfaced after deadline.
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"ATLAS server did not become ready: {last_error}")


def smoke(source: Path, port: int | None = None) -> None:
    script = source / "serve.sh"
    if not script.is_file():
        raise FileNotFoundError(script)

    selected_port = port or find_free_port()
    base_url = f"http://127.0.0.1:{selected_port}"
    process = subprocess.Popen(
        [str(script), str(selected_port)],
        cwd=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_until_ready(base_url, time.time() + 10)
        html = get(base_url + "/").decode("utf-8", errors="replace")
        if "АТЛАС Standalone" not in html:
            raise RuntimeError("ATLAS title not found in standalone HTML")

        for path in STATIC_PATHS[1:]:
            body = get(base_url + path)
            if not body:
                raise RuntimeError(f"{path} returned an empty body")

        default_model = json.loads(get(base_url + "/api/default-model").decode("utf-8"))
        if not default_model.get("found"):
            raise RuntimeError("/api/default-model did not find a model")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test ATLAS standalone folder.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    smoke(args.source, args.port)
    print("ATLAS standalone smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

