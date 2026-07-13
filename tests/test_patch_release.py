from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import patch_release


ROOT = Path(__file__).resolve().parents[1]


def test_patch_release_contract_separates_product_and_build(tmp_path):
    contract = tmp_path / "version.json"
    contract.write_text(
        json.dumps(
            {
                "product_version": "1.2.3",
                "build_number": 44,
                "desktop_version": "5.1.44",
            }
        ),
        encoding="utf-8",
    )

    assert patch_release.load_contract(contract)["product_version"] == "1.2.3"


@pytest.mark.parametrize(
    ("product", "build", "desktop"),
    (("1.2", 44, "5.1.44"), ("1.2.3.4", 44, "5.1.44"), ("1.2.3", 44, "5.1.45")),
)
def test_patch_release_rejects_ambiguous_version_contract(tmp_path, product, build, desktop):
    contract = tmp_path / "version.json"
    contract.write_text(
        json.dumps(
            {"product_version": product, "build_number": build, "desktop_version": desktop}
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        patch_release.load_contract(contract)


def test_windows_patch_release_is_fail_closed_and_isolated():
    source = (ROOT / "tools/windows_patch_release.ps1").read_text(encoding="utf-8")

    assert "LES-release-smoke" in source
    assert "@($InstallRoot, $StateRoot)" in source
    assert "does not match requested build commit" in source
    assert "windows_release_smoke.ps1" in source
    assert "Get-FileHash" in source
    assert "git -C $RepoRoot status --porcelain" in source
    assert '"--build-number", [string]$BuildNumber' in source


def test_makefile_exposes_one_patch_release_entrypoint():
    source = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "patch-release:" in source
    assert "tools/patch_release.py $(PATCH_RELEASE_ARGS)" in source
