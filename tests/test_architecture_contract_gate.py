from pathlib import Path

from tools.architecture_contract_gate import scan_architecture


def _write(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _codes(root: Path) -> set[str]:
    return {item.code for item in scan_architecture(root)}


def test_rejects_parallel_estimate_workbook_name(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/bad.py",
        'NAME = "estimate_build_lsr_workbook"\n',
    )

    assert _codes(tmp_path) == {"PARALLEL_WORKBOOK_TOOL"}


def test_rejects_forced_workbook_regex(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/bad.py",
        """import re

def route(question: str) -> None:
    if re.search("лср", question):
        call("build_lsr_workbook")
""",
    )

    assert "FORCED_WORKBOOK_CALL" in _codes(tmp_path)


def test_rejects_implicit_profile_activation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/startup.py",
        "activate_profile_revision('estimator', revision)\n",
    )

    assert "IMPLICIT_PROFILE_ACTIVATION" in _codes(tmp_path)


def test_allows_explicit_profile_activation_boundary(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/routers/profiles.py",
        "activate_profile_revision('estimator', revision)\n",
    )

    assert "IMPLICIT_PROFILE_ACTIVATION" not in _codes(tmp_path)


def test_rejects_unregistered_direct_model_http_call(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/new_model_path.py",
        """import httpx

def generate(base_url: str, payload: dict):
    return httpx.post(f"{base_url}/v1/chat/completions", json=payload)
""",
    )

    assert "INFERENCE_GOVERNOR_BYPASS" in _codes(tmp_path)


def test_inference_baseline_is_exact_path_and_function(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "backend/ocr_parser.py",
        """import httpx

def ocr_page(base_url: str, payload: dict):
    return httpx.post(f"{base_url}/v1/chat/completions", json=payload)

def new_ocr_route(base_url: str, payload: dict):
    return httpx.post(f"{base_url}/v1/chat/completions", json=payload)
""",
    )

    findings = scan_architecture(tmp_path)
    bypasses = [item for item in findings if item.code == "INFERENCE_GOVERNOR_BYPASS"]
    assert [(item.path, item.detail) for item in bypasses] == [
        ("backend/ocr_parser.py", "direct model HTTP call in new_ocr_route()"),
    ]


def test_rejects_fixture_claimed_as_live_acceptance(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "reports/result.md",
        "Synthetic fixture — live model quality accepted.\n",
    )

    assert "FAKE_LIVE_ACCEPTANCE" in _codes(tmp_path)


def test_never_reads_private_archive(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "local_private_archive/secret.py",
        'NAME = "estimate_build_lsr_workbook"\n',
    )

    assert scan_architecture(tmp_path) == []


def test_gate_self_test_fixtures_are_not_product_findings(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_architecture_contract_gate.py",
        'MUTATION = "estimate_build_lsr_workbook"\n',
    )
    _write(
        tmp_path,
        "tools/architecture_contract_gate.py",
        'PATTERN = r"estimate_.*workbook"\n',
    )

    assert scan_architecture(tmp_path) == []


def test_rejects_engine_name_routing_in_provider_neutral_chat_boundary(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/canonical_route_service.py",
        """def complete(connection):
    if connection.display_name == "Ollama":
        return native_call(connection)
    return common_call(connection)
""",
    )

    assert "ENGINE_NAME_ROUTING" in _codes(tmp_path)


def test_allows_provider_names_only_inside_legacy_importer(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "proxy/services/model_connection_resolver_service.py",
        """class LegacyConnectionImporter:
    def import_effective(self, provider):
        if provider == "Ollama":
            return "legacy:ollama"
""",
    )

    assert "ENGINE_NAME_ROUTING" not in _codes(tmp_path)
