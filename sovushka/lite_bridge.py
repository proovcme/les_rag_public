"""Лёгкий мост и рантайм-роуты для внешнего контура.

W5.4/5.5 (решение оператора 2026-06-11): единственный UI — NiceGUI
(`/classic` чат, `/les/classic` админка). HTML-шеллы lite_chat/lite_admin
удалены; здесь живёт всё, что ОБЯЗАНО пережить удаление шеллов:

  • `/lite-api/*`  — мост на proxy (его используют les.ovc.me, M5, внешний
    smoke 12/12 и вьювер CAD/BIM);
  • `/lite-runtime/*` — локальные рантайм-действия (loopback/trusted only);
  • монтирование статики и страница вьювера CAD/BIM (`/les/cad-bim-viewer`);
  • редиректы `/` → `/classic`, `/les` и `/les/lite` → `/les/classic`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import mimetypes
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import Request, Response
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from sovushka.config import PROXY_URL, TRUSTED_NETWORK_ROLE, TRUSTED_PROXY_HEADER
from sovushka.trust import client_ip_from_request, trust_diagnostics, trusted_role_for_request


# ─────────────────────────────────────────────────────────────────────
# МОСТ /lite-api/*  (бывш. lite_chat.py)
# ─────────────────────────────────────────────────────────────────────

BRIDGE_PUBLIC_PATHS = {"/api/auth/verify", "/api/auth/trust"}


def _client_is_loopback(request: Request) -> bool:
    host = client_ip_from_request(request)
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def bridge_request_allowed(
    path: str,
    *,
    has_key: bool,
    is_loopback: bool,
    is_trusted_network: bool = False,
) -> bool:
    target_path = f"/api/{path.strip('/')}"
    return has_key or is_loopback or is_trusted_network or target_path in BRIDGE_PUBLIC_PATHS


def _forward_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": request.headers.get("accept", "application/json")}
    content_type = request.headers.get("content-type")
    api_key = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization")
    if content_type:
        headers["Content-Type"] = content_type
    if api_key:
        headers["X-API-Key"] = api_key
    if authorization:
        headers["Authorization"] = authorization
    trusted_role = trusted_role_for_request(request)
    if trusted_role:
        headers[TRUSTED_PROXY_HEADER] = trusted_role or TRUSTED_NETWORK_ROLE
        headers["X-Forwarded-For"] = client_ip_from_request(request)
    return headers


async def bridge_proxy_request(path: str, request: Request) -> Response:
    target_path = f"/api/{path.strip('/')}"
    if target_path == "/api/auth/trust":
        return JSONResponse(trust_diagnostics(request))

    has_key = bool(request.headers.get("x-api-key") or request.headers.get("authorization"))
    is_loopback = _client_is_loopback(request)
    is_trusted_network = bool(trusted_role_for_request(request))
    if not bridge_request_allowed(
        path,
        has_key=has_key,
        is_loopback=is_loopback,
        is_trusted_network=is_trusted_network,
    ):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    query = f"?{request.url.query}" if request.url.query else ""
    target_url = f"{PROXY_URL.rstrip('/')}{target_path}{query}"
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            proxied = await client.request(
                request.method,
                target_url,
                content=body or None,
                headers=_forward_headers(request),
            )
    except httpx.RequestError as error:
        return JSONResponse({"detail": f"Proxy unavailable: {error}"}, status_code=502)

    content_type = proxied.headers.get("content-type", "application/json")
    return Response(content=proxied.content, status_code=proxied.status_code, media_type=content_type)


# ─────────────────────────────────────────────────────────────────────
# ЛОКАЛЬНЫЕ РАНТАЙМ-ДЕЙСТВИЯ /lite-runtime/*  (бывш. lite_admin.py)
# ─────────────────────────────────────────────────────────────────────

LOCAL_RUNTIME_ACTIONS = {
    "start_indexer",
    "stop_indexer",
    "restart_proxy",
    "restart_mlx",
    "restart_qdrant",
    "restart_ui",
}


def local_runtime_action_allowed(*, is_loopback: bool, is_trusted_network: bool = False) -> bool:
    return is_loopback or is_trusted_network


def _local_runtime_request_allowed(request: Request) -> bool:
    return local_runtime_action_allowed(
        is_loopback=_client_is_loopback(request),
        is_trusted_network=bool(trusted_role_for_request(request)),
    )


def _runtime_result_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_runtime_result_payload(item) for item in value]
    try:
        return asdict(value)
    except TypeError:
        return value


def _runtime_action(name: str) -> Callable[[], Any]:
    from tools import les_runtime_control

    actions: dict[str, Callable[[], Any]] = {
        "start_indexer": lambda: les_runtime_control.start_service("indexer"),
        "stop_indexer": lambda: les_runtime_control.stop_service("indexer"),
        "restart_proxy": lambda: les_runtime_control.restart_service("proxy"),
        "restart_mlx": lambda: les_runtime_control.restart_service("mlx"),
        "restart_qdrant": lambda: les_runtime_control.restart_service("qdrant"),
        "restart_ui": lambda: les_runtime_control.restart_service("ui", False),
    }
    return actions[name]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _cad_bim_ifc_sample_dir(root: Path) -> Path:
    ifc_sample_dir = root / "ifc_sample"
    standalone_ifc_sample_dir = root / "standalone" / "cad_bim_viewer" / "ifc-sample"
    if not ifc_sample_dir.exists() and standalone_ifc_sample_dir.exists():
        return standalone_ifc_sample_dir
    return ifc_sample_dir


def _reindex_paths() -> dict[str, Path]:
    root = _repo_root()
    artifacts = root / "artifacts" / "reindex_runs"
    return {
        "artifacts": artifacts,
        "state": artifacts / "reindex_state_ntd_fire_index__ntd_hvac_index.json",
        "pid": artifacts / "guarded_reindex_hvac_fire.pid.json",
    }


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        status = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
        if status.startswith("Z"):
            return False
    except Exception:
        pass
    return True


def guarded_reindex_status_payload() -> dict[str, Any]:
    paths = _reindex_paths()
    pid_info: dict[str, Any] = {}
    if paths["pid"].exists():
        try:
            pid_info = json.loads(paths["pid"].read_text(encoding="utf-8"))
        except Exception:
            pid_info = {}
    pid = int(pid_info.get("pid") or 0)
    running = _pid_running(pid)

    state: dict[str, Any] = {}
    if paths["state"].exists():
        try:
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
        except Exception as error:
            state = {"error": str(error)}

    completed = state.get("completed") if isinstance(state, dict) else {}
    completed_count = len(completed) if isinstance(completed, dict) else 0
    return {
        "running": running,
        "pid": pid if running else None,
        "pid_file": str(paths["pid"]),
        "state_file": str(paths["state"]),
        "completed": completed_count,
        "total": 194,
        "remaining": max(0, 194 - completed_count),
        "updated_at": state.get("updated_at") if isinstance(state, dict) else None,
        "runs": len(state.get("runs") or []) if isinstance(state, dict) else 0,
        "last_log": pid_info.get("log_path"),
        "last_started_at": pid_info.get("started_at"),
    }


async def lite_runtime_status(request: Request) -> JSONResponse:
    if not _local_runtime_request_allowed(request):
        return JSONResponse({"detail": "Local runtime status requires trusted local access"}, status_code=403)

    from tools import les_runtime_control

    statuses = await asyncio.to_thread(
        les_runtime_control.all_statuses,
        ["qdrant", "mlx", "proxy", "indexer", "ui"],
    )
    return JSONResponse({"services": _runtime_result_payload(statuses)})


async def lite_reindex_status(request: Request) -> JSONResponse:
    if not _local_runtime_request_allowed(request):
        return JSONResponse({"detail": "Local reindex status requires trusted local access"}, status_code=403)
    return JSONResponse(guarded_reindex_status_payload())


async def lite_runtime_action(action: str, request: Request) -> JSONResponse:
    if action not in LOCAL_RUNTIME_ACTIONS:
        return JSONResponse({"detail": f"Unknown action: {action}"}, status_code=404)
    if not _local_runtime_request_allowed(request):
        return JSONResponse({"detail": "Local runtime actions require trusted local access"}, status_code=403)

    result = await asyncio.to_thread(_runtime_action(action))
    return JSONResponse({"action": action, "result": _runtime_result_payload(result)})


_VIEWER_NOT_BUILT_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LES АТЛАС</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #07090c; color: #f4f7fb; font: 14px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    main { width: min(680px, calc(100vw - 32px)); border: 1px solid #263748; border-radius: 8px; background: #10161d; padding: 22px; }
    h1 { margin: 0 0 10px; font-size: 18px; }
    p { color: #9fb0c1; line-height: 1.55; }
    code { color: #38bdf8; }
  </style>
</head>
<body>
  <main>
    <h1>LES АТЛАС не собран</h1>
    <p>Соберите frontend bundle:</p>
    <p><code>cd frontend/cad_bim_viewer && npm install && npm run build</code></p>
  </main>
</body>
</html>"""


def register_lite_bridge_routes() -> None:
    """Регистрирует мост, рантайм-роуты, статику вьювера и редиректы шеллов.
    HTML-шеллы lite_chat/lite_admin удалены — их адреса ведут в NiceGUI."""
    from nicegui import app

    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/javascript", ".mjs")
    repo_root = _repo_root()
    viewer_dist = repo_root / "frontend" / "cad_bim_viewer" / "dist"
    ifc_sample_dir = _cad_bim_ifc_sample_dir(repo_root)

    app.mount(
        "/les/cad-bim-viewer/assets",
        StaticFiles(directory=viewer_dist / "assets", check_dir=False),
        name="les_cad_bim_viewer_assets",
    )
    app.mount(
        "/les/cad-bim-viewer/web-ifc",
        StaticFiles(directory=viewer_dist / "web-ifc", check_dir=False),
        name="les_cad_bim_viewer_web_ifc",
    )
    app.mount(
        "/les/cad-bim-viewer/fragments",
        StaticFiles(directory=viewer_dist / "fragments", check_dir=False),
        name="les_cad_bim_viewer_fragments",
    )
    app.mount(
        "/les/cad-bim-viewer/ifc-sample",
        StaticFiles(directory=ifc_sample_dir, check_dir=False),
        name="les_cad_bim_viewer_ifc_sample",
    )

    # W5.4: корень и лайт-шеллы ведут в NiceGUI (шеллы удалены).
    @app.get("/")
    async def root_redirect():
        return RedirectResponse("/classic", status_code=307)

    @app.get("/les")
    @app.get("/les/")
    async def lite_admin_redirect():
        return RedirectResponse("/les/classic", status_code=307)

    @app.get("/les/lite")
    @app.get("/les/lite/")
    async def lite_admin_lite_redirect():
        return RedirectResponse("/les/classic", status_code=307)

    @app.api_route("/lite-api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def lite_api_bridge(path: str, request: Request):
        return await bridge_proxy_request(path, request)

    @app.get("/les/cad-bim-viewer")
    @app.get("/les/cad-bim-viewer/")
    async def cad_bim_viewer_page():
        index = viewer_dist / "index.html"
        if index.exists():
            return FileResponse(
                index,
                media_type="text/html",
                headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
            )
        return HTMLResponse(
            _VIEWER_NOT_BUILT_HTML,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/lite-runtime/status")
    async def lite_runtime_status_page(request: Request):
        return await lite_runtime_status(request)

    @app.get("/lite-runtime/reindex-status")
    async def lite_reindex_status_page(request: Request):
        return await lite_reindex_status(request)

    @app.post("/lite-runtime/action/{action}")
    async def lite_runtime_action_page(action: str, request: Request):
        return await lite_runtime_action(action, request)
