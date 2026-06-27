from pathlib import Path

from tools import seed_artel_fop_profiles as seed


def test_parse_revit_shared_parameter_file_and_render_markdown(tmp_path):
    fop = tmp_path / "FOP2021.txt"
    fop.write_text(
        "\n".join(
            [
                "# This is a Revit shared parameter file.",
                "*META\tVERSION\tMINVERSION",
                "META\t2\t1",
                "*GROUP\tID\tNAME",
                "GROUP\t1\t01 Обязательные ОБЩИЕ",
                "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE\tDESCRIPTION\tUSERMODIFIABLE",
                "PARAM\t11111111-1111-1111-1111-111111111111\tADSK_Наименование\tTEXT\t\t1\t1\tНазвание\t1",
                "PARAM\t22222222-2222-2222-2222-222222222222\tADSK_Код изделия\tTEXT\t\t1\t1\tКод\t1",
            ]
        ),
        encoding="utf-8",
    )

    parsed = seed.parse_shared_parameters(seed.read_text(fop))
    markdown = seed.render_markdown(fop, "FOP2021", parsed)

    assert parsed["groups"] == {"1": "01 Обязательные ОБЩИЕ"}
    assert len(parsed["params"]) == 2
    assert "ARTEL FOP Shared Parameter Profile" in markdown
    assert "ADSK_Наименование" in markdown
    assert "11111111-1111-1111-1111-111111111111" in markdown
    assert "01 Обязательные ОБЩИЕ" in markdown


def test_write_fop_projection_under_artel(tmp_path):
    fop = tmp_path / "FOP2021.txt"
    fop.write_text(
        "\n".join(
            [
                "# This is a Revit shared parameter file.",
                "*GROUP\tID\tNAME",
                "GROUP\t1\tMain",
                "*PARAM\tGUID\tNAME\tDATATYPE\tDATACATEGORY\tGROUP\tVISIBLE",
                "PARAM\t11111111-1111-1111-1111-111111111111\tADSK_Наименование\tTEXT\t\t1\t1",
            ]
        ),
        encoding="utf-8",
    )

    target = seed.write_projection(fop, tmp_path)

    assert target == tmp_path / "RAG_Content" / "ARTEL" / "fop_profiles" / "FOP2021.md"
    assert "ADSK_Наименование" in target.read_text(encoding="utf-8")
