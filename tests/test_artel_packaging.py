from pathlib import Path
import zipfile

from tools import build_artel_release, check_atlas_bundle_budget


ROOT = Path(__file__).resolve().parents[1]


def test_artel_release_required_files_exist():
    build_artel_release.validate_source(ROOT / "products" / "artel")


def test_artel_release_excludes_binary_and_legacy_build_output():
    source = ROOT / "products" / "artel"

    assert build_artel_release.is_excluded(source / "Dist" / "MyVeras.dll", source)
    assert build_artel_release.is_excluded(source / "backend" / "Agnostis.Api" / "bin" / "Release" / "x.dll", source)
    assert build_artel_release.is_excluded(source / "backend" / "Agnostis.Api" / "obj" / "project.assets.json", source)
    assert not build_artel_release.is_excluded(source / "backend" / "Agnostis.Api" / "Program.cs", source)


def test_artel_release_archive_contains_hand_test_surface(tmp_path):
    target = build_artel_release.build_archive(
        ROOT / "products" / "artel",
        tmp_path,
        "artel-test",
    )

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())

    assert "artel-test/ARTEL_MANIFEST.json" in names
    assert "artel-test/RUNBOOK_HAND_TEST.md" in names
    assert "artel-test/app/index.html" in names
    assert "artel-test/backend/Agnostis.Api/Program.cs" in names
    assert "artel-test/BUILD.md" not in names
    assert all("/bin/" not in name and "/obj/" not in name for name in names)
    assert all("/MyVeras" not in name for name in names)


def test_atlas_bundle_budget_current_standalone():
    failures = check_atlas_bundle_budget.check_budget(ROOT / "standalone" / "cad_bim_viewer")

    assert failures == []
