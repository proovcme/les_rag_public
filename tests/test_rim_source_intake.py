from proxy.smeta_core.source_intake import intake_vor_csv


def test_csv_intake_supports_cp1251_and_user_column_mapping(tmp_path):
    source = tmp_path / "vor.csv"
    source.write_bytes(
        (
            "Позиция;Блок;Описание;Мера;Объем;Комментарий\n"
            "1;Кабельные трассы;Прокладка кабеля;м;400;в лотке\n"
        ).encode("cp1251")
    )
    result = intake_vor_csv(
        source,
        column_map={
            "number": "Позиция",
            "section": "Блок",
            "work_name": "Описание",
            "unit": "Мера",
            "quantity": "Объем",
            "note": "Комментарий",
        },
    )
    assert result["encoding"] == "cp1251"
    assert result["delimiter"] == ";"
    assert result["work_item_count"] == 1
    item = result["work_items"][0]
    assert item["section"] == "Кабельные трассы"
    assert item["title"] == "Прокладка кабеля"
    assert item["quantity"] == 400.0

