from pathlib import Path
import zipfile

from tools import build_atlas_release


ROOT = Path(__file__).resolve().parents[1]


def test_atlas_release_required_files_exist():
    build_atlas_release.validate_source(ROOT / "standalone" / "cad_bim_viewer")


def test_atlas_release_excludes_private_sample_dirs():
    source = ROOT / "standalone" / "cad_bim_viewer"

    assert build_atlas_release.is_excluded(source / "JSON" / "private.json", source)
    assert build_atlas_release.is_excluded(source / "ifc-sample" / "private.ifc", source)
    assert build_atlas_release.is_excluded(source / ".DS_Store", source)
    assert not build_atlas_release.is_excluded(source / "models" / "demo.cad_bim_graph.json", source)


def test_atlas_release_archive_contains_manifest(tmp_path):
    target = build_atlas_release.build_archive(
        ROOT / "standalone" / "cad_bim_viewer",
        tmp_path,
        "atlas-test",
    )

    assert target.exists()
    assert target.name == "atlas-test.zip"
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    assert "atlas-test/ATLAS_MANIFEST.json" in names
    assert "atlas-test/INSTALL.md" in names
