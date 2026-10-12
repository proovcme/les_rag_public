from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _contract_api() -> tuple[str, type[Exception], type[Any], Any]:
    try:
        from proxy.services.les_module_contracts import (
            MODULE_API_VERSION,
            ModuleContractError,
            ModuleManifest,
            validate_manifest,
        )
    except ModuleNotFoundError:
        pytest.fail("les_module_contracts is not implemented")
    return MODULE_API_VERSION, ModuleContractError, ModuleManifest, validate_manifest


def _service_api() -> tuple[Any, Any, Any]:
    try:
        from proxy.services.les_module_service import (
            load_enabled_modules,
            module_registry_snapshot,
            route_module,
        )
    except ImportError:
        pytest.fail("explicit feature-module loader is not implemented")
    return load_enabled_modules, module_registry_snapshot, route_module


def _manifest(default_skill_path: Path, **overrides: object) -> Any:
    module_api_version, _, manifest_type, _ = _contract_api()
    values: dict[str, object] = {
        "api_version": module_api_version,
        "module_id": "sample_module",
        "title": "Аудит ПД",
        "icon": "fact_check",
        "router_factories": ("fixture_modules.sample_module.module:get_router",),
        "panel_builder": "fixture_modules.sample_module.module:build_panel",
        "chat_handler_factories": ("fixture_modules.sample_module.module:get_chat_handler",),
        "skill_path": str(default_skill_path),
        "capabilities": ("checklist_review", "evidence_export"),
    }
    values.update(overrides)
    return manifest_type(**values)


def _write_config(path: Path, modules: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps({"schema": "les.module-registry.v1", "modules": modules}),
        encoding="utf-8",
    )
    return path


def _write_fixture_module(root: Path, module_id: str = "sample_module") -> str:
    package = root / "fixture_modules"
    module_package = package / module_id
    package.mkdir()
    module_package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (module_package / "__init__.py").write_text("", encoding="utf-8")
    (module_package / "SKILL.md").write_text("# Fixture skill\n", encoding="utf-8")
    (module_package / "module.py").write_text(
        """from pathlib import Path
from proxy.services.les_module_contracts import ModuleManifest

def get_manifest():
    return ModuleManifest(
        api_version="1.0",
        module_id="sample_module",
        title="Аудит ПД",
        icon="fact_check",
        router_factories=("fixture_modules.sample_module.module:get_router",),
        panel_builder="fixture_modules.sample_module.module:build_panel",
        chat_handler_factories=("fixture_modules.sample_module.module:get_chat_handler",),
        skill_path=str(Path(__file__).with_name("SKILL.md")),
        capabilities=("checklist_review", "evidence_export"),
    )

def get_router():
    return "router"

def build_panel():
    return "panel"

def get_chat_handler():
    return "handler"
""",
        encoding="utf-8",
    )
    return "fixture_modules.sample_module.module:get_manifest"


@pytest.fixture(autouse=True)
def _clear_fixture_imports() -> None:
    yield
    for name in tuple(sys.modules):
        if name == "fixture_modules" or name.startswith("fixture_modules."):
            sys.modules.pop(name, None)


@pytest.mark.parametrize("api_version", ["2.0", "1.1", "invalid"])
def test_manifest_rejects_incompatible_api_version(tmp_path: Path, api_version: str) -> None:
    _, contract_error, _, validate_manifest = _contract_api()
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Skill\n", encoding="utf-8")

    with pytest.raises(contract_error) as caught:
        validate_manifest(_manifest(skill, api_version=api_version), "sample_module")

    assert caught.value.code == "MODULE_API_INCOMPATIBLE"


def test_manifest_rejects_declared_id_that_differs_from_config(tmp_path: Path) -> None:
    _, contract_error, _, validate_manifest = _contract_api()
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Skill\n", encoding="utf-8")

    with pytest.raises(contract_error) as caught:
        validate_manifest(_manifest(skill, module_id="another_module"), "sample_module")

    assert caught.value.code == "MODULE_ID_MISMATCH"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"module_id": "../audit"}, "MODULE_ID_INVALID"),
        ({"capabilities": ("review", "review")}, "MODULE_CAPABILITY_DUPLICATE"),
        ({"router_factories": ("not a dotted entry point",)}, "MODULE_ENTRY_POINT_INVALID"),
        ({"skill_path": "missing/SKILL.md"}, "MODULE_SKILL_MISSING"),
    ],
)
def test_manifest_rejects_unsafe_or_incomplete_contract(
    tmp_path: Path,
    overrides: dict[str, object],
    reason_code: str,
) -> None:
    _, contract_error, _, validate_manifest = _contract_api()
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Skill\n", encoding="utf-8")

    with pytest.raises(contract_error) as caught:
        validate_manifest(_manifest(skill, **overrides), "sample_module")

    assert caught.value.code == reason_code


def test_loader_imports_only_explicit_enabled_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_enabled_modules, module_registry_snapshot, _ = _service_api()
    entry_point = _write_fixture_module(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    config = _write_config(
        tmp_path / "modules.json",
        [
            {"module_id": "sample_module", "enabled": True, "manifest": entry_point},
            {
                "module_id": "disabled_module",
                "enabled": False,
                "manifest": "fixture_modules.disabled_module.module:get_manifest",
            },
        ],
    )

    loaded = load_enabled_modules(config, package="fixture_modules")

    assert tuple(item.module_id for item in loaded) == ("sample_module",)
    diagnostics = module_registry_snapshot()["feature_modules"]
    assert diagnostics["registry"]["status"] == "ready"
    assert diagnostics["modules"]["sample_module"] == {
        "status": "enabled",
        "api_version": "1.0",
        "capabilities": ["checklist_review", "evidence_export"],
        "reason_code": None,
    }
    assert diagnostics["modules"]["disabled_module"]["reason_code"] == "MODULE_DISABLED"


def test_unknown_entry_point_disables_only_that_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_enabled_modules, module_registry_snapshot, _ = _service_api()
    entry_point = _write_fixture_module(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    config = _write_config(
        tmp_path / "modules.json",
        [
            {
                "module_id": "sample_module",
                "enabled": True,
                "manifest": entry_point.replace("get_manifest", "missing_factory"),
            }
        ],
    )

    assert load_enabled_modules(config, package="fixture_modules") == ()
    disabled = module_registry_snapshot()["feature_modules"]["modules"]["sample_module"]
    assert disabled["status"] == "disabled"
    assert disabled["reason_code"] == "MODULE_ENTRY_POINT_UNAVAILABLE"


def test_manifest_factory_failure_is_bounded_to_that_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_point = _write_fixture_module(tmp_path)
    module_file = tmp_path / "fixture_modules" / "sample_module" / "module.py"
    module_file.write_text(
        "def get_manifest():\n    raise KeyError('private failure detail')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    config = _write_config(
        tmp_path / "modules.json",
        [{"module_id": "sample_module", "enabled": True, "manifest": entry_point}],
    )
    load_enabled_modules, module_registry_snapshot, _ = _service_api()

    assert load_enabled_modules(config, package="fixture_modules") == ()
    disabled = module_registry_snapshot()["feature_modules"]["modules"]["sample_module"]
    assert disabled == {
        "status": "disabled",
        "api_version": None,
        "capabilities": [],
        "reason_code": "MODULE_ENTRY_POINT_UNAVAILABLE",
    }


def test_unsafe_config_id_fails_closed_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_point = _write_fixture_module(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    config = _write_config(
        tmp_path / "modules.json",
        [{"module_id": "../sample_module", "enabled": False, "manifest": entry_point}],
    )
    load_enabled_modules, module_registry_snapshot, _ = _service_api()

    assert load_enabled_modules(config, package="fixture_modules") == ()
    diagnostics = module_registry_snapshot()["feature_modules"]
    assert diagnostics["registry"] == {
        "status": "disabled",
        "reason_code": "MODULE_CONFIG_INVALID",
    }
    assert diagnostics["modules"] == {}
    assert "fixture_modules.sample_module.module" not in sys.modules


def test_duplicate_module_ids_fail_closed_without_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_enabled_modules, module_registry_snapshot, _ = _service_api()
    entry_point = _write_fixture_module(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    config = _write_config(
        tmp_path / "modules.json",
        [
            {"module_id": "sample_module", "enabled": True, "manifest": entry_point},
            {"module_id": "sample_module", "enabled": True, "manifest": entry_point},
        ],
    )

    assert load_enabled_modules(config, package="fixture_modules") == ()
    diagnostics = module_registry_snapshot()["feature_modules"]
    assert diagnostics["registry"]["status"] == "disabled"
    assert diagnostics["registry"]["reason_code"] == "MODULE_CONFIG_DUPLICATE_ID"
    assert "fixture_modules.sample_module.module" not in sys.modules


def test_malformed_config_fails_closed_and_keeps_legacy_router(tmp_path: Path) -> None:
    load_enabled_modules, module_registry_snapshot, route_module = _service_api()
    config = tmp_path / "modules.json"
    config.write_text("{not-json", encoding="utf-8")
    expected_module = route_module("Дай смету по ВОР", mode="auto")

    assert load_enabled_modules(config) == ()
    assert route_module("Дай смету по ВОР", mode="auto") == expected_module
    diagnostics = module_registry_snapshot()["feature_modules"]
    assert diagnostics["registry"]["status"] == "disabled"
    assert diagnostics["registry"]["reason_code"] == "MODULE_CONFIG_INVALID"
    assert "smeta" in module_registry_snapshot()


def test_empty_registry_keeps_legacy_snapshot_and_routing(tmp_path: Path) -> None:
    load_enabled_modules, module_registry_snapshot, route_module = _service_api()
    config = _write_config(tmp_path / "modules.json", [])
    before = route_module("Проверь раздел РД по ГОСТ", mode="auto")

    assert load_enabled_modules(config) == ()

    snapshot = module_registry_snapshot()
    assert route_module("Проверь раздел РД по ГОСТ", mode="auto") == before
    assert snapshot["smeta"]["title"] == "Сметы"
    assert snapshot["contracts"]["title"] == "Договоры"
    assert snapshot["feature_modules"] == {
        "schema": "les.feature-modules.v1",
        "registry": {"status": "ready", "reason_code": None},
        "modules": {},
    }


def test_repository_registry_is_explicitly_empty() -> None:
    load_enabled_modules, module_registry_snapshot, _ = _service_api()

    assert tuple(load_enabled_modules()) == ()
    assert module_registry_snapshot()["feature_modules"]["modules"] == {}