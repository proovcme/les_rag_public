from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI

from proxy.security import require_admin, require_user
from proxy.services.les_module_contracts import ModuleManifest


def _manifest(tmp_path: Path, module_id: str, **changes) -> ModuleManifest:
    skill = tmp_path / module_id / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"# {module_id}\n", encoding="utf-8")
    values = {
        "api_version": "1.0",
        "module_id": module_id,
        "title": module_id,
        "icon": "o_extension",
        "router_factories": (),
        "panel_builder": None,
        "chat_handler_factories": (),
        "skill_path": str(skill),
        "capabilities": (),
    }
    values.update(changes)
    return ModuleManifest(**values)


def _dependency_calls(router: APIRouter) -> set[object]:
    return {
        dependency.call
        for route in router.routes
        for dependency in getattr(route, "dependant", ()).dependencies
    }


def test_duplicate_module_route_is_rejected_before_mount(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import (
        ModuleMountError,
        module_routers,
        validate_route_collisions,
    )

    first = APIRouter()
    second = APIRouter()
    first.add_api_route("/api/shared", lambda: {}, methods=["GET"])
    second.add_api_route("/api/shared", lambda: {}, methods=["GET"])
    manifests = (
        _manifest(tmp_path, "alpha", router_factories=("modules.alpha:create_router",)),
        _manifest(tmp_path, "beta", router_factories=("modules.beta:create_router",)),
    )
    factories = {
        "modules.alpha:create_router": lambda: first,
        "modules.beta:create_router": lambda: second,
    }

    mounted = module_routers(manifests, resolve_entry_point=factories.__getitem__)

    with pytest.raises(ModuleMountError) as error:
        validate_route_collisions((), mounted)
    assert error.value.code == "MODULE_ROUTE_COLLISION"
    assert str(error.value) == "MODULE_ROUTE_COLLISION"


def test_duplicate_route_inside_one_module_is_rejected(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import (
        ModuleMountError,
        module_routers,
        validate_route_collisions,
    )

    router = APIRouter()
    router.add_api_route("/api/duplicate", lambda: {"first": True}, methods=["POST"])
    router.add_api_route("/api/duplicate", lambda: {"second": True}, methods=["POST"])
    manifest = _manifest(
        tmp_path,
        "duplicate",
        router_factories=("modules.duplicate:create_router",),
    )
    mounted = module_routers(
        (manifest,),
        resolve_entry_point=lambda _entry: lambda: router,
    )

    with pytest.raises(ModuleMountError) as error:
        validate_route_collisions((), mounted)
    assert error.value.code == "MODULE_ROUTE_COLLISION"


def test_router_mount_preserves_user_and_admin_dependencies(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_routers

    router = APIRouter()

    @router.get("/api/member", dependencies=[Depends(require_user)])
    async def member():
        return {"ok": True}

    @router.post("/api/manage", dependencies=[Depends(require_admin)])
    async def manage():
        return {"ok": True}

    manifest = _manifest(
        tmp_path,
        "secure",
        router_factories=("modules.secure:create_router",),
    )

    mounted = module_routers(
        (manifest,),
        resolve_entry_point=lambda _entry: lambda: router,
    )

    assert len(mounted) == 1
    assert require_user in _dependency_calls(mounted[0].router)
    assert require_admin in _dependency_calls(mounted[0].router)


def test_broken_panel_does_not_hide_healthy_panel(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_panels, render_module_panels

    rendered: list[str] = []
    failures: list[tuple[str, str]] = []

    def broken() -> None:
        raise RuntimeError("secret internal detail")

    def healthy() -> None:
        rendered.append("healthy")

    manifests = (
        _manifest(tmp_path, "broken", panel_builder="modules.broken:build_panel"),
        _manifest(tmp_path, "healthy", panel_builder="modules.healthy:build_panel"),
    )
    builders = {
        "modules.broken:build_panel": broken,
        "modules.healthy:build_panel": healthy,
    }

    panels = module_panels(manifests, resolve_entry_point=builders.__getitem__)
    render_module_panels(
        panels,
        on_error=lambda module_id, code: failures.append((module_id, code)),
    )

    assert rendered == ["healthy"]
    assert failures == [("broken", "MODULE_PANEL_UNAVAILABLE")]
    assert "secret" not in repr(failures)


def test_module_router_can_be_included_without_wrapper(tmp_path: Path) -> None:
    from proxy.services.les_module_mount_service import module_routers

    router = APIRouter()
    router.add_api_route("/api/module-health", lambda: {"ok": True}, methods=["GET"])
    manifest = _manifest(
        tmp_path,
        "health",
        router_factories=("modules.health:create_router",),
    )
    mounted = module_routers(
        (manifest,),
        resolve_entry_point=lambda _entry: lambda: router,
    )
    app = FastAPI()
    app.include_router(mounted[0].router)

    assert any(getattr(route, "path", "") == "/api/module-health" for route in app.routes)
