from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exporters_define_ribbon_buttons_and_push_commands():
    autocad_app = (ROOT / "exporters/autocad/LES.AutoCAD.JsonExport/LesAutoCadApplication.cs").read_text(encoding="utf-8")
    autocad_command = (ROOT / "exporters/autocad/LES.AutoCAD.JsonExport/LesJsonExportCommand.cs").read_text(encoding="utf-8")
    revit_app = (ROOT / "exporters/revit/LES.Revit.JsonExport/LesJsonApplication.cs").read_text(encoding="utf-8")
    push_command = (ROOT / "exporters/revit/LES.Revit.JsonExport/LesJsonPushCommand.cs").read_text(encoding="utf-8")
    installer = (ROOT / "exporters/installer/LES.CadBimExporterInstaller/Program.cs").read_text(encoding="utf-8")

    assert "RibbonTab" in autocad_app
    assert "Push to LES" in autocad_app
    assert "LESJSONPUSH" in autocad_command
    assert "LESJSONCONFIG" in autocad_command
    assert "CreateRibbonTab" in revit_app
    assert "Push\\nto LES" in revit_app
    assert "LesJsonPushCommand" in push_command
    assert "LoadOnAutoCADStartup=\"True\"" in installer
    assert "LESJSONPUSH" in installer
    assert "LES.Revit.JsonExport.LesJsonApplication" in installer


def test_exporter_upload_defaults_use_local_les_and_api_key_header():
    autocad_upload = (ROOT / "exporters/autocad/LES.AutoCAD.JsonExport/LesUpload.cs").read_text(encoding="utf-8")
    revit_upload = (ROOT / "exporters/revit/LES.Revit.JsonExport/LesUpload.cs").read_text(encoding="utf-8")

    for text in (autocad_upload, revit_upload):
        assert "http://127.0.0.1:8050" in text
        assert "/api/cad-bim/import" in text
        assert "X-API-Key" in text
