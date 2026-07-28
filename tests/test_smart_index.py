from backend.smart_index import build_smart_plan


def test_general_rag_excludes_module_owned_smeta_projection(tmp_path):
    service = tmp_path / "TABLE_SMETA" / "SMETA_SERVICE" / "collection_01.md"
    service.parent.mkdir(parents=True)
    service.write_text(
        "# ГЭСН 01\nНавигационная карточка сборника",
        encoding="utf-8",
    )
    user = tmp_path / "PROJECTS" / "user_note.md"
    user.parent.mkdir(parents=True)
    user.write_text("# Пользовательский проект\nКабельный журнал", encoding="utf-8")

    result = build_smart_plan(tmp_path)

    assert "SMETA_SERVICE_Index" not in result["plan"]
    assert result["rejected_reasons"]["module_owned_source"] == 1
    assert result["total_files"] == 1
    assert any(
        item["path"].endswith("collection_01.md")
        and item["reason"] == "module_owned_source"
        for item in result["rejected"]
    )
