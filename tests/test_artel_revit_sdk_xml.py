from pathlib import Path

from tools import seed_artel_revit_factory_sources as sources


SAMPLE_XML = """<?xml version="1.0"?>
<doc>
  <assembly>"RevitAPI"</assembly>
  <members>
    <member name="T:Autodesk.Revit.DB.SampleType">
      <summary>A sample <see cref="T:Autodesk.Revit.DB.Element"/> type.</summary>
      <since>2024</since>
    </member>
    <member name="M:Autodesk.Revit.DB.SampleType.Create(System.String)">
      <summary>Creates an item for <paramref name="name"/>.</summary>
      <param name="name">The item name.</param>
      <returns>The created item.</returns>
      <exception cref="T:Autodesk.Revit.Exceptions.ArgumentException">Invalid name.</exception>
    </member>
  </members>
</doc>
"""


def test_parse_revit_sdk_xml_preserves_exact_documentation_ids(tmp_path: Path):
    xml_path = tmp_path / "RevitAPI.xml"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")

    assembly, members = sources.parse_sdk_xml(xml_path)

    assert assembly == "RevitAPI"
    assert [member["kind"] for member in members] == ["type", "method"]
    assert members[1]["documentation_id"] == "M:Autodesk.Revit.DB.SampleType.Create(System.String)"
    rendered_sections = "\n".join(body for _, body in members[0]["sections"])
    assert "T:Autodesk.Revit.DB.Element" in rendered_sections


def test_write_revit_sdk_xml_shards_records_version_and_provenance(tmp_path: Path):
    xml_path = tmp_path / "RevitAPI.xml"
    xml_path.write_text(SAMPLE_XML, encoding="utf-8")
    artel_root = tmp_path / "ARTEL"

    targets = sources.write_sdk_xml_shards(
        xml_path,
        tmp_path,
        api_version="2024.1.10.25",
        package_url="https://api.nuget.org/example.nupkg",
        package_sha256="abc123",
        shard_members=1,
        artel_content_root=artel_root,
    )

    assert len(targets) == 2
    first = targets[0].read_text(encoding="utf-8")
    second = targets[1].read_text(encoding="utf-8")
    assert "Document type: REVIT_API_SDK_DOC" in first
    assert "Revit API version: 2024.1.10.25" in first
    assert "Package SHA-256: abc123" in first
    assert "T:Autodesk.Revit.DB.SampleType" in first
    assert "M:Autodesk.Revit.DB.SampleType.Create(System.String)" in second
    assert "Exception `T:Autodesk.Revit.Exceptions.ArgumentException`" in second
