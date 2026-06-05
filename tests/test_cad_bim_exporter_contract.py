import json
from pathlib import Path

from proxy.services.cad_bim_graph import import_payload


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cad_bim"


def test_autocad_export_payload_imports_as_cad_bim_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.loads((FIXTURES / "autocad_export_sample.cad_bim_graph.json").read_text(encoding="utf-8"))

    result = import_payload(payload, source="autocad_export_sample.cad_bim_graph.json", source_kind="json", profile="autocad")

    assert result.profile == "autocad"
    assert result.elements == 3
    assert result.relations == 2
    assert result.properties >= 6
    text = (tmp_path / result.projection_path).read_text(encoding="utf-8")
    assert "CAD/BIM JSON projection (autocad)" in text
    assert "A-DETAIL" in text
    assert "Узел УК-1" in text


def test_revit_export_payload_imports_parameters_and_levels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.loads((FIXTURES / "revit_export_sample.cad_bim_graph.json").read_text(encoding="utf-8"))

    result = import_payload(payload, source="revit_export_sample.cad_bim_graph.json", source_kind="json", profile="revit")

    assert result.profile == "revit"
    assert result.elements == 2
    assert result.relations == 1
    assert result.properties >= 4
    text = (tmp_path / result.projection_path).read_text(encoding="utf-8")
    assert "CAD/BIM JSON projection (revit)" in text
    assert "Level 01" in text
    assert "EI 60" in text
    assert "vertices" not in text
    assert "faces" not in text


def test_autodesk_exporters_share_universal_destination_config():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "exporters" / "autocad" / "LES.AutoCAD.JsonExport" / "LesUpload.cs",
        root / "exporters" / "revit" / "LES.Revit.JsonExport" / "LesUpload.cs",
        root / "exporters" / "navisworks" / "LES.Navisworks.JsonExport" / "LesUpload.cs",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "cad_bim_exporter_settings.json" in source
        assert "LesUrls" in source
        assert "CustomUrls" in source
        assert "LocalOutputDir" in source
        assert "EndpointFromCustomUrl" in source


def test_navisworks_exporter_is_in_installer_payload():
    root = Path(__file__).resolve().parents[1]
    project = root / "exporters" / "navisworks" / "LES.Navisworks.JsonExport" / "LES.Navisworks.JsonExport.csproj"
    installer = root / "exporters" / "installer" / "LES.CadBimExporterInstaller" / "Program.cs"
    build = root / "exporters" / "build-exporters-windows.ps1"

    assert project.exists()
    assert "Autodesk.Navisworks.Api.Plugins.dll" in project.read_text(encoding="utf-8")
    navisworks_plugin = (
        root / "exporters" / "navisworks" / "LES.Navisworks.JsonExport" / "LesNavisworksPlugin.cs"
    ).read_text(encoding="utf-8")
    assert "LES.Navisworks.JsonExport" in navisworks_plugin
    assert "LES.Navisworks.JsonPush" in navisworks_plugin
    assert "LES.Navisworks.JsonConfig" in navisworks_plugin
    assert "LES.Navisworks.JsonExport.dll" in installer.read_text(encoding="utf-8")
    assert "NavisworksInstallDir" in build.read_text(encoding="utf-8")
