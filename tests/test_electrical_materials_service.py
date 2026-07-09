from proxy.services.electrical_materials_service import normalize_electrical_material_table


def test_normalize_electrical_material_table_reads_vor_cable_row():
    table = [
        ["Поз.", "Наименование работ", "Ед. изм.", "Кол-во", "Примечание"],
        ["1", "2", "3", "4", "5"],
        ["12", "Кабель ППГнг-HF 3х2,5", "м", "125,5", ""],
    ]

    result = normalize_electrical_material_table(table, source_ref="vor.pdf#page=10#table=1")

    assert result["row_count"] == 1
    row = result["rows"][0]
    assert row["position"] == "12"
    assert row["item_kind"] == "cable"
    assert row["cable_mark"] == "ППГнг-HF 3х2,5"
    assert row["cable_cores"] == 3
    assert row["cable_section_mm2"] == 2.5
    assert row["quantity_m"] == 125.5
    assert row["source_ref"].endswith("#row=3")


def test_normalize_electrical_material_table_repairs_so_mojibake():
    table = [
        ["Ïîç.", "Íàèìåíîâàíèå è òåõíè÷åñêàÿ õàðàêòåðèñòèêà", "Åä. èçìåðåíèÿ", "Êîë.", "Ïðèìå÷àíèå"],
        ["1", "Ùèò îñâåùåíèÿ ÙÎ1.2.2", "êîìïë.", "1", "Àíàëîãè÷íî ÙÎ1.1.1"],
    ]

    result = normalize_electrical_material_table(table, source_ref="so.pdf#page=2#table=1")

    row = result["rows"][0]
    assert row["name"] == "Щит освещения ЩО1.2.2"
    assert row["unit"] == "компл."
    assert row["quantity"] == 1.0
    assert row["item_kind"] == "panel"
    assert row["note"] == "Аналогично ЩО1.1.1"


def test_normalize_electrical_material_table_tracks_sections_and_lighting():
    table = [
        ["Поз.", "Наименование работ", "Ед. изм.", "Кол-во", "Примечание"],
        ["3", "Монтаж осветительного оборудования", "", "", ""],
        ["3.6", "Монтаж светильника светодиодного OPTIMA.PRS ECO LED 595 4000K", "шт.", "588", "3,4 кг/шт."],
    ]

    result = normalize_electrical_material_table(table, source_ref="vor.pdf#page=5#table=1")

    section, row = result["rows"]
    assert section["item_kind"] == "section"
    assert row["item_kind"] == "lighting"
    assert row["section"] == "Монтаж осветительного оборудования"
    assert row["quantity"] == 588.0


def test_normalize_electrical_material_table_does_not_mix_busbar_and_cable_socket_with_cable():
    table = [
        ["Поз.", "Наименование работ", "Ед. изм.", "Кол-во", "Примечание"],
        ["2.1", "Монтаж шинопровода 1Ш1.1 закрытого магистрального переменного тока", "м", "81", ""],
        ["5.8", "Монтаж розетки кабельной открытой установки 2P+PE, 63А, IP66", "шт.", "9", ""],
    ]

    result = normalize_electrical_material_table(table, source_ref="vor.pdf#page=4#table=1")

    busbar, socket = result["rows"]
    assert busbar["item_kind"] == "busbar"
    assert busbar["quantity_m"] == 81.0
    assert socket["item_kind"] == "equipment"
    assert socket["quantity_m"] is None


def test_normalize_electrical_material_table_extracts_vor_technical_attributes():
    table = [
        ["Поз.", "Наименование работ", "Ед. изм.", "Кол-во", "Примечание"],
        [
            "12.7",
            "Прокладка кабеля ВВГнг(A)-LS 3х4-0,66 (dкаб=10,8 мм) на высоте 9,5 метров",
            "м",
            "3000",
            "0,24 кг/м",
        ],
    ]

    result = normalize_electrical_material_table(table, source_ref="ИОС.ЭС-ВОР.pdf#page=10#table=1")

    row = result["rows"][0]
    assert row["doc_role"] == "vor"
    assert row["work_action"] == "lay"
    assert row["cable_diameter_mm"] == 10.8
    assert row["install_height_m"] == 9.5
    assert row["unit_mass_kg"] == 0.24
    assert row["total_mass_kg"] == 720.0


def test_normalize_electrical_material_table_reads_kunrs_cable_not_kg_note():
    table = [
        ["Поз.", "Наименование работ", "Ед. изм.", "Кол-во", "Примечание"],
        [
            "12.34",
            "Прокладка кабеля КунРс Внг(А)-FRLS 3х1,5 (dкаб=11,5 мм) в смонтированных лотках",
            "м",
            "3500",
            "0,12 кг/м",
        ],
    ]

    result = normalize_electrical_material_table(table, source_ref="ИОС.ЭС-ВОР.pdf#page=11#table=1")

    row = result["rows"][0]
    assert row["item_kind"] == "cable"
    assert row["cable_mark"] == "КунРс Внг(А)-FRLS 3х1,5"
    assert row["cable_cores"] == 3
    assert row["cable_section_mm2"] == 1.5
    assert row["unit_mass_kg"] == 0.12


def test_normalize_electrical_material_table_extracts_so_equipment_attributes():
    table = [
        ["Поз.", "Наименование", "Ед. измерения", "Кол.", "Примечание"],
        ["1", "Щит ГРЩ1 2100х9000х800 мм, 3000 кг, IP31, 1600А, 400В", "компл.", "1", ""],
        ["2", "Устройство компенсации реактивной мощности 150 кВАР УКРМ", "компл.", "2", ""],
        ["3", "Ящик с трансформатором ОСО ЯТП 220/24В, IP54, 250Вт 3 автомата", "шт.", "50", ""],
    ]

    result = normalize_electrical_material_table(table, source_ref="ИОС.ЭС-СО.pdf#page=1#table=1")

    panel, ukrm, box = result["rows"]
    assert panel["doc_role"] == "so"
    assert panel["ip_rating"] == "IP31"
    assert panel["rated_current_a"] == 1600.0
    assert panel["voltage_v"] == 400.0
    assert panel["dimensions_mm"] == [2100, 9000, 800]
    assert ukrm["rated_reactive_power_kvar"] == 150.0
    assert box["ip_rating"] == "IP54"
    assert box["voltage_v"] == 220.0
    assert box["voltages_v"] == [220.0, 24.0]
    assert box["rated_power_w"] == 250.0
