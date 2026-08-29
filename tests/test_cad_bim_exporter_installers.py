from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_exporters_define_ribbon_buttons_and_push_commands():
    autocad_app = (ROOT / "exporters/autocad/LES.AutoCAD.JsonExport/LesAutoCadApplication.cs").read_text(encoding="utf-8")
    autocad_command = (ROOT / "exporters/autocad/LES.AutoCAD.JsonExport/LesJsonExportCommand.cs").read_text(encoding="utf-8")
    revit_app = (ROOT / "exporters/revit/LES.Revit.JsonExport/LesJsonApplication.cs").read_text(encoding="utf-8")
    revit_push = (ROOT / "exporters/revit/LES.Revit.JsonExport/LesJsonPushCommand.cs").read_text(encoding="utf-8")
    installer = (ROOT / "exporters/installer/LES.CadBimExporterInstaller/Program.cs").read_text(encoding="utf-8")

    assert "RibbonTab" in autocad_app
    assert "Push to LES" in autocad_app
    assert "LESJSONPUSH" in autocad_command
    assert "LESJSONCONFIG" in autocad_command
    assert "CreateRibbonTab" in revit_app
    assert "Push\\nto LES" in revit_app
    assert "LesJsonPushCommand" in revit_push
    assert "LoadOnAutoCADStartup=\"True\"" in installer
    assert "LESJSONPUSH" in installer
    assert "LES.Revit.JsonExport.LesJsonApplication" in installer


def test_exporter_upload_defaults_are_public_and_machine_neutral():
    autocad_upload = (ROOT / "exporters/autocad/LES.AutoCAD.JsonExport/LesUpload.cs").read_text(encoding="utf-8")
    revit_upload = (ROOT / "exporters/revit/LES.Revit.JsonExport/LesUpload.cs").read_text(encoding="utf-8")
    navisworks_upload = (ROOT / "exporters/navisworks/LES.Navisworks.JsonExport/LesUpload.cs").read_text(encoding="utf-8")
    installer = (ROOT / "exporters/installer/LES.CadBimExporterInstaller/Program.cs").read_text(encoding="utf-8")
    build_script = (ROOT / "exporters/build-exporters-windows.ps1").read_text(encoding="utf-8")

    for text in (autocad_upload, revit_upload, navisworks_upload, installer, build_script):
        assert "http://127.0.0.1:8050" in text
        assert "10.195.146." not in text
        assert "les.ovc.me" not in text

    for text in (autocad_upload, revit_upload, navisworks_upload):
        assert "/api/cad-bim/import" in text
        assert "X-API-Key" in text
